"""SQLite usage sources: Hermes sessions (~/.hermes/state.db) and JIT overlay DBs (turn_telemetry).

Both are opened read-only (`mode=ro`, falling back to `PRAGMA query_only`). Hermes keeps running totals per
session, so each changed session replaces its row (attributed to the local day it started). Overlay DBs are
append-only per session: rows after the remembered turn_telemetry id are added; a recreated DB is re-read.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from hub import usage_store as store
from hub.usage_claude import local_day

HERMES_SOURCE = "hermes"
JIT_SOURCE = "jit"
HERMES_STATE_KEY = "state.db"
OVERLAY_GLOB = "*/*/overlay_*.db"
WAL_SUFFIXES = ("", "-wal")
HERMES_COLUMNS = (
    "id", "cwd", "started_at", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "api_call_count", "estimated_cost_usd",
)
JIT_QUERY = (
    "SELECT id, session_id, created_at, active_scope, capsule_tokens_est, hook_total_ms "
    "FROM turn_telemetry WHERE id > ? ORDER BY id"
)


def open_readonly(path: Path) -> sqlite3.Connection:
    """Read-only connection: URI mode=ro first, else a normal connection with query_only."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except sqlite3.Error:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _files_signature(path: Path) -> Tuple[int, float]:
    """Combined size and newest mtime of the DB and its WAL (a WAL write leaves the main file untouched)."""
    size, mtime = 0, 0.0
    for suffix in WAL_SUFFIXES:
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            stat = candidate.stat()
            size += stat.st_size
            mtime = max(mtime, stat.st_mtime)
    return size, mtime


def _hermes_row(row: sqlite3.Row) -> Optional[dict]:
    """session_days row of one Hermes session; missing columns read as NULL (cost stays unknown)."""
    try:
        started = datetime.fromtimestamp(float(row["started_at"]))
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return {
        "day": started.date().isoformat(), "session_id": row["id"], "path": row["cwd"], "scope": None,
        "input_tokens": row["input_tokens"] or 0, "output_tokens": row["output_tokens"] or 0,
        "cache_read_tokens": row["cache_read_tokens"] or 0, "cache_write_tokens": row["cache_write_tokens"] or 0,
        "turns": 0, "api_calls": row["api_call_count"] or 0, "capsules": 0, "capsule_tokens": 0, "hook_ms": 0,
        "cost_usd": row["estimated_cost_usd"],
    }


def _hermes_select(has: set) -> str:
    """SELECT over HERMES_COLUMNS; a column the installed schema lacks is selected as NULL."""
    present = [name if name in has else f"NULL AS {name}" for name in HERMES_COLUMNS]
    return f"SELECT {', '.join(present)} FROM sessions"


def collect_hermes(conn: sqlite3.Connection, db_path: Path) -> int:
    """Upsert changed Hermes sessions. Returns the number of sessions whose rows changed."""
    if not db_path.exists():
        return 0
    size, mtime = _files_signature(db_path)
    state = store.get_reader_state(conn, HERMES_SOURCE, HERMES_STATE_KEY)
    if store.unchanged(state, size, mtime, 0):
        return 0
    source = open_readonly(db_path)
    try:
        has = _columns(source, "sessions")
        rows = source.execute(_hermes_select(has)).fetchall()
    finally:
        source.close()
    changed = 0
    with conn:
        for row in rows:
            parsed = _hermes_row(row)
            if parsed is not None and store.replace_unit(conn, HERMES_SOURCE, str(row["id"]), [parsed]):
                changed += 1
        store.set_reader_state(conn, HERMES_SOURCE, HERMES_STATE_KEY, 0, size, mtime, 0)
    return changed


def _ingest_overlay(conn: sqlite3.Connection, root: Path, path: Path) -> int:
    unit = str(path.relative_to(root))
    size, mtime = _files_signature(path)
    inode = path.stat().st_ino
    state = store.get_reader_state(conn, JIT_SOURCE, unit)
    if store.unchanged(state, size, mtime, inode):
        return 0
    last_id = state["position"] if state is not None else 0
    source = open_readonly(path)
    try:
        if "capsule_tokens_est" not in _columns(source, "turn_telemetry"):
            rows = []
        else:
            max_id = source.execute("SELECT COALESCE(MAX(id), 0) FROM turn_telemetry").fetchone()[0]
            if state is not None and (state["inode"] != inode or max_id < last_id):
                store.drop_unit(conn, JIT_SOURCE, unit)
                last_id = 0
            rows = source.execute(JIT_QUERY, (last_id,)).fetchall()
    finally:
        source.close()
    scope_dir = Path(unit).parts[0]
    for row in rows:
        day = local_day(row["created_at"])
        if day is not None:
            capsule_tokens = int(row["capsule_tokens_est"] or 0)
            identity = {"session_id": row["session_id"], "path": None, "scope": row["active_scope"] or scope_dir}
            delta = {"turns": 1, "capsules": 1 if capsule_tokens > 0 else 0, "capsule_tokens": capsule_tokens,
                     "hook_ms": float(row["hook_total_ms"] or 0.0)}
            store.add_to_day(conn, JIT_SOURCE, unit, day, identity, delta)
        last_id = max(last_id, int(row["id"]))
    store.set_reader_state(conn, JIT_SOURCE, unit, last_id, size, mtime, inode)
    return len(rows)


def collect_jit(conn: sqlite3.Connection, sessions_root: Path) -> Tuple[int, List[str]]:
    """Ingest new turn_telemetry rows from every overlay DB. Returns (rows, per-file errors)."""
    if not sessions_root.is_dir():
        return 0, []
    added, errors = 0, []
    for path in sorted(sessions_root.glob(OVERLAY_GLOB)):
        try:
            with conn:
                added += _ingest_overlay(conn, sessions_root, path)
        except (OSError, sqlite3.Error) as exc:
            errors.append(f"{path}: {exc}")
    return added, errors
