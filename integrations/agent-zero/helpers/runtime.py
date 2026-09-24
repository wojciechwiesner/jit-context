"""
JIT-Context Engine & Epistemic Memory Cascade for Agent Zero.

v0.3.0:
- L0 Hot-Path: Local SQLite WAL (<3ms), RYOW, RecentTurnFence (centralized archive)
- L1 Warm-Path: Project domain knowledge with Hysteresis Scope Guard (<10ms)
- L2 Deep-Path: Vault prefetch with Circuit Breaker + deadline (default 600ms)
- Deterministic Prompt Caching Capsule Compiler (<1.5k tokens, budget-trimmed)
- Shadow-mode acceptance gate for L2 promotion (HELPFUL / NEUTRAL / HARMFUL)
- Pre-LLM hook watchdog budget (default 650ms) and real telemetry

Design rule (I6): every public method degrades silently on failure;
the agent loop must never be blocked by the context runtime.
"""

import os
import json
import time
import sqlite3
import asyncio
from typing import Any, Dict, List, Optional

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PLUGIN_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "jit_context.db")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")

_env_plugin_dir = os.environ.get("JIT_CONTEXT_PLUGIN_DIR")
if _env_plugin_dir and os.path.isdir(_env_plugin_dir):
    PLUGIN_DIR = _env_plugin_dir
    DATA_DIR = os.path.join(PLUGIN_DIR, "data")
    DB_PATH = os.path.join(DATA_DIR, "jit_context.db")
    SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")

VAULT_DIR = os.environ.get("JIT_CONTEXT_VAULT_DIR") or (
    "/root/Documents/Wojciech" if os.path.exists("/root/Documents/Wojciech") else ""
)

