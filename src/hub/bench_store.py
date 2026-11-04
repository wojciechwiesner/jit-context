"""ab_runs table in the hub usage store: one row per `claude -p` call of a controlled A/B batch.

Values the CLI did not report stay NULL (never 0). summarize() gives per-arm medians with n and the median of
paired differences (JIT on minus off) over (task, run) pairs where both calls succeeded.
"""

from __future__ import annotations

import sqlite3
from statistics import median
from typing import Dict, List, Optional

from hub import usage_store

ARM_ON = "on"
ARM_OFF = "off"
ARMS = (ARM_ON, ARM_OFF)
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
METRICS = ("total_tokens", "num_turns", "wall_s", "cost_usd")
ROW_FIELDS = (
    "batch_id", "project", "repo_path", "head", "task_id", "prompt", "run_index", "arm", "model",
    "started_at", "wall_s", "exit_code", "is_error", "error", "num_turns", *TOKEN_FIELDS,
    "cost_usd", "duration_api_ms", "session_id", "answer",
)

AB_SCHEMA = """
CREATE TABLE IF NOT EXISTS ab_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL, project TEXT NOT NULL, repo_path TEXT NOT NULL, head TEXT,
    task_id TEXT NOT NULL, prompt TEXT NOT NULL, run_index INTEGER NOT NULL, arm TEXT NOT NULL,
    model TEXT NOT NULL, started_at TEXT NOT NULL, wall_s REAL NOT NULL,
    exit_code INTEGER, is_error INTEGER NOT NULL, error TEXT, num_turns INTEGER,
    input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
    cost_usd REAL, duration_api_ms INTEGER, session_id TEXT, answer TEXT
);
CREATE INDEX IF NOT EXISTS idx_ab_runs_project ON ab_runs(project, batch_id);
"""


def connect(path=None) -> sqlite3.Connection:
    """Usage store connection with the ab_runs table ensured."""
    conn = usage_store.connect(path)
    conn.executescript(AB_SCHEMA)
    return conn


def insert_run(conn: sqlite3.Connection, row: Dict[str, object]) -> None:
    conn.execute(
        f"INSERT INTO ab_runs ({', '.join(ROW_FIELDS)}) VALUES ({', '.join('?' for _ in ROW_FIELDS)})",
        [row.get(name) for name in ROW_FIELDS],
    )
    conn.commit()


def read_batch(conn: sqlite3.Connection, batch_id: str) -> List[dict]:
    rows = conn.execute("SELECT * FROM ab_runs WHERE batch_id=? ORDER BY id", (batch_id,)).fetchall()
    return [dict(row) for row in rows]


def total_tokens(row: dict) -> Optional[int]:
    """Sum of the four token fields; None when any of them is missing."""
    values = [row.get(name) for name in TOKEN_FIELDS]
    if any(value is None for value in values):
        return None
    return int(sum(values))


def _metric(row: dict, name: str) -> Optional[float]:
    return total_tokens(row) if name == "total_tokens" else row.get(name)


def _median_with_n(values: List[Optional[float]]) -> Dict[str, object]:
    known = [value for value in values if value is not None]
    return {"median": median(known) if known else None, "n": len(known)}


def summarize(rows: List[dict]) -> Dict[str, object]:
    """Per-arm medians (failed calls excluded and counted) and paired on-minus-off medians."""
    ok = [row for row in rows if not row["is_error"]]
    arms = {}
    for arm in ARMS:
        arm_rows = [row for row in ok if row["arm"] == arm]
        arms[arm] = {name: _median_with_n([_metric(row, name) for row in arm_rows]) for name in METRICS}
        arms[arm]["errors"] = sum(1 for row in rows if row["arm"] == arm and row["is_error"])
    by_pair: Dict[tuple, Dict[str, dict]] = {}
    for row in ok:
        by_pair.setdefault((row["task_id"], row["run_index"]), {})[row["arm"]] = row
    paired = {}
    for name in METRICS:
        diffs = []
        for pair in by_pair.values():
            on, off = (_metric(pair[arm], name) if arm in pair else None for arm in ARMS)
            diffs.append(on - off if on is not None and off is not None else None)
        paired[name] = _median_with_n(diffs)
    return {"arms": arms, "paired_on_minus_off": paired, "calls": len(rows)}
