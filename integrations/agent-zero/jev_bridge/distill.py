"""Slot 3: distill archived fence rows into compact hot facts.
Rules (I3): assistant prose is NEVER distilled; weight cap 0.5; dedupe by
token Jaccard > 0.8; max `cap` facts per call; read-only vs jit DB.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List

from jev_bridge.judge import tokens

ARCHIVE_TABLE = "pruned_history"  # verified: id, session_id, message_index, ai, content, created_at
WEIGHT_CAP = 0.5


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _compress(text: str, max_len: int = 160) -> str:
    t = " ".join((text or "").split())
    return t[: max_len - 1] + "…" if len(t) > max_len else t


def distill_new_rows(runtime, db_path: str, session_id: str, since_ts: float, cap: int = 3) -> int:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    written = 0
    try:
        rows = conn.execute(
            f"SELECT id, ai, content FROM {ARCHIVE_TABLE} "
            "WHERE session_id = ? AND created_at > ? ORDER BY id ASC",
            (session_id, since_ts),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    existing: List[Dict[str, str]] = []
    try:
        existing = runtime.get_hot_facts() or []
    except Exception:
        existing = []
    existing_tokens = [tokens(f.get("value", "")) for f in existing]

    for row_id, ai, content in rows:
        if written >= cap:
            break
        if ai:  # I3: skip assistant output
            continue
        value = _compress(str(content))
        vt = tokens(value)
        if not vt:
            continue
        if any(_jaccard(vt, et) > 0.8 for et in existing_tokens):
            continue
        key = f"distill:{session_id[:8]}:{row_id}"
        try:
            runtime.set_hot_fact(key, value, epistemic_weight=WEIGHT_CAP)
        except Exception:
            continue
        existing_tokens.append(vt)
        written += 1
    return written
