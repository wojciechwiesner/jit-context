"""Autocheck engine for Hermes JIT Context OS & Borg Context Broker."""

import time
import sqlite3
from typing import Dict, Any
from health.invariants import evaluate_all_invariants

from config import L2_ENABLED

def get_health_report(conn: sqlite3.Connection, deep: bool = False) -> Dict[str, Any]:
    start_time = time.perf_counter()
    
    # 1. L0 Metrics
    t0 = time.perf_counter()
    cursor = conn.execute("SELECT count(*) FROM overlay WHERE status = 'active'")
    pending_overlay = cursor.fetchone()[0]
    cursor = conn.execute("SELECT count(*) FROM outbox WHERE state = 'pending'")
    pending_outbox = cursor.fetchone()[0]
    read_latency_ms = (time.perf_counter() - t0) * 1000.0
    
    # 2. L2 Circuit Breaker Metrics
    provider = conn.execute(
        "SELECT state, consecutive_failures FROM provider_state WHERE provider = ?",
        ("borg_broker",),
    ).fetchone()
    cb_state, cb_failures = (provider[0], provider[1]) if provider else ("closed", 0)
    latest_session = conn.execute(
        "SELECT active_scope FROM sessions ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    
    # 3. Invariants Check
    invariants = evaluate_all_invariants(conn)
    all_passed = all(status == "pass" for status in invariants.values())
    
    total_duration_ms = (time.perf_counter() - start_time) * 1000.0
    
    l2_status = "disabled" if not L2_ENABLED else (
        "degraded" if cb_state in {"open", "half_open"} else "not_verified"
    )
    status = "unsafe" if not all_passed else (
        "degraded" if l2_status == "degraded" else "healthy"
    )
    
    return {
        "status": status,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": round(total_duration_ms, 2),
        "l0": {
            "wal": "ok" if journal_mode == "wal" else "not_wal",
            "journal_mode": journal_mode,
            "read_latency_ms": round(read_latency_ms, 2),
            "pending_overlay": pending_overlay,
            "outbox_pending": pending_outbox
        },
        "l1": {
            "active_scope": latest_session[0] if latest_session else None,
            "cache_status": "not_checked"
        },
        "l2": {
            "enabled": L2_ENABLED,
            "status": l2_status,
            "circuit_breaker": cb_state,
            "consecutive_failures": cb_failures
        },
        "invariants": invariants,
        "invariant_scope": "isolated_self_test",
        "end_to_end_verified": False,
    }
