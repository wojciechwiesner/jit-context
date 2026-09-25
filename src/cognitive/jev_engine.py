"""JEV Decision & Scoring Engine for Hermes JIT Context OS.

Provides asynchronous, probabilistic decision scoring (~typesafe/jev-latest via OpenRouter
/api/alpha/decisions) and deterministic hybrid token fallback (Invariant I6: Fail-open).
Never on the hot path: prefetch occurs in daemon threads; capsule compilation reads cache in <0.05 ms.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "~typesafe/jev-latest"

_TOKEN_RE = re.compile(r"[\w:\-.]{3,}", re.UNICODE)
_STOP_WORDS = {
    "the", "and", "for", "that", "this", "with", "you", "are", "not",
    "nie", "jest", "tak", "jak", "dla", "oraz", "przez", "ktore", "jako",
    "wiec", "albo", "lecz", "moze", "ktory", "ktora", "czy", "sie",
}
# Reuse cached scores of a previous query when token-set Jaccard similarity reaches this value.
DEFAULT_FUZZY_THRESHOLD = 0.5


def fold_text(text: str) -> str:
    """Lowercase and strip diacritics so 'połączenie' and 'polaczenie' tokenize identically."""
    lowered = text.lower().replace("ł", "l")
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text: str) -> Set[str]:
    """Extract folded semantic tokens (Unicode-aware, diacritics removed) with stopwords removed."""
    if not text:
        return set()
    tokens = set()
    for raw in _TOKEN_RE.findall(fold_text(text)):
        token = raw.strip(".:-_")
        if len(token) >= 3 and token not in _STOP_WORDS:
            tokens.add(token)
    return tokens


def fact_key(value: str) -> str:
    """Content-addressed candidate key, stable across turns even when the fact list changes."""
    return "fact_" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def token_overlap_score(candidate_text: str, query_tokens: Set[str]) -> float:
    """Compute normalized token overlap score between candidate and query tokens."""
    if not query_tokens:
        return 0.0
    ct = tokenize(candidate_text)
    if not ct:
        return 0.0
    return len(ct & query_tokens) / len(ct)


class CircuitBreaker:
    """Thread-safe circuit breaker protecting against upstream API failure storms."""

    def __init__(self, failure_threshold: int = 3, cooldown_s: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.disabled_permanently = False
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        with self._lock:
            if self.disabled_permanently:
                return False
            if self.failure_count >= self.failure_threshold:
                if time.time() - self.last_failure_time < self.cooldown_s:
                    return False
                # Cooldown elapsed, allow a single probe
            return True

    def record_success(self) -> None:
        with self._lock:
            self.failure_count = 0

    def record_failure(self, is_fatal_auth: bool = False) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if is_fatal_auth:
                self.disabled_permanently = True


class JevDecisionScorer:
    """Async probabilistic decision engine with TTL cache and deterministic fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        ttl_s: float = 300.0,
        timeout_s: float = 10.0,
        max_facts: int = 40,
    ) -> None:
        self.api_key = api_key or os.environ.get("JEV_OPENROUTER_KEY", "").strip()
        self.model = model
        self.ttl_s = ttl_s
        self.timeout_s = timeout_s
        self.max_facts = max_facts

        self._cache: Dict[str, Tuple[float, Set[str], Dict[str, float]]] = {}
        self._cache_lock = threading.Lock()
        self._breaker = CircuitBreaker()
        self._inflight: Set[str] = set()
        self._inflight_lock = threading.Lock()
        self.fuzzy_threshold = DEFAULT_FUZZY_THRESHOLD

    def is_available(self) -> bool:
        """True if configured with an API key and circuit breaker is open to requests."""
        return bool(self.api_key) and self._breaker.allow_request()

    def _query_hash(self, query: str) -> str:
        """Hash of the normalized token set, so '?' or word order do not cause a cache miss."""
        tokens = tokenize(query)
        basis = " ".join(sorted(tokens)) if tokens else query.strip().lower()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    def get_cached_scores(self, query: str) -> Optional[Dict[str, float]]:
        """Non-blocking cache lookup (<0.1 ms).

        Exact match on the normalized token set first; otherwise reuses the freshest entry whose
        token-set Jaccard similarity with the query reaches ``fuzzy_threshold``. This lets a
        prefetch fired on turn N serve turn N+1 when the user rephrases or continues the topic.
        Scores are per candidate key, so callers should use content-addressed keys (``fact_key``).
        """
        h = self._query_hash(query)
        q_tokens = tokenize(query)
        now = time.time()
        with self._cache_lock:
            for k in [k for k, (ts, _, _) in self._cache.items() if now - ts > self.ttl_s]:
                del self._cache[k]
            entry = self._cache.get(h)
            if entry is not None:
                return dict(entry[2])
            best: Optional[Tuple[float, float, Dict[str, float]]] = None
            for ts, tokens, scores in self._cache.values():
                sim = _jaccard(q_tokens, tokens)
                if sim >= self.fuzzy_threshold and (best is None or (sim, ts) > (best[0], best[1])):
                    best = (sim, ts, scores)
            return dict(best[2]) if best else None

    def _store_cache(self, query: str, scores: Dict[str, float]) -> None:
        h = self._query_hash(query)
        with self._cache_lock:
            if len(self._cache) > 128:
                # Evict oldest 32 items
                for k in sorted(self._cache, key=lambda x: self._cache[x][0])[:32]:
                    self._cache.pop(k, None)
            self._cache[h] = (time.time(), tokenize(query), dict(scores))

    def prefetch_async(self, query: str, candidates: List[Dict[str, str]]) -> None:
        """Fires an asynchronous daemon prefetch off the hot path."""
        if not self.is_available() or not query or not candidates:
            return

        h = self._query_hash(query)
        with self._inflight_lock:
            if h in self._inflight:
                return
            self._inflight.add(h)

        def _worker():
            try:
                self.score_remote(query, candidates)
            finally:
                with self._inflight_lock:
                    self._inflight.discard(h)

        t = threading.Thread(target=_worker, name=f"jev-prefetch-{h}", daemon=True)
        t.start()

    def score_remote(
        self, query: str, candidates: List[Dict[str, str]]
    ) -> Dict[str, float]:
        """Perform remote HTTP call to OpenRouter Decisions API. Never raises."""
        if not self.api_key or not self._breaker.allow_request():
            return {}

        cached = self.get_cached_scores(query)
        if cached is not None:
            return cached

        sliced = candidates[: self.max_facts]
        if not sliced:
            return {}

        questions = {}
        for i, c in enumerate(sliced):
            k = str(c.get("key", f"item_{i}"))
            val = str(c.get("value", c.get("text", "")))
            questions[f"q_{i}"] = {
                "type": "noul",
                "instructions": f"Fact [{k}: {val}] is relevant for: {query}",
            }

        payload = {
            "model": self.model,
            "state": {"query": query, "task": "evaluate candidate relevance"},
            "questions": questions,
        }

        try:
            req = urllib.request.Request(
                DECISIONS_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "hermes-jit-context-os/0.2.0 (JevBridge)",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            raw_scores = {}
            for i, c in enumerate(sliced):
                qid = f"q_{i}"
                k = str(c.get("key", f"item_{i}"))
                ans = data.get("answers", {}).get(qid, {})
                # Normalize probability
                p = 0.0
                if isinstance(ans, dict):
                    p = float(ans.get("noul", ans.get("probability", ans.get("p", ans.get("score", 0.0)))))
                elif isinstance(ans, (int, float)):
                    p = float(ans)
                raw_scores[k] = p

            self._breaker.record_success()
            self._store_cache(query, raw_scores)
            return raw_scores

        except urllib.error.HTTPError as e:
            is_fatal = e.code in (401, 403)
            self._breaker.record_failure(is_fatal_auth=is_fatal)
            return {}
        except Exception:
            self._breaker.record_failure(is_fatal_auth=False)
            return {}

    def score_remote_detailed(
        self, query: str, candidates: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Perform remote HTTP call to OpenRouter Decisions API returning full verifiable telemetry."""
        t0 = time.time()
        if not self.api_key:
            return {
                "model": self.model,
                "scores": {},
                "remote_call_success": False,
                "fallback_used": True,
                "http_status": 0,
                "latency_ms": 0.0,
                "usage": {},
                "error": "No JEV API key configured (JEV_OPENROUTER_KEY missing)",
            }

        if not self._breaker.allow_request():
            return {
                "model": self.model,
                "scores": {},
                "remote_call_success": False,
                "fallback_used": True,
                "http_status": 0,
                "latency_ms": 0.0,
                "usage": {},
                "error": "Circuit breaker open / cooling down",
            }

        sliced = candidates[: self.max_facts]
        if not sliced:
            return {
                "model": self.model,
                "scores": {},
                "remote_call_success": True,
                "fallback_used": False,
                "http_status": 200,
                "latency_ms": 0.0,
                "usage": {},
                "error": None,
            }

        questions = {}
        for i, c in enumerate(sliced):
            k = str(c.get("key", f"item_{i}"))
            val = str(c.get("value", c.get("text", "")))
            questions[f"q_{i}"] = {
                "type": "noul",
                "instructions": f"Fact [{k}: {val}] is relevant for: {query}",
            }

        payload = {
            "model": self.model,
            "state": {"query": query, "task": "evaluate candidate relevance"},
            "questions": questions,
        }

        try:
            req = urllib.request.Request(
                DECISIONS_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "hermes-jit-context-os/0.2.0 (JevBridge)",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                status_code = resp.status
                body = resp.read().decode("utf-8")
                data = json.loads(body)

            latency_ms = round((time.time() - t0) * 1000, 2)
            raw_scores = {}
            for i, c in enumerate(sliced):
                qid = f"q_{i}"
                k = str(c.get("key", f"item_{i}"))
                ans = data.get("answers", {}).get(qid, {})
                p = 0.0
                if isinstance(ans, dict):
                    p = float(ans.get("noul", ans.get("probability", ans.get("p", ans.get("score", 0.0)))))
                elif isinstance(ans, (int, float)):
                    p = float(ans)
                raw_scores[k] = p

            self._breaker.record_success()
            self._store_cache(query, raw_scores)
            return {
                "model": data.get("model", self.model),
                "scores": raw_scores,
                "remote_call_success": True,
                "fallback_used": False,
                "http_status": status_code,
                "latency_ms": latency_ms,
                "usage": data.get("usage", {}),
                "answers_count": len(raw_scores),
                "error": None,
            }
        except urllib.error.HTTPError as e:
            latency_ms = round((time.time() - t0) * 1000, 2)
            is_fatal = e.code in (401, 403)
            self._breaker.record_failure(is_fatal_auth=is_fatal)
            return {
                "model": self.model,
                "scores": {},
                "remote_call_success": False,
                "fallback_used": True,
                "http_status": e.code,
                "latency_ms": latency_ms,
                "usage": {},
                "error": f"HTTP {e.code}: {e.reason}",
            }
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000, 2)
            self._breaker.record_failure(is_fatal_auth=False)
            return {
                "model": self.model,
                "scores": {},
                "remote_call_success": False,
                "fallback_used": True,
                "http_status": 0,
                "latency_ms": latency_ms,
                "usage": {},
                "error": str(e),
            }

    def rerank_hybrid(
        self, query: str, candidates: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Reranks candidates using cached JEV scores or deterministic token overlap.
        
        Guaranteed non-blocking (<0.1 ms), stable, never drops candidates (Invariant I6).
        """
        if not candidates:
            return []

        scores = self.get_cached_scores(query) or {}
        q_tokens = tokenize(query)

        def _sort_key(item: Dict[str, str]) -> Tuple[float, float]:
            k = str(item.get("key", ""))
            v = str(item.get("value", item.get("text", "")))
            # Priority 1: Jev probability (descending)
            p_score = scores.get(k, 0.0)
            # Priority 2: Deterministic token overlap
            t_score = token_overlap_score(f"{k} {v}", q_tokens)
            return (-p_score, -t_score)

        return sorted(candidates, key=_sort_key)


_GLOBAL_SCORER: Optional[JevDecisionScorer] = None


def get_jev_scorer() -> JevDecisionScorer:
    """Process-wide singleton instance of JevDecisionScorer."""
    global _GLOBAL_SCORER
    if _GLOBAL_SCORER is None:
        _GLOBAL_SCORER = JevDecisionScorer()
    return _GLOBAL_SCORER
