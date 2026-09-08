"""Tests for SOTA Coding Capsule architecture (Dev Runtime, Working Set, Invariants, Pointers)."""

import pytest
from l0.db import init_db, get_db
from l0.overlay import ensure_session, append_event
from context.compiler import compile_context


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_overlay.db"
    init_db(db_file)
    conn = get_db(db_file)
    yield conn
    conn.close()


def test_sota_coding_capsule_renders_all_sections(test_db, tmp_path):
    session_id = "test_sota_session"
    ensure_session(test_db, session_id)

    # 1. User sets task
    append_event(test_db, session_id, "user", "Napraw błąd walidacji w webhooku", "direct_user")

    # 2. Simulate tool reading and mutating files (adds to L0 overlay)
    append_event(
        test_db, session_id, "tool", "[read_file] src/validator.py", "tool",
        fact_kind="tool_observation", fact_key="read:src/validator.py", fact_value="read_ok"
    )
    append_event(
        test_db, session_id, "tool", "[run_tests] exit 1", "tool",
        fact_kind="verified_fact", fact_key="pytest_failure", fact_value="AssertionError line 28 in test_webhook.py"
    )

    # Create dummy repo files in tmp_path
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_webhook.py").write_text("def test_ok(): pass", encoding="utf-8")
    (tmp_path / ".planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".planning" / "STATE.md").write_text(
        "# State\n- Invariant I1: Direct user input wins\n- ZAKAZ: Brak samozatruwania\n",
        encoding="utf-8"
    )

    # 3. Compile context
    capsule = compile_context(
        test_db,
        session_id=session_id,
        user_message="Napraw błąd walidacji w webhooku",
        session_cwd=str(tmp_path),
        allowed_tools=["read_file", "write_file", "run_tests", "finish"]
    )
    text = str(capsule)

    # 4. Verify presence of all key SOTA sections
    assert "<ONA_CONTEXT" in text
    assert "[CURRENT — direct user]" in text
    assert "Goal: Napraw błąd walidacji w webhooku" in text
    assert "Intent: BUG_REPORT" in text

    assert "[DEV RUNTIME & VERIFICATION]" in text
    assert f"Working Directory: {tmp_path}" in text
    assert "Verify Command: pytest" in text
    assert "Allowed Tools: [read_file, write_file, run_tests, finish]" in text

    assert "[WORKING SET & CONTRACTS]" in text
    assert "src/validator.py" in text

    assert "[VERIFIED RUNTIME PROOFS (Authority 1.0)]" in text
    assert "[pytest_failure] AssertionError line 28 in test_webhook.py" in text

    assert "[ACTIVE INVARIANTS]" in text
    assert "Invariant I1: Direct user input wins" in text
    assert "ZAKAZ: Brak samozatruwania" in text

    # Verify capsule size is in calibrated sweet spot (<1500 tokens / <6000 chars)
    assert len(text) < 5000
    assert len(text) > 400
