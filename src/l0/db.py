"""L0 SQLite WAL Database layer for Hermes JIT Context OS."""

import sqlite3
import time
from typing import Optional
from pathlib import Path
from config import DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    active_scope TEXT NOT NULL,
    scope_epoch INTEGER NOT NULL DEFAULT 1,
    scope_confidence REAL NOT NULL DEFAULT 1.0,
    last_seq INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    turn_id TEXT,
    origin TEXT NOT NULL, -- 'direct_user', 'assistant', 'tool', 'external', 'derived', 'system'
    role TEXT NOT NULL,   -- 'user', 'assistant', 'system', 'tool'
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    root_event_id TEXT,
    authority REAL NOT NULL DEFAULT 0.0, -- 1.0 for direct_user, 0.0 for assistant
    effective_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_content_hash ON events(session_id, content_hash);

CREATE TABLE IF NOT EXISTS overlay (
    entry_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL, -- 'statement', 'fact', 'directive', 'override'
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    authority REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active', -- 'active', 'superseded', 'replicated'
    supersedes TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
    FOREIGN KEY(source_event_id) REFERENCES events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_overlay_session_status ON overlay(session_id, status);

CREATE TABLE IF NOT EXISTS outbox (
    event_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    destination TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    state TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'in_flight', 'delivered', 'failed'
    created_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS provider_state (
    provider TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'closed', -- 'closed', 'open', 'half_open'
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    opened_at TEXT,
    last_attempt TEXT,
    last_success TEXT,
    latency_ema REAL NOT NULL DEFAULT 0.0
);
"""

def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target_path = db_path or DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=0.05)
    conn.row_factory = sqlite3.Row
    
    # Critical PRAGMAs for <3ms latency and WAL durability
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA busy_timeout=50;")
    
    return conn

def init_db(db_path: Optional[Path] = None) -> None:
    conn = get_db(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
            try:
                from telemetry.db_schema import init_telemetry_schema
                init_telemetry_schema(conn)
            except Exception as e:
                print(f"[ona-context:db] Telemetry schema init: {e}")
    finally:
        conn.close()
