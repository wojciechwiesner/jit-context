"""Chaos Suite for Hermes JIT Context OS."""

import pytest
from unittest.mock import patch
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session
from l2.client import query_deep_context
from l2.circuit_breaker import CircuitBreaker

@pytest.fixture
def chaos_db(tmp_path):
    db_file = tmp_path / "chaos_overlay.db"
    init_db(db_file)
    conn = get_db(db_file)
    yield conn
    conn.close()

def test_chaos_network_timeout_fails_open(chaos_db):
    """Simulate network timeout on Borg Gateway -> must fail-open without exception."""
    with patch("httpx.Client.post", side_effect=Exception("Connection timed out")):
        res = query_deep_context("Szukaj w pamięci", ["hermes"], chaos_db)
        assert res is None # Clean fail-open

def test_chaos_circuit_breaker_trips_after_3_failures(chaos_db):
    cb = CircuitBreaker("chaos_cb")
    assert cb.can_attempt(chaos_db) is True
    
    cb.record_failure(chaos_db)
    cb.record_failure(chaos_db)
    assert cb.can_attempt(chaos_db) is True # 2 failures -> still closed
    
    cb.record_failure(chaos_db) # 3rd failure -> trips to OPEN
    assert cb.can_attempt(chaos_db) is False

def test_chaos_malformed_json_response_fails_open(chaos_db):
    class MockResp:
        status_code = 500
        def json(self):
            return {"error": "Internal Borg Crash"}
            
    with patch("httpx.Client.post", return_value=MockResp()):
        res = query_deep_context("Zapytanie", ["hermes"], chaos_db)
        assert res is None
