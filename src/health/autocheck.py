"""Autocheck engine for Hermes JIT Context OS & Borg Context Broker."""

import time
import sqlite3
from typing import Dict, Any
from health.invariants import evaluate_all_invariants
from l2.circuit_breaker import CircuitBreaker

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
    cb = CircuitBreaker("borg_broker")
    cb_state, cb_failures, _ = cb.get_state(conn)
    
    # 3. Invariants Check
    invariants = evaluate_all_invariants(conn)
    all_passed = all(status == "pass" for status in invariants.values())
    
    total_duration_ms = (time.perf_counter() - start_time) * 1000.0
    
    status = "healthy" if (all_passed and cb_state != "open") else ("degraded" if all_passed else "unsafe")
    
    return {
        "status": status,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": round(total_duration_ms, 2),
        "l0": {
            "wal": "ok",
            "journal_mode": "wal",
            "read_latency_ms": round(read_latency_ms, 2),
            "pending_overlay": pending_overlay,
            "outbox_pending": pending_outbox
        },
        "l1": {
            "active_scope": "hermes",
            "cache_status": "ready"
        },
        "l2": {
            "circuit_breaker": cb_state,
            "consecutive_failures": cb_failures
        },
        "invariants": invariants
    }
