#!/usr/bin/env python3
"""
hermes-ona-doctor: Automated end-to-end verification CLI for Hermes JIT Context OS.
"""

import sys
import os
import time
import json
import sqlite3
import urllib.request
from pathlib import Path

# Inspect the configured Hermes installation without shadowing the installed package.
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
PLUGIN_DIR = HERMES_HOME / "plugins" / "ona-context"

from l0.db import get_db, init_db, DB_PATH
from l0.overlay import append_event, ensure_session, get_active_overlays
from l1.scope import resolve_scope
from l2.circuit_breaker import CircuitBreaker
from context.compiler import compile_context
from health.invariants import evaluate_all_invariants

def run_doctor() -> bool:
    print("=" * 60)
    print(" 🩺 HERMES JIT CONTEXT OS & BORG BROKER — DOCTOR")
    print("=" * 60)
    
    results = {}
    
    # 1. Plugin structure & configuration
    try:
        plugin_yaml = PLUGIN_DIR / "plugin.yaml"
        if plugin_yaml.exists():
            results["Plugin Config"] = ("PASS", f"Found at {PLUGIN_DIR}")
        else:
            results["Plugin Config"] = ("FAIL", "Missing plugin.yaml")
    except Exception as e:
        results["Plugin Config"] = ("FAIL", str(e))
        
    # 2. SQLite WAL Journal Mode & Integrity
    try:
        init_db()
        conn = get_db()
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if jm.lower() == "wal" and ic.lower() == "ok":
            results["SQLite WAL"] = ("PASS", f"mode={jm}, integrity={ic}")
        else:
            results["SQLite WAL"] = ("WARN", f"mode={jm}, integrity={ic}")
        conn.close()
    except Exception as e:
        results["SQLite WAL"] = ("FAIL", str(e))
        
    # 3. L0 Read-Your-Own-Writes & Authority Check
    try:
        conn = get_db()
        test_sess = f"doc_test_{int(time.time())}"
        ensure_session(conn, test_sess)
        
        # User event
        append_event(conn, test_sess, "user", "TEST_PORT = 9988", "direct_user")
        # Assistant event
        append_event(conn, test_sess, "assistant", "Hypothesis: MongoDB used", "assistant_trace")
        
        # Verify L0 isolation and authority
        evs = conn.execute("SELECT origin, authority, content FROM events WHERE session_id = ? ORDER BY seq ASC", (test_sess,)).fetchall()
        user_auth = evs[0]["authority"]
        asst_auth = evs[1]["authority"]
        
        if user_auth == 1.0 and asst_auth == 0.0:
            results["L0 Hot-Path (RYOW)"] = ("PASS", "user auth=1.0, assistant auth=0.0 (anti-self-poisoning)")
        else:
            results["L0 Hot-Path (RYOW)"] = ("FAIL", f"user={user_auth}, asst={asst_auth}")
        conn.close()
    except Exception as e:
        results["L0 Hot-Path (RYOW)"] = ("FAIL", str(e))
        
    # 4. L1 Scope Hysteresis & Project Isolation
    try:
        active_scope, ret_scopes, _, _ = resolve_scope("How did we do auth in InvoiceFlow?", "hermes-jit-context-os")
        if active_scope == "hermes-jit-context-os" and "invoiceflow" in ret_scopes:
            results["L1 Scope Hysteresis"] = ("PASS", "active scope preserved, cross-project lookup scoped to retrieval")
        else:
            results["L1 Scope Hysteresis"] = ("FAIL", f"scope shifted prematurely: {active_scope}")
    except Exception as e:
        results["L1 Scope Hysteresis"] = ("FAIL", str(e))
        
    # 5. L2 Circuit Breaker & Fail-Open Check
    try:
        conn = get_db()
        cb = CircuitBreaker("doctor_l2")
        cb.record_failure(conn)
        cb.record_failure(conn)
        cb.record_failure(conn)
        if not cb.can_attempt(conn):
            results["L2 Circuit Breaker"] = ("PASS", "tripped after 3 consecutive failures (fail-open)")
        else:
            results["L2 Circuit Breaker"] = ("FAIL", "circuit did not trip")
        conn.close()
    except Exception as e:
        results["L2 Circuit Breaker"] = ("FAIL", str(e))
        
    # 6. Context Capsule Compilation
    try:
        conn = get_db()
        t0 = time.perf_counter()
        capsule = compile_context(
            conn=conn,
            session_id="doctor_check",
            user_message="Status check",
            conversation_history=[]
        )
        dur_ms = (time.perf_counter() - t0) * 1000
        if "<ONA_CONTEXT" in capsule and dur_ms < 10.0:
            results["Capsule Compiler"] = ("PASS", f"{len(capsule)} chars in {dur_ms:.2f}ms (<10ms)")
        else:
            results["Capsule Compiler"] = ("WARN", f"took {dur_ms:.2f}ms")
        conn.close()
    except Exception as e:
        results["Capsule Compiler"] = ("FAIL", str(e))
        
    # 7. Invariants I1–I11 Comprehensive Evaluation
    try:
        conn = get_db()
        inv_eval = evaluate_all_invariants(conn)
        failed_invs = [k for k, v in inv_eval.items() if (getattr(v, 'value', v) or '').lower() != "pass"]
        if len(inv_eval) == 11 and not failed_invs:
            results["Invariants I1–I11"] = ("PASS", "11/11 Invariants PASS")
        else:
            results["Invariants I1–I11"] = ("FAIL", f"Evaluated {len(inv_eval)}/11; failed: {failed_invs}")
        conn.close()
    except Exception as e:
        results["Invariants I1–I11"] = ("FAIL", str(e))
        
    # 8. Live Health & Observatory Server (:8765)
    try:
        url = f"http://{os.environ.get('JIT_HEALTH_HOST', '127.0.0.1')}:{os.environ.get('JIT_HEALTH_PORT', '8765')}/health"
        req = urllib.request.urlopen(url, timeout=1.0)
        if req.status == 200:
            data = json.loads(req.read().decode())
            daemon_status = data.get("status")
            results["Observatory Daemon"] = (
                "PASS" if daemon_status == "healthy" else "FAIL",
                f"{url} (status={daemon_status})",
            )
        else:
            results["Observatory Daemon"] = ("FAIL", f"{url} returned HTTP {req.status}")
    except Exception as e:
        results["Observatory Daemon"] = ("FAIL", f"not responding ({e})")

    # 9. JEV Decision Engine (Alpha API & Hybrid Invariant I6)
    try:
        from cognitive.jev_engine import get_jev_scorer
        scorer = get_jev_scorer()
        candidates = [
            {"key": "c1", "value": "decision tree engine"},
            {"key": "c2", "value": "banana fruit"}
        ]
        reranked = scorer.rerank_hybrid("decision engine", candidates)
        if len(reranked) == 2 and reranked[0]["key"] == "c1":
            if scorer.api_key and scorer._breaker.allow_request():
                results["JEV Decision Engine"] = ("PASS", "upstream API active (~typesafe/jev-latest) + Invariant I6 fail-open OK")
            else:
                results["JEV Decision Engine"] = ("PASS", "offline token fallback verified (Invariant I6 fail-open OK)")
        else:
            results["JEV Decision Engine"] = ("FAIL", "hybrid reranking degraded")
    except Exception as e:
        results["JEV Decision Engine"] = ("FAIL", str(e))
        
    # Print report
    print("\nDIAGNOSTIC RESULTS:")
    print("-" * 60)
    all_ok = all(status == "PASS" for status, _ in results.values())
    for item, (status, detail) in results.items():
        color = "\033[92m" if status == "PASS" else ("\033[93m" if status == "WARN" else "\033[91m")
        reset = "\033[0m"
        print(f" {item:<24} [{color}{status}{reset}]  {detail}")

    print("-" * 60)
    print("\nONA CONTEXT OS SUMMARY")
    print("────────────────────────────────────────")
    for item, (status, _) in results.items():
        print(f"{item:<24} {status}")
    passed = sum(status == "PASS" for status, _ in results.values())
    print(f"Checks                   {passed}/{len(results)} PASS")
    print("────────────────────────────────────────")

    if all_ok:
        print("READY FOR ACTIVE\n")
    else:
        print("BLOCKED — CHECK RESULTS ABOVE\n")

    return all_ok


def main() -> int:
    return 0 if run_doctor() else 1


if __name__ == "__main__":
    sys.exit(main())
