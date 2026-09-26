"""Per-turn autochecker: alignment chain, harness efficiency, mods ledger."""
import json

import pytest

import telemetry.jitjevmods as mods_mod
import telemetry.turn_audit as ta


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(mods_mod, "MODS_JSON", tmp_path / "mods.json")
    monkeypatch.setattr(mods_mod, "MODS_MD", tmp_path / "jitjevmods.md")
    monkeypatch.setattr(ta, "AUDIT_DIR", tmp_path)
    return tmp_path


def call(name, args, result="ok", cid=None):
    cid = cid or f"c{abs(hash((name, json.dumps(args, sort_keys=True), result))) % 10**8}"
    return ({"role": "assistant", "content": "", "tool_calls": [{"id": cid, "function": {"name": name, "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": cid, "content": result})


def run(prompt, output, calls, capsule="", goal="", cwd=None, tele=None, scopes=("general",)):
    tools = ta.collect_tools([m for c in calls for m in c])
    return ta.audit("s1", "t1", prompt, output, tools, capsule, tele or {}, list(scopes), cwd, 30.0)


def keys(report):
    return {f["key"] for f in report["findings"]}


def test_turn_slice_skips_out_of_band_and_background_notices():
    msgs = [{"role": "user", "content": "build the panel"}, {"role": "assistant", "content": "x"},
            {"role": "user", "content": "[OUT-OF-BAND USER MESSAGE — steer]\nalso english"},
            {"role": "user", "content": "[IMPORTANT: 2 background processes completed. Treat...]"}]
    assert ta.turn_slice(msgs)[0]["content"] == "build the panel"


def test_mcp_tool_names_are_normalised():
    assert ta.tool_name("mcp__dance_guilt__oven_terminal") == "terminal"
    assert ta.tool_name("mcp__dance_guilt__save_patch") == "patch"
    assert ta.tool_name("read_file") == "read_file"


def test_clean_turn_scores_100():
    capsule = '<ONA_CONTEXT scope="jit">\n    • Goal: fix the audit parser in turn_audit\n    • Acceptance Criteria: pytest passes\n</ONA_CONTEXT>'
    r = run("fix the audit parser in turn_audit", "Poprawione, testy przechodzą.",
            [call("patch", {"path": "/r/src/telemetry/turn_audit.py", "old_string": "a", "new_string": "b"}),
             call("terminal", {"command": "pytest -q"}, '{"output": "3 passed", "exit_code": 0}')], capsule=capsule)
    assert r["findings"] == [] and r["score"] == 100


def test_stale_capsule_goal_is_flagged():
    capsule = '<ONA_CONTEXT scope="general">\n    • Goal: analyse whether the cognitive approach makes sense\n</ONA_CONTEXT>'
    r = run("stop the run and build a per-turn autochecker writing improvements to jitjevmods", "ok", [], capsule=capsule)
    assert "capsule_goal_stale" in keys(r)


def test_claim_without_runtime_proof():
    r = run("napraw serwer", "Gotowe, serwer działa.", [call("patch", {"path": "/r/app.txt", "old_string": "a", "new_string": "b"})])
    assert "claim_without_proof" in keys(r)


def test_edit_after_last_verification():
    r = run("fix it", "done checking", [call("terminal", {"command": "pytest"}), call("write_file", {"path": "/r/a.py", "content": "x"})])
    assert "edit_not_verified" in keys(r)


def test_patches_with_different_bodies_are_not_duplicates_but_identical_commands_are():
    patches = [call("patch", {"path": "/r/a.py", "old_string": str(i), "new_string": "z"}) for i in range(4)]
    assert "duplicate_calls" not in keys(run("x", "", patches))
    same = [call("terminal", {"command": "ls"}, cid=f"id{i}") for i in range(3)]
    assert "duplicate_calls" in keys(run("x", "", same))


def test_tool_error_rate_and_rereads():
    err = '{"output": "", "exit_code": 1, "error": "boom"}'
    calls = [call("terminal", {"command": f"c{i}"}, err) for i in range(3)] + [call("read_file", {"path": "/r/big.py"}, cid=f"r{i}") for i in range(3)]
    k = keys(run("x", "", calls))
    assert {"tool_error_rate", "reread_same_file"} <= k


def test_scope_split_and_hook_latency():
    r = run("x", "", [], tele={"hook_total_ms": 900, "capsule_tokens_est": 200}, scopes=("general", "hermes"))
    assert {"scope_split", "hook_latency"} <= keys(r)


def test_project_goal_read_from_state_md(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".planning").mkdir()
    (tmp_path / ".planning" / "STATE.md").write_text("# S\n\n## Active Goal\nAlign JIT guarantees with runtime behavior.\n")
    assert ta.project_goal(str(tmp_path)) == "Align JIT guarantees with runtime behavior."
    r = run("bake a chocolate cake recipe please", "", [], cwd=str(tmp_path))
    assert "project_goal_offtrack" in keys(r)


def test_ledger_merges_repeated_findings_and_renders_markdown(isolated_ledger):
    for _ in range(3):
        ta.persist(run("napraw serwer", "Gotowe, działa.", []))
    data = json.loads((isolated_ledger / "mods.json").read_text())
    assert data["claim_without_proof"]["count"] == 3
    md = (isolated_ledger / "jitjevmods.md").read_text()
    assert md.count("## claim_without_proof") == 1 and "3x" in md
    assert (isolated_ledger / "s1.jsonl").read_text().count("\n") == 3
    assert mods_mod.set_status("claim_without_proof", "done")
    assert "| done |" in (isolated_ledger / "jitjevmods.md").read_text()
