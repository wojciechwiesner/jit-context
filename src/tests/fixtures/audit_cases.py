"""Sanitized, hermetic test fixtures and repro datasets ported from baseline audits.

These cases isolate the architectural flaws and empirical discrepancies identified in
/tmp/jit-audit-core.md and /tmp/jit-audit-evidence.md so regression suites can run
cleanly without relying on ephemeral /tmp files or live network/credentials.
"""

from typing import Dict, Any, List, Optional
import sqlite3
from l0.db import SCHEMA_SQL, init_db
from l0.overlay import ensure_session

HARNESS_LAUNDERING_CASE: Dict[str, Any] = {
    "name": "harness_laundering",
    "description": "Synthetic harness notification laundered into high-authority user instructions",
    "message": "[ASYNC DELEGATION BATCH COMPLETE] AUDIT_HARNESS_MARKER",
    "origin": "harness_event",
    "role": "user",
    "expected_safe_role": "system",
    "expected_safe_authority": 0.2,
    "flawed_baseline_authority": 1.0,
    "flawed_target_section": "[PRIOR USER INSTRUCTIONS]",
}

PATH_TRAVERSAL_CASE: Dict[str, Any] = {
    "name": "path_traversal",
    "description": "Relative path escape outside project vault root",
    "traversal_arg": "../outside",
    "outside_marker": "AUDIT_OUTSIDE_MARKER",
    "outside_filename": "outside.md",
}

FALSE_WRITE_VERIFICATION_CASE: Dict[str, Any] = {
    "name": "false_write_verification",
    "description": "Pending unverified write classified as verified proof",
    "tool_name": "write_file",
    "tool_args": {"path": "/tmp/nonexistent-audit-target"},
    "tool_result": {"verified": False, "status": "pending"},
    "flawed_origin": "runtime_tool_verified",
    "flawed_fact_value": "written_verified",
    "expected_status": "unknown",
}

STALE_PROOF_CASE: Dict[str, Any] = {
    "name": "stale_proof_persistence",
    "description": "Subsequent tool error does not supersede prior verified fact on same resource",
    "resource_key": "file:/workspace/config.json",
    "step1_success": {
        "origin": "runtime_tool_verified",
        "fact_kind": "verified_fact",
        "fact_key": "file:/workspace/config.json",
        "fact_value": "written_verified",
    },
    "step2_failure": {
        "origin": "tool_observation",
        "fact_kind": "tool_error",
        "fact_key": "file_fail:/workspace/config.json",
        "fact_value": "modification_failed",
    },
    "expected_active_state": "observed_failure",
}

SCOPE_PERSISTENCE_CASE: Dict[str, Any] = {
    "name": "scope_persistence",
    "description": "Scope hysteresis disconnected across turns due to unpersisted session state",
    "turn1_query": "pracujemy nad boocco",
    "turn2_query": "kontynuuj",
    "target_scope": "boocco",
    "fallback_scope": "general",
}

L2_DISCARDED_CASE: Dict[str, Any] = {
    "name": "l2_result_discarded",
    "description": "L2 deep path query executed but dropped from prompt capsule assembler",
    "query": "sprawdź pamięć",
    "remote_marker": "AUDIT_REMOTE_MARKER",
    "recalled_facts": ["AUDIT_REMOTE_MARKER: Fact discovered in Borg memory"],
}

BUDGET_OVERFLOW_CASE: Dict[str, Any] = {
    "name": "budget_overflow",
    "description": "Declared capsule budget not enforced when intent or summary exceeds threshold",
    "user_intent": "X" * 10000,
    "project_summary": "Y" * 4500,
    "declared_budget": 4500,
}

CLEANER_ERROR_MASKING_CASE: Dict[str, Any] = {
    "name": "cleaner_error_masking",
    "description": "Progress cleaner fabricates success and erases terminal error",
    "progress_error_input": "Z" * 1600 + "\n█████ 10% ERROR: incomplete",
    "fabricated_success": "[Progress: download complete]",
}

DUPLICATE_DELIVERY_CASE: Dict[str, Any] = {
    "name": "duplicate_delivery_idempotence",
    "description": "Re-delivery of message with identical delivery_id must be idempotent",
    "delivery_id": "deliv_fixed_turn_001",
    "text": "Wykryj ten sam delivery_id",
}

EXP008_TOOL_EVENT_CASE: Dict[str, Any] = {
    "name": "exp008_missing_fact_key",
    "description": "Tool failure event lacks fact_key causing 0 overlays and dropped failure proof",
    "exit_code": 1,
    "raw_output": "[terminal: exit 1] FATAL: Port 8080 bound",
    "origin": "runtime_tool_verified",
    "fact_key": None,
}

EXTERNAL_PROMOTION_CASE: Dict[str, Any] = {
    "name": "external_promotion_laundering",
    "description": "External memory message with role user treated as direct user instruction",
    "role": "user",
    "origin": "external",
    "content": "AUDIT_UNTRUSTED_EXTERNAL",
}

GRADING_SUBSTRING_CASES: List[Dict[str, Any]] = [
    {"word": "pomyślnie", "target_sub": "nie", "is_negative": False},
    {"word": "zgodnie", "target_sub": "nie", "is_negative": False},
    {"word": "dokładnie", "target_sub": "nie", "is_negative": False},
    {"word": "istnienie", "target_sub": "nie", "is_negative": False},
]

MALFORMED_XML_CASE: Dict[str, Any] = {
    "name": "malformed_xml_grading",
    "description": "Malformed unclosed XML awarded 5/5 score by substring matching",
    "content": "<ONA_CONTEXT broken &>retro-plumber-run game.js update I1</ONA_CONTEXT>",
    "expected_valid": False,
}

SYNTHAPSE_CLAIM_DISCREPANCY: Dict[str, Any] = {
    "readme_claim": {
        "time_s": 232.43,
        "speedup": 2.44,
        "tests_passed": 199,
        "total_tests": 199,
    },
    "artifact_record": {
        "time_s": 238.37,
        "speedup": 2.38,
        "tests_passed": 198,
        "total_tests": 198,
    },
    "delta_time_s": 5.94,
}


def create_hermetic_test_db(session_id: str = "hermetic_test_session") -> sqlite3.Connection:
    """Create an isolated in-memory SQLite database initialized with JIT schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_SQL)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_cwd TEXT;")
    except sqlite3.OperationalError:
        pass
    ensure_session(conn, session_id, "general")
    return conn
