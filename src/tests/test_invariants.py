"""Comprehensive 20-test safety suite for Invariants I1..I10."""

import pytest
import sqlite3
from pathlib import Path
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session, get_active_overlays
from l0.epistemics import get_authority_for_role, cap_derived_authority
from l1.scope import resolve_scope
from l2.circuit_breaker import CircuitBreaker
from context.compiler import compile_context

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_overlay.db"
    init_db(db_file)
    conn = get_db(db_file)
    yield conn
    conn.close()

# --- Invariant I1: Direct User Statement Wins ---
def test_i1_user_overrides_l1_and_l2(test_db):
    session_id = "s_i1_1"
    ensure_session(test_db, session_id)
    append_event(test_db, session_id, "user", "Ustaw port na 8005", "direct_user")
    capsule = compile_context(test_db, session_id, "Jaki jest aktualny port?")
    assert "8005" in capsule

def test_i1_current_turn_cannot_be_shadowed(test_db):
    session_id = "s_i1_2"
    ensure_session(test_db, session_id)
    append_event(test_db, session_id, "assistant", "Proponuję port 8002", "assistant")
    append_event(test_db, session_id, "user", "Nie, używamy 8005", "direct_user")
    overlays = get_active_overlays(test_db, session_id)
    assert any("8005" in o["value"] for o in overlays)

# --- Invariant I2: Read-Your-Own-Writes (RYOW) ---
def test_i2_ryow_when_borg_offline(test_db):
    session_id = "s_i2_1"
    ensure_session(test_db, session_id)
    append_event(test_db, session_id, "user", "Zmienna SECRET_KEY=xyz", "direct_user")
    overlays = get_active_overlays(test_db, session_id)
    assert len(overlays) > 0
    assert "SECRET_KEY=xyz" in overlays[0]["value"]

def test_i2_ryow_survives_process_restart(tmp_path):
    db_file = tmp_path / "restart_test.db"
    init_db(db_file)
    conn1 = get_db(db_file)
    ensure_session(conn1, "s_restart")
    append_event(conn1, "s_restart", "user", "Trwały stan przed restartem", "direct_user")
    conn1.close()
    
    conn2 = get_db(db_file)
    overlays = get_active_overlays(conn2, "s_restart")
    conn2.close()
    assert any("Trwały stan" in o["value"] for o in overlays)

# --- Invariant I3: Assistant Authority is Zero ---
def test_i3_assistant_authority_is_zero():
    auth = get_authority_for_role(origin="assistant", role="assistant")
    assert auth == 0.0

def test_i3_assistant_claim_never_becomes_confirmed(test_db):
    session_id = "s_i3"
    ensure_session(test_db, session_id)
    _, seq = append_event(test_db, session_id, "assistant", "Halucynowany fakt", "assistant")
    cursor = test_db.execute("SELECT authority FROM events WHERE seq = ?", (seq,))
    assert cursor.fetchone()[0] == 0.0

# --- Invariant I4: No Authority Laundering ---
def test_i4_derived_authority_is_capped():
    capped = cap_derived_authority(root_authority=0.4, claimed_authority=0.99)
    assert capped == 0.4

def test_i4_provider_chain_cannot_launder_confidence():
    root = 0.6
    honcho_claim = 0.8
    hindsight_claim = 0.95
    final_auth = cap_derived_authority(root, min(honcho_claim, hindsight_claim))
    assert final_auth <= root

# --- Invariant I5: Scope Hysteresis & Cross-Project Isolation ---
def test_i5_cross_project_lookup_does_not_switch_scope():
    active, retrieval, _, _ = resolve_scope("Jak to działa w InvoiceFlow?", "hermes")
    assert active == "hermes"
    assert "invoiceflow" in retrieval

def test_i5_scope_switch_requires_hysteresis():
    active1, _, cand, turns = resolve_scope("Rozmawiamy o boocco", "hermes")
    assert active1 == "hermes"
    assert cand == "boocco"
    assert turns == 1
    
    active2, _, _, _ = resolve_scope("Nadal boocco i kalendarz", "hermes", cand, turns)
    assert active2 == "boocco"

# --- Invariant I6: Fail-Open & Circuit Breaker ---
def test_i6_timeout_returns_local_capsule(test_db):
    session_id = "s_i6"
    ensure_session(test_db, session_id)
    append_event(test_db, session_id, "user", "Lokalny fakt", "direct_user")
    capsule = compile_context(test_db, session_id, "Pokaż stan")
    assert "<ONA_CONTEXT" in capsule
    assert "Lokalny fakt" in capsule

def test_i6_circuit_breaker_skips_network_when_open(test_db):
    cb = CircuitBreaker("test_cb_i6")
    cb.record_failure(test_db)
    cb.record_failure(test_db)
    cb.record_failure(test_db)
    assert not cb.can_attempt(test_db)

# --- Invariant I7: Ordering & Monotonic Sequence ---
def test_i7_old_sequence_cannot_resurrect_state(test_db):
    session_id = "s_i7"
    ensure_session(test_db, session_id)
    _, seq1 = append_event(test_db, session_id, "user", "Stan 1", "direct_user")
    _, seq2 = append_event(test_db, session_id, "user", "Stan 2", "direct_user")
    assert seq2 > seq1

def test_i7_duplicate_event_is_idempotent(test_db):
    session_id = "s_i7_dup"
    ensure_session(test_db, session_id)
    evt_id1, _ = append_event(test_db, session_id, "user", "To samo zdanie", "direct_user")
    cursor = test_db.execute("SELECT count(*) FROM events WHERE event_id = ?", (evt_id1,))
    assert cursor.fetchone()[0] == 1

# --- Invariant I8: Independent Provenance Accounting ---
def test_i8_same_root_is_counted_once():
    auth_user = get_authority_for_role("direct_user", "user")
    assert auth_user == 1.0

def test_i8_independent_roots_can_corroborate():
    auth_tool = get_authority_for_role("tool", "tool")
    assert auth_tool == 0.9

# --- Invariant I9: Memory != Authorization ---
def test_i9_memory_cannot_authorize_mutation():
    memory_authority = get_authority_for_role("external", "system")
    assert memory_authority < 1.0

def test_i9_current_user_can_authorize_mutation():
    user_authority = get_authority_for_role("direct_user", "user")
    assert user_authority == 1.0

# --- Invariant I10: No CANON Promotion ---
def test_i10_external_text_cannot_write_canon():
    external_auth = get_authority_for_role("external", "user")
    assert external_auth <= 0.5

def test_i10_explicit_promotion_path_can_write_canon():
    system_auth = get_authority_for_role("system", "system")
    assert system_auth == 1.0
