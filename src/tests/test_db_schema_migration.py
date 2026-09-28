"""An overlay DB created by an older release must receive new tables/columns on open.

Regression: get_db() only ran the schema when the file did not exist, so long-lived
session DBs never got tool_routing / llm_metrics.tool_names_json and every turn logged
"no such table: tool_routing" and "no such column: tool_names_json".
"""
import sqlite3

from l0.db import SCHEMA_VERSION, get_db


LEGACY_LLM_METRICS_COLS = (
    "api_request_id TEXT, session_id TEXT, turn_id TEXT, retry_count INTEGER, "
    "started_at TEXT, ended_at TEXT, provider TEXT, requested_model TEXT, "
    "response_model TEXT, message_count INTEGER, tool_count INTEGER, request_chars INTEGER, "
    "approx_input_tokens INTEGER, status TEXT, duration_ms REAL, finish_reason TEXT, "
    "input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, "
    "cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL, "
    "response_chars INTEGER, tool_calls INTEGER, http_status INTEGER, retryable INTEGER, "
    "error_reason TEXT"
)


def _make_legacy_db(path):
    # Mirrors a real pre-migration overlay DB: llm_metrics without tool_names_json,
    # no tool_routing table, user_version 0.
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE llm_metrics (id INTEGER PRIMARY KEY, {LEGACY_LLM_METRICS_COLS})")
    conn.commit()
    conn.close()


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_legacy_db_is_migrated_on_open(tmp_path):
    db = tmp_path / "overlay_legacy.db"
    _make_legacy_db(db)

    conn = get_db(db_path=db)
    try:
        assert "tool_routing" in _tables(conn)
        assert "tool_names_json" in _columns(conn, "llm_metrics")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_reopen_is_idempotent_and_keeps_data(tmp_path):
    db = tmp_path / "overlay_reopen.db"
    conn = get_db(db_path=db)
    conn.execute(
        "INSERT INTO tool_routing (session_id, turn_id, created_at) VALUES ('s', 't', 'now')"
    )
    conn.commit()
    conn.close()

    conn = get_db(db_path=db)
    try:
        assert conn.execute("SELECT count(*) FROM tool_routing").fetchone()[0] == 1
    finally:
        conn.close()
