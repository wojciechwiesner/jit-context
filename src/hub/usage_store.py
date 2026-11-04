"""Usage store: <hub dir>/usage.sqlite with per-unit rows, reader cursors and daily rollups.

session_days holds one row per (source, unit, day). A unit is the thing a reader can re-read on its own:
a transcript file (claude), a Hermes session id (hermes) or an overlay DB file (jit). daily_usage is derived
from session_days and rebuilt only when rows changed or the registry changed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import config

USAGE_DB_NAME = "usage.sqlite"
SQLITE_TIMEOUT_SECONDS = 30
SUM_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "turns", "api_calls", "capsules", "capsule_tokens", "hook_ms",
)
COST_FIELD = "cost_usd"
META_REGISTRY_KEY = "registry_signature"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reader_state (
    source TEXT NOT NULL, key TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0, size INTEGER, mtime REAL, inode INTEGER, cursor TEXT,
    PRIMARY KEY (source, key)
);
CREATE TABLE IF NOT EXISTS seen_messages (msg_key TEXT PRIMARY KEY, unit TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_seen_unit ON seen_messages(unit);
CREATE TABLE IF NOT EXISTS session_days (
    source TEXT NOT NULL, unit TEXT NOT NULL, day TEXT NOT NULL,
    session_id TEXT, path TEXT, scope TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0, api_calls INTEGER NOT NULL DEFAULT 0,
    capsules INTEGER NOT NULL DEFAULT 0, capsule_tokens INTEGER NOT NULL DEFAULT 0,
    hook_ms REAL NOT NULL DEFAULT 0, cost_usd REAL,
    PRIMARY KEY (source, unit, day)
);
CREATE TABLE IF NOT EXISTS daily_usage (
    day TEXT NOT NULL, source TEXT NOT NULL, project TEXT, registered INTEGER NOT NULL,
    sessions INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
    turns INTEGER NOT NULL, api_calls INTEGER NOT NULL,
    capsules INTEGER NOT NULL, capsule_tokens INTEGER NOT NULL, hook_ms REAL NOT NULL,
    cost_usd REAL, cost_sessions INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_project ON daily_usage(project, day);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def usage_db_path() -> Path:
    return config.hub_dir() / USAGE_DB_NAME


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (and create) the usage store."""
    target = Path(path) if path else usage_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def get_reader_state(conn: sqlite3.Connection, source: str, key: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM reader_state WHERE source=? AND key=?", (source, key)).fetchone()


def set_reader_state(conn: sqlite3.Connection, source: str, key: str, position: int = 0,
                     size: Optional[int] = None, mtime: Optional[float] = None,
                     inode: Optional[int] = None, cursor: Optional[str] = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO reader_state (source, key, position, size, mtime, inode, cursor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (source, key, position, size, mtime, inode, cursor),
    )


def unchanged(state: Optional[sqlite3.Row], size: int, mtime: float, inode: int) -> bool:
    return state is not None and state["size"] == size and state["mtime"] == mtime and state["inode"] == inode


def drop_unit(conn: sqlite3.Connection, source: str, unit: str) -> None:
    """Forget everything one unit contributed (used when its file was replaced or truncated)."""
    conn.execute("DELETE FROM session_days WHERE source=? AND unit=?", (source, unit))
    conn.execute("DELETE FROM seen_messages WHERE unit=?", (unit,))


def add_to_day(conn: sqlite3.Connection, source: str, unit: str, day: str, identity: Dict[str, Optional[str]],
               delta: Dict[str, float]) -> None:
    """Add counters to one (source, unit, day) row; identity = session_id/path/scope (first value wins)."""
    columns = ", ".join(SUM_FIELDS)
    updates = ", ".join(f"{name} = {name} + excluded.{name}" for name in SUM_FIELDS)
    conn.execute(
        f"INSERT INTO session_days (source, unit, day, session_id, path, scope, {columns}) "
        f"VALUES (?, ?, ?, ?, ?, ?, {', '.join('?' for _ in SUM_FIELDS)}) "
        f"ON CONFLICT(source, unit, day) DO UPDATE SET {updates}, "
        "session_id = COALESCE(session_days.session_id, excluded.session_id), "
        "path = COALESCE(session_days.path, excluded.path), scope = COALESCE(session_days.scope, excluded.scope)",
        (source, unit, day, identity.get("session_id"), identity.get("path"), identity.get("scope"),
         *[delta.get(name, 0) for name in SUM_FIELDS]),
    )


def replace_unit(conn: sqlite3.Connection, source: str, unit: str, rows: Sequence[dict]) -> bool:
    """Make a unit's rows equal to `rows` (full snapshot sources). True when anything changed."""
    fields = ("day", "session_id", "path", "scope", *SUM_FIELDS, COST_FIELD)
    current = conn.execute(
        f"SELECT {', '.join(fields)} FROM session_days WHERE source=? AND unit=? ORDER BY day", (source, unit)
    ).fetchall()
    wanted = sorted((tuple(row.get(name) for name in fields) for row in rows), key=lambda r: r[0])
    if [tuple(r) for r in current] == wanted:
        return False
    conn.execute("DELETE FROM session_days WHERE source=? AND unit=?", (source, unit))
    conn.executemany(
        f"INSERT INTO session_days (source, unit, {', '.join(fields)}) "
        f"VALUES (?, ?, {', '.join('?' for _ in fields)})",
        [(source, unit, *values) for values in wanted],
    )
    return True


def mark_seen(conn: sqlite3.Connection, msg_key: str, unit: str) -> bool:
    """True when the message key is new (and records it)."""
    cur = conn.execute("INSERT OR IGNORE INTO seen_messages (msg_key, unit) VALUES (?, ?)", (msg_key, unit))
    return cur.rowcount == 1


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def rebuild_daily(conn: sqlite3.Connection, resolve: Callable[[Optional[str], Optional[str]], tuple]) -> int:
    """Recompute daily_usage from session_days. `resolve(path, scope)` -> (project, registered)."""
    sums = ", ".join(f"SUM({name}) AS {name}" for name in SUM_FIELDS)
    groups = conn.execute(
        f"SELECT day, source, path, scope, {sums}, SUM({COST_FIELD}) AS cost_usd, "
        f"COUNT({COST_FIELD}) AS cost_rows, GROUP_CONCAT(DISTINCT session_id) AS sessions "
        "FROM session_days GROUP BY day, source, path, scope"
    ).fetchall()
    merged: Dict[tuple, dict] = {}
    for row in groups:
        project, registered = resolve(row["path"], row["scope"])
        bucket = merged.setdefault((row["day"], row["source"], project), _empty_bucket(registered))
        _merge(bucket, row)
    conn.execute("DELETE FROM daily_usage")
    conn.executemany(
        f"INSERT INTO daily_usage (day, source, project, registered, sessions, {', '.join(SUM_FIELDS)}, "
        f"cost_usd, cost_sessions) VALUES ({', '.join('?' for _ in range(len(SUM_FIELDS) + 7))})",
        [(day, source, project, b["registered"], len(b["session_ids"]), *[b[n] for n in SUM_FIELDS],
          b["cost_usd"], b["cost_sessions"]) for (day, source, project), b in merged.items()],
    )
    return len(merged)


def _empty_bucket(registered: bool) -> dict:
    bucket: dict = {name: 0 for name in SUM_FIELDS}
    bucket.update(registered=int(registered), session_ids=set(), cost_usd=None, cost_sessions=0)
    return bucket


def _merge(bucket: dict, row: sqlite3.Row) -> None:
    for name in SUM_FIELDS:
        bucket[name] += row[name] or 0
    if row["sessions"]:
        bucket["session_ids"].update(row["sessions"].split(","))
    if row["cost_rows"]:
        bucket["cost_usd"] = (bucket["cost_usd"] or 0.0) + row["cost_usd"]
        bucket["cost_sessions"] += row["cost_rows"]


def read_daily(conn: sqlite3.Connection, project: Optional[str] = None,
               since: Optional[str] = None) -> List[dict]:
    clauses, params = [], []  # type: List[str], List[str]
    if project is not None:
        clauses.append("project = ?")
        params.append(project)
    if since is not None:
        clauses.append("day >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows: Iterable[sqlite3.Row] = conn.execute(
        f"SELECT * FROM daily_usage {where} ORDER BY day, source, project", params
    )
    return [dict(row) for row in rows]
