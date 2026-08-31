"""Telemetry database schema for Context OS Observatory."""

import sqlite3

TELEMETRY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS turn_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'shadow',
    
    user_query_chars INTEGER NOT NULL DEFAULT 0,
    user_query_tokens_est INTEGER DEFAULT 0,
    user_query_hash TEXT,
    
    active_scope TEXT,
    retrieval_scopes_json TEXT,
    scope_epoch INTEGER DEFAULT 1,
    scope_changed INTEGER NOT NULL DEFAULT 0,
    
    l2_triggered INTEGER NOT NULL DEFAULT 0,
    l2_triggers_json TEXT,
    
    l0_ms REAL DEFAULT 0.0,
    l1_ms REAL DEFAULT 0.0,
    l2_ms REAL DEFAULT 0.0,
    compile_ms REAL DEFAULT 0.0,
    hook_total_ms REAL DEFAULT 0.0,
    
    capsule_hash TEXT,
    capsule_chars INTEGER DEFAULT 0,
    capsule_tokens_est INTEGER DEFAULT 0,
    
    haystack_chars_est INTEGER DEFAULT 0,
    haystack_tokens_est INTEGER DEFAULT 0,
    jit_tokens_avoided_est INTEGER DEFAULT 0,
    compression_ratio REAL DEFAULT 0.0,
    
    api_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    
    actual_cost_usd REAL DEFAULT 0.0,
    no_cache_cost_est_usd REAL DEFAULT 0.0,
    no_jit_cost_est_usd REAL DEFAULT 0.0,
    savings_est_usd REAL DEFAULT 0.0,
    
    l1_cache_hit INTEGER DEFAULT 0,
    capsule_cache_hit INTEGER DEFAULT 0,
    prompt_cache_hit_ratio REAL DEFAULT 0.0,
    
    overlay_items INTEGER DEFAULT 0,
    recent_fence_items INTEGER DEFAULT 0,
    invariants_failed_json TEXT DEFAULT '[]',
    degraded INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    
    UNIQUE(session_id, turn_id)
);

CREATE INDEX IF NOT EXISTS idx_turn_telemetry_created ON turn_telemetry(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_turn_telemetry_session ON turn_telemetry(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_request_id TEXT NOT NULL,
    session_id TEXT,
    turn_id TEXT,
    retry_count INTEGER DEFAULT 0,
    
    started_at TEXT NOT NULL,
    ended_at TEXT,
    
    provider TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    response_model TEXT,
    
    message_count INTEGER DEFAULT 0,
    tool_count INTEGER DEFAULT 0,
    request_chars INTEGER DEFAULT 0,
    approx_input_tokens INTEGER DEFAULT 0,
    
    status TEXT NOT NULL DEFAULT 'started',
    duration_ms REAL DEFAULT 0.0,
    finish_reason TEXT,
    
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    
    cost_usd REAL DEFAULT 0.0,
    response_chars INTEGER DEFAULT 0,
    tool_calls INTEGER DEFAULT 0,
    
    http_status INTEGER,
    retryable INTEGER DEFAULT 0,
    error_reason TEXT,
    
    UNIQUE(api_request_id, retry_count)
);

CREATE INDEX IF NOT EXISTS idx_llm_turn ON llm_metrics(session_id, turn_id);
CREATE INDEX IF NOT EXISTS idx_llm_started ON llm_metrics(started_at DESC);

CREATE TABLE IF NOT EXISTS context_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    
    layer TEXT NOT NULL,
    target TEXT NOT NULL,
    trigger TEXT,
    
    active_scope TEXT,
    retrieval_scope TEXT,
    query_text TEXT,
    
    cache_hit INTEGER DEFAULT 0,
    duration_ms REAL DEFAULT 0.0,
    status TEXT DEFAULT 'hit',
    results_count INTEGER DEFAULT 0,
    returned_chars INTEGER DEFAULT 0,
    returned_tokens_est INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_context_queries_turn ON context_queries(session_id, turn_id);

CREATE TABLE IF NOT EXISTS telemetry_feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    session_id TEXT,
    turn_id TEXT,
    ref_id TEXT,
    payload_json TEXT
);
"""

def init_telemetry_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TELEMETRY_SCHEMA_SQL)
    conn.commit()
