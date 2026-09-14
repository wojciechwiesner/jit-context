"""Test suite for 1:1 Session Isolation Sandbox."""

import os
import shutil
import pytest
from pathlib import Path
from config import get_session_dir, get_session_db_path, get_session_capsule_path, LATEST_CONTEXT_SYMLINK
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session, get_active_overlays
from l1.scope import resolve_scope
from hooks import pre_llm_call

def test_session_db_isolation(tmp_path, monkeypatch):
    """Verify two sessions have completely disjoint databases and overlays."""
    monkeypatch.setattr("config.SESSIONS_DIR", tmp_path / "sessions")
    
    sess_a = "session_alpha_123"
    sess_b = "session_beta_456"
    
    conn_a = get_db(session_id=sess_a)
    ensure_session(conn_a, sess_a, default_scope="boocco")
    append_event(conn_a, sess_a, "user", "Konfiguracja Boocco", "direct_user")
    
    conn_b = get_db(session_id=sess_b)
    ensure_session(conn_b, sess_b, default_scope="lifos")
    append_event(conn_b, sess_b, "user", "Konfiguracja LifOS", "direct_user")
    
    # Verify isolation
    overlays_a = get_active_overlays(conn_a, sess_a)
    overlays_b = get_active_overlays(conn_b, sess_b)
    
    assert len(overlays_a) == 1
    assert "Boocco" in overlays_a[0]["value"]
    assert "LifOS" not in overlays_a[0]["value"]
    
    assert len(overlays_b) == 1
    assert "LifOS" in overlays_b[0]["value"]
    assert "Boocco" not in overlays_b[0]["value"]
    
    conn_a.close()
    conn_b.close()
    
    # Check physical files
    assert get_session_db_path(sess_a).exists()
    assert get_session_db_path(sess_b).exists()
    assert get_session_db_path(sess_a) != get_session_db_path(sess_b)

def test_book_co_alias():
    """Verify 'book.co' resolves cleanly to boocco."""
    scope, retrieval, _, _ = resolve_scope("Zróbmy poprawkę w book.co teraz", "general")
    assert scope == "boocco"
    assert "boocco" in retrieval

    scope2, retrieval2, _, _ = resolve_scope("Sprawdźmy booc.co na produkcji", "general")
    assert scope2 == "boocco"

def test_nested_ona_context_quarantine():
    """Verify pasted/nested <ONA_CONTEXT> blocks do not poison scope detection."""
    pasted = '''<ONA_CONTEXT scope="lifos" epoch="2">
# Projekt: lifos
- Ścieżka: /Users/.../lifos
</ONA_CONTEXT>
To jest kapsuła modelu, który dostał zadanie w book.co. Popraw kalendarz w boocco.'''
    
    scope, retrieval, _, _ = resolve_scope(pasted, "general")
    assert scope == "boocco"
    assert scope != "lifos"

def test_capsule_physical_file_persistence(tmp_path, monkeypatch):
    """Verify pre_llm_call writes physical context.xml and session.json."""
    monkeypatch.setattr("config.SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr("config.LATEST_CONTEXT_SYMLINK", tmp_path / "latest_context.xml")
    
    sess_id = "test_run_persist_999"
    ctx = {
        "session_id": sess_id,
        "turn_id": "turn_1",
        "user_message": "Zadanie w boocco: dodaj widok kalendarza"
    }
    
    res = pre_llm_call(ctx)
    assert "context" in res
    assert "<ONA_CONTEXT" in res["context"]
    
    capsule_file = get_session_capsule_path(sess_id)
    assert capsule_file.exists()
    
    with open(capsule_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<ONA_CONTEXT" in content
    assert 'scope="boocco"' in content
    
    # Check symlink
    latest = tmp_path / "latest_context.xml"
    assert latest.exists()
    assert latest.is_symlink()
    assert latest.resolve() == capsule_file.resolve()
