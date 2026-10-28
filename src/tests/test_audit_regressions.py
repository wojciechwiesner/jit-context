"""Regression cases from the live context audit; no production state or network."""

import json

import pytest

from context.cascade_distiller import assemble_elastic_capsule, distill_context_cascade
from context.compiler import CapsuleResult
from hooks import extract_genuine_user_instruction, is_synthetic_harness_message
from l0.overlay import append_event, ensure_session


@pytest.mark.parametrize("text", [
    "[IMPORTANT: 3 background processes completed. Treat these results as one batch.]\nfix auth.py",
    "[IMPORTANT: MCP servers have been reloaded. Added servers: wunderui.]",
    "[ASYNC DELEGATION BATCH COMPLETE — task] Some generated fix suggestion.",
])
def test_host_notifications_are_not_user_instructions(text):
    assert is_synthetic_harness_message(text)


def test_reload_notice_preserves_the_actual_following_instruction():
    text = (
        "[IMPORTANT: MCP servers have been reloaded. Added servers: wunderui.]\n\n"
        "[IMPORTANT: MCP servers have been reloaded. Added servers: browseros-neo.]\n\n"
        "Obejmij to i dzialaj"
    )
    assert extract_genuine_user_instruction(text) == "Obejmij to i dzialaj"
    assert is_synthetic_harness_message(text)


def test_compiler_result_metadata_survives_hook_unpacking():
    from context.capsule_policy import unpack_compilation
    compiled = CapsuleResult("<ONA_CONTEXT/>", {"complexity": "feature", "budget": 16000})
    capsule, meta = unpack_compilation(compiled)
    assert capsule == "<ONA_CONTEXT/>"
    assert meta == compiled.meta
    assert unpack_compilation(("old", {"budget": 1000})) == ("old", {"budget": 1000})
    assert unpack_compilation("legacy") == ("legacy", {})


def test_task_switch_does_not_promote_historical_files_to_current_targets(tmp_path):
    old_file = tmp_path / "old-deploy.md"
    old_file.write_text("Old deployment notes")
    result = distill_context_cascade(
        ["czy to dziala?"], "jit-context", 2,
        dev_runtime={"cwd": str(tmp_path), "verify_cmd": "pytest"},
        working_set=[{"path": str(old_file), "summary": "1 lines"}],
    )
    current = result["capsule"].split("[DEV RUNTIME", 1)[0]
    assert "Execute '" not in current
    assert "Target Files:" not in result["capsule"]
    assert "Acceptance Criteria:" not in current


def test_generated_fields_are_advisory_and_targets_are_grounded(tmp_path):
    source = tmp_path / "auth.py"
    source.write_text("def login(): pass\n")
    capsule, _ = assemble_elastic_capsule(
        "jit-context", 1, 0.9, "feature", "Fix auth.py", [], [], [],
        dev_runtime={"cwd": str(tmp_path), "codebase_map": ["auth.py"]},
        intent="DIRECT_TASK", enhanced_spec="Fix login, not the previous project.",
        acceptance_criteria="Run tests", target_files=["auth.py", "/foreign/deploy.md"],
    )
    current = capsule.split("[DEV RUNTIME", 1)[0]
    assert "Enhanced Technical Spec" not in current
    assert "ADVISORY" in capsule
    assert "Target Files: [auth.py]" in capsule
    assert "/foreign/deploy.md" not in capsule


def test_final_hook_budget_is_bounded_after_alerts():
    from context.capsule_policy import finalize_capsule
    text = '<ONA_CONTEXT scope="test">\n' + "x" * 17000 + "\n</ONA_CONTEXT>\n<ALERT>notice</ALERT>"
    capsule, meta = finalize_capsule(text, {"budget": 16000})
    assert len(capsule) <= meta["budget"] <= 14000
    assert capsule.endswith("</ONA_CONTEXT>")
    assert "truncated" in capsule


def test_working_set_paths_include_actual_line_count_format():
    from context.capsule_policy import working_set_paths
    text = "• src/auth.py (42 lines)\n• src/store.py (written)\n• src/db.py (active module)"
    assert working_set_paths(text) == ["src/auth.py", "src/store.py", "src/db.py"]


def test_invariant_diagnostics_do_not_append_to_caller_db(test_db):
    from health.diagnostics import evaluate_all_invariants
    ensure_session(test_db, "real-session", default_scope="jit-context")
    append_event(test_db, "real-session", "user", "Do not invent user statements", "direct_user")
    before = test_db.total_changes
    for _ in range(2):
        statuses = evaluate_all_invariants(test_db)
        assert statuses
        assert all(value.value == "PASS" for value in statuses.values())
    assert test_db.total_changes == before
    assert test_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert test_db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1


def test_health_reports_real_scope_and_explicitly_disabled_l2(test_db, monkeypatch):
    import health.autocheck as autocheck
    ensure_session(test_db, "real-session", default_scope="jit-context")
    monkeypatch.setattr(autocheck, "L2_ENABLED", False, raising=False)
    before = test_db.total_changes
    report = autocheck.get_health_report(test_db)
    assert test_db.total_changes == before
    assert report["l1"]["active_scope"] == "jit-context"
    assert report["l2"]["enabled"] is False
    assert report["l2"]["status"] == "disabled"
    assert report["invariant_scope"] == "isolated_self_test"
    assert test_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_turn_telemetry_does_not_invent_a_counterfactual(test_db):
    from telemetry.collector import record_turn_telemetry
    from telemetry.db_schema import init_telemetry_schema
    ensure_session(test_db, "s1")
    init_telemetry_schema(test_db)
    record_turn_telemetry(test_db, "s1", "t1", "check", "jit-context", [], 1, 1, 0, 2, 3, "capsule")
    row = test_db.execute("SELECT haystack_tokens_est,jit_tokens_avoided_est FROM turn_telemetry").fetchone()
    assert tuple(row) == (0, 0)


def test_worker_reads_files_below_a_hidden_parent(tmp_path):
    from worker.local_agent import build_workspace_capsule
    root = tmp_path / ".hermes" / "scratch" / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src/auth.py").write_text("def login(): pass\n")
    (root / ".venv").mkdir()
    (root / ".venv/decoy.py").write_text("def login(): pass\n")
    capsule, evidence = build_workspace_capsule(root, "Fix login in auth.py")
    assert evidence["top_file"] == "src/auth.py"
    assert ".venv/decoy.py" not in capsule


def test_metrics_do_not_read_legacy_global_state_or_claim_savings(tmp_path, monkeypatch):
    from health import server
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(server, "telemetry_db_paths", lambda *_args: [])

    report = server.get_live_metrics_combined("all")
    assert report["live_jit"] == {}
    assert report["l0_latency_ms"] is None
    assert report["total_jit_avoided_tokens"] is None
    assert report["savings_measurement"]["status"] == "not_measured"
    assert report["telemetry_type"] == "mixed_live_and_estimated"


def test_live_status_uses_own_sessions_without_exposing_capsule(tmp_path):
    from health.live_status import latest_session_payload
    session = tmp_path / "project" / "session-1"
    session.mkdir(parents=True)
    (session / "session_1.json").write_text(json.dumps({
        "session_id": "session-1", "scope": "project", "capsule": "private fixture",
        "budget_chars": 14000,
    }))
    payload = latest_session_payload(tmp_path)
    assert payload["scope"] == "project"
    assert payload["budget_chars"] == 14000
    assert "capsule" not in payload
