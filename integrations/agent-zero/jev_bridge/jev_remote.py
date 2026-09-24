"""Slot 5: remote Jev scorer (OpenRouter /api/alpha/decisions) + TTL cache.

Never on the hot path: scoring runs in a daemon thread fired at
message_loop_end; the capsule-time reranker only reads the fresh cache.
I6: every failure degrades to empty scores -> deterministic fallback.
Key priority: config jev_openrouter_key > env JEV_OPENROUTER_KEY > data/jev_openrouter_key.txt.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from jev_bridge.http_client import _Breaker

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
KEY_FILE = os.path.join("data", "jev_openrouter_key.txt")

def _plugin_root() -> str:
    """Injectable seam: tests monkeypatch to tmp_path for hermetic runs."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_INFLIGHT: set = set()
_INFLIGHT_LOCK = threading.Lock()


def resolve_key(cfg: Optional[dict] = None) -> str:
    cfg = cfg or {}
    k = str(cfg.get("jev_openrouter_key") or "").strip()
    if k:
        return k
    k = os.environ.get("JEV_OPENROUTER_KEY", "").strip()
    if k:
        return k
    try:
        p = os.path.join(_plugin_root(), KEY_FILE)
        if os.path.isfile(p):
            return open(p, encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""


class JevRemoteScorer:
    """One instance per process; cache is shared via get_shared_scorer()."""

    def __init__(self, api_key: str, model: str = "~typesafe/jev-latest",
                 timeout_s: float = 3.0, ttl_s: float = 300.0,
                 max_facts: int = 40, now_fn=time.time):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.ttl_s = ttl_s
        self.max_facts = max_facts
        self.now = now_fn
        self.breaker = _Breaker(threshold=3, recovery=30.0, now_fn=now_fn)
        self._cache: Dict[str, Tuple[float, Dict[str, float]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- cache
    def _qhash(self, query: str) -> str:
        return hashlib.sha1((query or "").encode("utf-8", "ignore")).hexdigest()

    def cached_scores(self, query: str) -> Dict[str, float]:
        h = self._qhash(query)
        with self._lock:
            item = self._cache.get(h)
            if item is None:
                return {}
            ts, scores = item
            if self.now() - ts > self.ttl_s:
                del self._cache[h]
                return {}
            return dict(scores)

    def _store(self, query: str, scores: Dict[str, float]) -> None:
        h = self._qhash(query)
        with self._lock:
            if len(self._cache) > 64:  # simple LRU-ish eviction
                for k in sorted(self._cache, key=lambda x: self._cache[x][0])[:32]:
                    del self._cache[k]
            self._cache[h] = (self.now(), dict(scores))

    # ------------------------------------------------------------ remote
    def score(self, query: str, facts: List[Dict[str, str]]) -> Dict[str, float]:
        """Blocking API call. Returns {} on any failure or empty input (I6)."""
        if not self.api_key or not query or not facts:
            return {}
        if not self.breaker.can_execute():
            return {}
        questions: Dict[str, dict] = {}
        id2key: Dict[str, str] = {}
        for i, f in enumerate(facts[: self.max_facts]):
            qid = f"q{i}"
            id2key[qid] = str(f.get("key", f"i{i}"))
            val = str(f.get("value", ""))[:160]
            questions[qid] = {
                "type": "noul",
                "instructions": f"Fact [{id2key[qid]}: {val}] is relevant for answering the query.",
            }
        payload = json.dumps({
            "model": self.model,
            "state": {
                "query": query[:2000],
                "task": "select memory facts to inject before answering",
            },
            "questions": questions,
        }).encode("utf-8")
        req = urllib.request.Request(
            DECISIONS_URL, data=payload, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            answers = data.get("answers") or {}
            out: Dict[str, float] = {}
            for qid, ans in answers.items():
                if not isinstance(ans, dict) or qid not in id2key:
                    continue
                try:
                    out[id2key[qid]] = max(0.0, min(1.0, float(ans.get("noul", 0.0))))
                except (TypeError, ValueError):
                    continue
            if not out:
                self.breaker.record_failure()
                return {}
            self.breaker.record_success()
            self._store(query, out)
            return out
        except urllib.error.HTTPError as e:
            self.breaker.record_failure()
            if e.code in (401, 403):
                # fatal auth/limit: dead key -> disable scorer for this process
                self.api_key = ""
            return {}
        except Exception:
            self.breaker.record_failure()
            return {}

    # ------------------------------------------------------------- async
    def prefetch_async(self, query: str, facts: List[Dict[str, str]]) -> bool:
        """Fire-and-forget background scoring. True iff a thread was started."""
        if not query or not facts or not self.api_key:
            return False
        if self.cached_scores(query):
            return False  # fresh cache already covers this query
        h = self._qhash(query)
        with _INFLIGHT_LOCK:
            if h in _INFLIGHT:
                return False
            _INFLIGHT.add(h)

        def _work() -> None:
            try:
                self.score(query, facts)
            except Exception:
                pass  # I6
            finally:
                with _INFLIGHT_LOCK:
                    _INFLIGHT.discard(h)

        threading.Thread(target=_work, name="jev-prefetch", daemon=True).start()
        return True


_SHARED: Optional[JevRemoteScorer] = None
_SHARED_SIG: Optional[tuple] = None


def make_scorer_from_config(cfg: Optional[dict] = None) -> Optional[JevRemoteScorer]:
    """Build scorer; None when disabled or key missing. Silent on failure (I6)."""
    try:
        cfg = cfg or {}
        if not cfg.get("jev_remote_enabled", True):
            return None
        key = resolve_key(cfg)
        if not key:
            return None
        return JevRemoteScorer(
            api_key=key,
            model=str(cfg.get("jev_remote_model", "~typesafe/jev-latest")),
            timeout_s=float(cfg.get("jev_remote_timeout", 3.0)),
            ttl_s=float(cfg.get("jev_remote_ttl", 300)),
            max_facts=int(cfg.get("jev_remote_max_facts", 40)),
        )
    except Exception:
        return None


def get_shared_scorer(cfg: Optional[dict] = None) -> Optional[JevRemoteScorer]:
    """Process-wide singleton so init-wiring and prefetch share one cache."""
    global _SHARED, _SHARED_SIG
    s = make_scorer_from_config(cfg)
    if s is None:
        return None
    sig = (s.api_key[-8:], s.model, s.ttl_s, s.timeout_s, s.max_facts)
    if _SHARED is None or _SHARED_SIG != sig:
        _SHARED = s
        _SHARED_SIG = sig
    return _SHARED
