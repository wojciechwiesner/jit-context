import pytest
from pathlib import Path
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session
from health.quality_guard import (
    audit_session_quality,
    check_tool_repetition_loops,
    check_tool_failure_burst,
    format_quality_alert
)

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_overlay.db"
    init_db(db_file)
    conn = get_db(db_file)
    yield conn
    conn.close()

def test_clean_session_is_healthy(test_db):
    session_id = "s_clean"
    ensure_session(test_db, session_id)
    append_event(test_db, session_id, "user", "Ustaw port", "direct_user")
    append_event(test_db, session_id, "tool", "[patch] successfully updated port", "tool", fact_kind="tool_observation", fact_key="patch:src/server.py")
    
    audit = audit_session_quality(test_db, session_id)
    assert audit["status"] == "healthy"
    assert audit["score"] == 1.0
    assert len(audit["anomalies"]) == 0

def test_tool_repetition_loop_detection(test_db):
    session_id = "s_loop"
    ensure_session(test_db, session_id)
    # Model calls read_file on same file repeatedly
    append_event(test_db, session_id, "tool", "[read_file] contents", "tool", fact_kind="tool_observation", fact_key="read_file:src/server.py")
    append_event(test_db, session_id, "tool", "[read_file] contents", "tool", fact_kind="tool_observation", fact_key="read_file:src/server.py")
    
    audit = audit_session_quality(test_db, session_id)
    assert audit["status"] in ("warning", "degraded")
    assert any("pętlę powtórzeń narzędzia" in a.get("message", "") for a in audit["anomalies"])
    alert = format_quality_alert(audit)
    assert alert is not None
    assert "ZAKAZ powtarzania tego samego wywołania narzędzia" in alert

def test_tool_failure_burst_detection(test_db):
    session_id = "s_err"
    ensure_session(test_db, session_id)
    append_event(test_db, session_id, "tool", "[terminal] Error: Command failed with exit code 1", "tool")
    append_event(test_db, session_id, "tool", "[patch] Failed to apply diff: syntax error", "tool")
    
    audit = audit_session_quality(test_db, session_id)
    assert audit["status"] in ("warning", "degraded")
    assert any("błędów narzędzi" in a.get("message", "") for a in audit["anomalies"])
