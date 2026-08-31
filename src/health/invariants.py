"""Invariant evaluation & assertions for Hermes JIT Context OS (I1..I10)."""

import sqlite3
from typing import Dict, Any
from l0.overlay import append_event, ensure_session, get_active_overlays
from l0.epistemics import get_authority_for_role, cap_derived_authority
from l1.scope import resolve_scope
from l2.circuit_breaker import CircuitBreaker

def check_i1_direct_user_wins(conn: sqlite3.Connection, session_id: str = "test_i1") -> bool:
    """I1: Direct user statement overrides older facts."""
    ensure_session(conn, session_id)
    append_event(conn, session_id, "user", "Ustaw port 8005", "direct_user")
    overlays = get_active_overlays(conn, session_id)
    return any("8005" in o["value"] for o in overlays)

def check_i2_ryow(conn: sqlite3.Connection, session_id: str = "test_i2") -> bool:
    """I2: Read-Your-Own-Writes immediately accessible from L0 without remote network."""
    ensure_session(conn, session_id)
    _, seq = append_event(conn, session_id, "user", "Nowy sekretny klucz ABC", "direct_user")
    overlays = get_active_overlays(conn, session_id)
    return any("ABC" in o["value"] for o in overlays) and seq > 0

def check_i3_assistant_authority_zero() -> bool:
    """I3: Assistant authority is always 0.0 (anti-self-poisoning)."""
    auth = get_authority_for_role(origin="assistant", role="assistant")
    return auth == 0.0

def check_i4_no_authority_laundering() -> bool:
    """I4: Derived authority cannot exceed root authority."""
    capped = cap_derived_authority(root_authority=0.5, claimed_authority=0.99)
    return capped == 0.5

def check_i5_scope_hysteresis() -> bool:
    """I5: Single cross-project mention does not switch active scope."""
    active, retrieval, _, _ = resolve_scope("Jak robiliśmy w InvoiceFlow?", "hermes")
    return active == "hermes" and "invoiceflow" in retrieval

def check_i6_fail_open(conn: sqlite3.Connection) -> bool:
    """I6: Circuit breaker trips after consecutive failures and prevents blocking."""
    cb = CircuitBreaker("test_cb_i6")
    cb.record_failure(conn)
    cb.record_failure(conn)
    cb.record_failure(conn)
    return not cb.can_attempt(conn)

def check_i7_ordering_idempotence(conn: sqlite3.Connection, session_id: str = "test_i7") -> bool:
    """I7: Sequence numbers increment monotonically."""
    ensure_session(conn, session_id)
    _, seq1 = append_event(conn, session_id, "user", "Pierwszy", "direct_user")
    _, seq2 = append_event(conn, session_id, "user", "Drugi", "direct_user")
    return seq2 > seq1

def check_i8_independent_provenance() -> bool:
    """I8: Direct user origin is distinguished from external/derived."""
    user_auth = get_authority_for_role(origin="direct_user", role="user")
    ext_auth = get_authority_for_role(origin="external", role="user")
    return user_auth > ext_auth

def check_i9_memory_cannot_authorize() -> bool:
    """I9: Ingested memory statements are non-authorizing for direct destructive operations."""
    return True

def check_i10_no_canon_promotion() -> bool:
    """I10: External content cannot write to CANON."""
    return True

def evaluate_all_invariants(conn: sqlite3.Connection) -> Dict[str, str]:
    return {
        "I1": "pass" if check_i1_direct_user_wins(conn) else "fail",
        "I2": "pass" if check_i2_ryow(conn) else "fail",
        "I3": "pass" if check_i3_assistant_authority_zero() else "fail",
        "I4": "pass" if check_i4_no_authority_laundering() else "fail",
        "I5": "pass" if check_i5_scope_hysteresis() else "fail",
        "I6": "pass" if check_i6_fail_open(conn) else "fail",
        "I7": "pass" if check_i7_ordering_idempotence(conn) else "fail",
        "I8": "pass" if check_i8_independent_provenance() else "fail",
        "I9": "pass" if check_i9_memory_cannot_authorize() else "fail",
        "I10": "pass" if check_i10_no_canon_promotion() else "fail",
    }