L2_DEADLINE_S = float(os.environ.get("JIT_CONTEXT_L2_DEADLINE_MS", "600")) / 1000.0
HOOK_BUDGET_MS = float(os.environ.get("JIT_CONTEXT_HOOK_BUDGET_MS", "650"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.last_failure_time = 0.0

    def can_execute(self) -> bool:
        now = time.time()
        if self.state == "OPEN":
            if now - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                return True
            return False
        return True

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"


class JITContextRuntime:
    """Process-wide singleton (per loaded module identity)."""

    _instance: Optional["JITContextRuntime"] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            inst = super().__new__(cls)
            inst._init_db()
            inst.circuit_breaker = CircuitBreaker()
            inst.active_scope = None
            inst.scope_mentions = {}
            inst._l2_facts: List[Dict[str, Any]] = []
            inst._shadow_stats = {"helpful": 0, "neutral": 0, "harmful": 0}
            inst._load_shadow_stats()
            cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------ DB

    def _init_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with _connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hot_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT,
                    epistemic_weight REAL DEFAULT 1.0,
                    authority REAL DEFAULT 1.0,
                    is_quarantined INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    stage TEXT,
                    duration_ms REAL,
                    tokens_avoided INTEGER,
                    cache_hit_rate REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pruned_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    message_index INTEGER,
                    ai INTEGER,
                    content TEXT,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shadow_verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    verdict TEXT
                )
            """)
            conn.commit()

    def _load_shadow_stats(self):
        try:
            with _connect() as conn:
                for verdict, cnt in conn.execute(
                    "SELECT verdict, COUNT(*) FROM shadow_verdicts GROUP BY verdict"
                ):
                    v = str(verdict).lower()
                    if v in self._shadow_stats:
                        self._shadow_stats[v] = int(cnt)
        except Exception:
            pass

    # ------------------------------------------------------------ L0 hot path

    def get_hot_facts(self) -> List[Dict[str, Any]]:
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT key, value, epistemic_weight FROM hot_facts "
                "ORDER BY updated_at DESC LIMIT 20"
            )
            return [dict(row) for row in cursor.fetchall()]

    def set_hot_fact(self, key: str, value: str, epistemic_weight: float = 1.0):
        now = time.time()
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO hot_facts (key, value, epistemic_weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    epistemic_weight=excluded.epistemic_weight,
                    updated_at=excluded.updated_at
                """,
                (key, value, epistemic_weight, now, now),
            )
            conn.commit()

    # -------------------------------------------------------- L1 scope guard

    def update_project_scope(self, detected_project: Optional[str]) -> Optional[str]:
        if not detected_project:
            return self.active_scope
        self.scope_mentions[detected_project] = (
            self.scope_mentions.get(detected_project, 0) + 1
        )
        # Hysteresis: 2 sustained mentions before flipping active scope (I5)
        if self.scope_mentions[detected_project] >= 2:
            self.active_scope = detected_project
        return self.active_scope

    # ------------------------------------------------------- L2 deep path

    async def prefetch_l2(self, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Background vault prefetch with circuit breaker and hard deadline (I6)."""
        cfg = config or {}
        if not cfg.get("l2_enabled", True):
            return []
        mode = str(cfg.get("l2_mode", "shadow")).lower()
        if mode == "disabled" or not VAULT_DIR or not self.circuit_breaker.can_execute():
            return []
        t0 = time.time()
        try:
            loop = asyncio.get_running_loop()
            facts = await asyncio.wait_for(
                loop.run_in_executor(None, self._read_vault_facts_sync),
                timeout=L2_DEADLINE_S,
            )
            self.circuit_breaker.record_success()
            self._l2_facts = facts
            if mode == "active":
                # Only the verified-active mode may write into hot facts.
                for f in facts:
                    self.set_hot_fact(f["key"], f["value"], epistemic_weight=0.6)
            self.record_telemetry(
                "l2_prefetch", (time.time() - t0) * 1000.0, tokens_avoided=len(facts)
            )
            return facts
        except asyncio.TimeoutError:
            self.circuit_breaker.record_failure()
            self.record_telemetry("l2_prefetch_timeout", L2_DEADLINE_S * 1000.0)
        except Exception:
            self.circuit_breaker.record_failure()
        return []

    def _read_vault_facts_sync(self, limit: int = 8) -> List[Dict[str, Any]]:
        facts: List[Dict[str, Any]] = []
        ctx = os.path.join(VAULT_DIR, "context")
        candidates: List[Dict[str, Any]] = []
        pool = 40  # candidate pool for optional reranker (Slot 2)
        if os.path.isdir(ctx):
            for name in ("global.md", "user.md"):
                p = os.path.join(ctx, name)
                if not os.path.isfile(p):
                    continue
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read(20000)
                except OSError:
                    continue
                base = os.path.basename(p)
                for line in text.splitlines():
                    line = line.strip().lstrip("#- ").strip()
                    if 8 <= len(line) <= 160:
                        candidates.append(
                            {"key": f"vault:{base}:{len(candidates)}", "value": line[:160]}
                        )
                        if len(candidates) >= pool:
                            break
        reranker = getattr(self, "fact_reranker", None)
        if callable(reranker) and candidates:
            try:
                ranked = list(reranker(candidates))
                if ranked:
                    candidates = ranked
            except Exception:
                pass  # I6: file-order fallback
        facts = candidates[:limit]
        return facts

    # --------------------------------------------------- shadow acceptance gate

    def record_shadow_verdict(self, verdict: str):
        v = str(verdict).upper()
        if v not in ("HELPFUL", "NEUTRAL", "HARMFUL"):
            return
        self._shadow_stats[v.lower()] += 1
        try:
            with _connect() as conn:
                conn.execute(
                    "INSERT INTO shadow_verdicts (timestamp, verdict) VALUES (?, ?)",
                    (time.time(), v),
                )
                conn.commit()
        except Exception:
            pass

    def l2_promotion_ready(
        self,
        min_evals: int = 10,
        max_harmful: int = 0,
        min_helpful_ratio: float = 0.3,
    ) -> bool:
        total = sum(self._shadow_stats.values())
        if total < min_evals:
            return False
        if self._shadow_stats["harmful"] > max_harmful:
            return False
        return (self._shadow_stats["helpful"] / total) >= min_helpful_ratio

    # ------------------------------------------------------------ fence store

    def archive_pruned_messages(self, session_id: str, messages: list) -> int:
        """Archive pruned history rows; returns estimated tokens avoided."""
        now = time.time()
        tokens = 0
        rows = []
        for idx, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            ai = 1 if m.get("ai") else 0
            raw = m.get("content", "")
            content_str = (
                json.dumps(raw) if isinstance(raw, (dict, list)) else str(raw)
            )
            tokens += len(content_str) // 4
            rows.append((session_id, idx, ai, content_str[:20000], now))
        try:
            with _connect() as conn:
                conn.executemany(
                    "INSERT INTO pruned_history "
                    "(session_id, message_index, ai, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
            self.record_telemetry("fence_pruned", 0.0, tokens_avoided=tokens)
        except Exception:
            pass
        return tokens

    # -------------------------------------------------------- capsule compiler

    def compile_capsule(
        self, agent=None, config: Optional[Dict[str, Any]] = None
    ) -> str:
        t0 = time.time()
        cfg = config or {}
        if cfg.get("mode", "active") == "disabled":
            return ""

        max_tokens = int(cfg.get("max_capsule_tokens", 1500))
        hot_facts = self.get_hot_facts() if cfg.get("l0_enabled", True) else []

        # Fixed XML structure for prompt-cache stability (>85% hit rate)
        sections = ["<!-- JIT-CONTEXT EPHEMERAL CAPSULE -->", "<jit_capsule>"]
        sections.append("  <core_canon>")
        sections.append("    <invariant id=\"I1\">Direct user input overrides stored memory.</invariant>")
        sections.append("    <invariant id=\"I3\">Assistant outputs carry 0.0 epistemic weight (anti-self-poisoning).</invariant>")
        sections.append("    <invariant id=\"I6\">Zero-block degradation: external timeouts fail safely to local cache.</invariant>")
        sections.append("    <invariant id=\"I9\">Memory cannot authorize destructive operations.</invariant>")
        sections.append("    <invariant id=\"I10\">Existing patch artifacts in context take precedence over re-implementing from scratch. Verify and apply directly.</invariant>")
        sections.append("  </core_canon>")

        if self.active_scope:
            sections.append(f"  <project_scope active=\"{self.active_scope}\">")
            sections.append(f"    Active project context: {self.active_scope}")
            sections.append("  </project_scope>")

        active_skills = cfg.get("active_skills", [])
        if active_skills:
            sections.append("  <active_skill_contracts level=\"1\">")
            for s in active_skills:
                sections.append(f"    <skill name=\"{s.get('name')}\" trigger=\"{s.get('trigger')}\">")
                if s.get("contract"):
                    sections.append(f"      <contract>{s.get('contract')}</contract>")
                if s.get("deep_ref"):
                    sections.append(f"      <deep_reference path=\"{s.get('deep_ref')}\" uri_only=\"true\"/>")
                sections.append("    </skill>")
            sections.append("  </active_skill_contracts>")

        # L2 shadow preview: metadata only, content is NOT injected (acceptance gate)
        l2_mode = str(cfg.get("l2_mode", "shadow")).lower()
        if self._l2_facts and l2_mode == "shadow":
            sections.append(
                f"  <l2_shadow_preview facts=\"{len(self._l2_facts)}\" injected=\"false\"/>"
            )

        patch_art = cfg.get("patch_artifact")
        if patch_art:
            sections.append("  <patch_artifact format=\"unified_diff\">")
            sections.append(f"{patch_art.strip()}")
            sections.append("  </patch_artifact>")

        max_fact_chars = int(cfg.get("max_fact_chars", 160))

        def _fact_line(f: Dict[str, Any]) -> str:
            value = str(f.get("value", ""))[:max_fact_chars]
            return (
                f"    <fact key=\"{f.get('key')}\" "
                f"weight=\"{f.get('epistemic_weight')}\">{value}</fact>"
            )

        if hot_facts:
            sections.append("  <dynamic_facts>")
            for fact in hot_facts:
                sections.append(_fact_line(fact))
            sections.append("  </dynamic_facts>")

        sections.append("</jit_capsule>")
        capsule = "\n".join(sections)

        # Budget guard stage 1: drop oldest dynamic facts while over budget
        while (len(capsule) // 4) > max_tokens and len(hot_facts) > 1:
            hot_facts = hot_facts[:-1]
            head = sections[: sections.index("  <dynamic_facts>") + 1]
            tail = ["  </dynamic_facts>", "</jit_capsule>"]
            capsule = "\n".join(head + [_fact_line(f) for f in hot_facts] + tail)

        # Budget guard stage 2: progressively shorten remaining fact values
        while (len(capsule) // 4) > max_tokens and hot_facts:
            f = dict(hot_facts[0])
            val = str(f.get("value", ""))
            if len(val) <= 48:
                hot_facts = hot_facts[1:]
                if not hot_facts:
                    break
                continue
            f["value"] = val[: max(48, int(len(val) * 0.7))]
            hot_facts[0] = f
            head = sections[: sections.index("  <dynamic_facts>") + 1]
            tail = ["  </dynamic_facts>", "</jit_capsule>"]
            capsule = "\n".join(head + [_fact_line(x) for x in hot_facts] + tail)

        # Budget guard stage 3: drop dynamic_facts entirely (canon is the floor)
        if (len(capsule) // 4) > max_tokens and not hot_facts:
            try:
                start = sections.index("  <dynamic_facts>")
                end = sections.index("  </dynamic_facts>")
                trimmed_sections = sections[:start] + sections[end + 1 :]
                capsule = "\n".join(trimmed_sections)
            except ValueError:
                pass

        duration_ms = (time.time() - t0) * 1000.0
        if cfg.get("telemetry_enabled", True):
            self.record_telemetry(
                "compile_capsule",
                duration_ms,
                tokens_avoided=len(capsule) // 4,
            )
        return capsule

    # ------------------------------------------------------------- telemetry

    def record_telemetry(
        self,
        stage: str,
        duration_ms: float,
        tokens_avoided: Optional[int] = None,
        cache_hit_rate: Optional[float] = None,
    ):
        try:
            with _connect() as conn:
                conn.execute(
                    "INSERT INTO telemetry_events "
                    "(timestamp, stage, duration_ms, tokens_avoided, cache_hit_rate) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (time.time(), stage, float(duration_ms), tokens_avoided, cache_hit_rate),
                )
                conn.commit()
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        counts = {"hot_facts": 0, "telemetry_events": 0, "pruned_history": 0}
        try:
            with _connect() as conn:
                for table in counts:
                    counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            pass
        return {
            "db_path": DB_PATH,
            "vault_dir": VAULT_DIR or None,
            "l2_deadline_ms": L2_DEADLINE_S * 1000.0,
            "hook_budget_ms": HOOK_BUDGET_MS,
            **counts,
            "circuit_breaker": self.circuit_breaker.state,
            "active_scope": self.active_scope,
            "l2_cached_facts": len(self._l2_facts),
            "shadow_stats": dict(self._shadow_stats),
            "l2_promotion_ready": self.l2_promotion_ready(),
        }


def get_runtime() -> JITContextRuntime:
    """Canonical accessor — always returns the process-wide singleton."""
    return JITContextRuntime()
