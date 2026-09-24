"""Slot 4: advisory eviction. Writes suggestions to jev_bridge's OWN db.
Never mutates jit_context hot_facts. Read-only query for candidates.
"""
from __future__ import annotations

import os
import sqlite3
import time


def _ensure(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=2.0) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jev_advice ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, "
            "fact_key TEXT, reason TEXT, applied INTEGER DEFAULT 0)"
        )


def _hot_rows(runtime, n: int):
    """Override seam for tests; production reads jit DB read-only."""
    try:
        from jev_bridge._runtime import jit_db_path
        path = jit_db_path()
        if not path:
            return []
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
        rows = conn.execute(
            "SELECT key, updated_at FROM hot_facts "
            "WHERE is_quarantined = 0 ORDER BY updated_at ASC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def write_eviction_advice(runtime, db_path: str, max_capsule_tokens: int, budget_pct: float = 0.9) -> int:
    try:
        capsule = runtime.compile_capsule()
        used = len(capsule) // 4
        if used <= int(max_capsule_tokens * budget_pct):
            return 0
        rows = _hot_rows(runtime, 5)
        if not rows:
            return 0
        _ensure(db_path)
        now = time.time()
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            conn.executemany(
                "INSERT INTO jev_advice (ts, kind, fact_key, reason) VALUES (?,?,?,?)",
                [(now, "evict_suggest", k, f"capsule {used}/{max_capsule_tokens} tok; oldest updated_at") for k, _ in rows],
            )
        return len(rows)
    except Exception:
        return 0  # I6
