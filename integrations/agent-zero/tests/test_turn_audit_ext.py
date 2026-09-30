"""Tests for Agent Zero turn audit extension, rules, ledger, and status API."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import pytest

from tests import conftest  # noqa: F401  (stubs framework)

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent
_RULES_PATH = _PLUGIN_ROOT / "helpers" / "turn_audit_rules.py"
_MODS_PATH = _PLUGIN_ROOT / "helpers" / "jitjevmods.py"
_EXT_PATH = _PLUGIN_ROOT / "extensions" / "python" / "monologue_end" / "_30_jit_turn_audit.py"
_STATUS_PATH = _PLUGIN_ROOT / "api" / "jit_status.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rules_mod = _load_module("turn_audit_rules", _RULES_PATH)
mods_mod = _load_module("jitjevmods", _MODS_PATH)
ext_mod = _load_module("jit_turn_audit_ext", _EXT_PATH)
status_mod = _load_module("jit_status", _STATUS_PATH)


class _Ctx:
    def __init__(self, cid="session-test-123"):
        self.id = cid


class _Agent:
    def __init__(self, cid="session-test-123"):
        self.context = _Ctx(cid)
        self.last_user_message = None
        self.history = None


class _LiveLoopData:
    def __init__(self, user_msg="", last_resp="", hist=None, tools=None):
        self.user_message = {"content": user_msg} if user_msg else None
        self.last_response = last_resp
        self.history_output = hist or []
        self.tools = tools
        self.system = ["<jit_capsule><core_canon></core_canon></jit_capsule>"]


# ---------------------------------------------------------------- Tests

def test_record_to_score():
    """Verify turn record -> scored audit report with correct weight deduction."""
    clean_record = {
        "user_message": "sprawdz czy serwer dziala",
        "final_response": "Server is running.",
        "tools": [
            {"name": "terminal", "args": {"command": "curl http://localhost:8000"}, "result": "HTTP/1.1 200 OK", "error": False}
        ],
        "capsule": "<jit_capsule><goal>sprawdz serwer</goal></jit_capsule>",
        "duration_s": 5.0,
    }
    rep = rules_mod.audit_turn(clean_record)
    assert rep["score"] == 100
    assert rep["findings"] == []
    assert rep["harness"]["tool_calls"] == 1
    assert rep["harness"]["errors"] == 0

    # Claim without proof: Polish claim 'gotowe, działa' without any verify tool -> finding severity 'high' (25)
    unverified_record = {
        "user_message": "zrob backup bazy",
        "final_response": "Wszystko gotowe, działa poprawnie.",
        "tools": [],
        "capsule": "<jit_capsule><goal>zrob backup</goal></jit_capsule>",
        "duration_s": 1.0,
    }
    rep2 = rules_mod.audit_turn(unverified_record)
    finding_keys = {f["key"] for f in rep2["findings"]}
    assert "claim_without_proof" in finding_keys
    assert rep2["score"] == 75  # 100 - 25


def test_findings_duplicate_calls_and_tool_errors():
    """Verify duplicate tool calls detection and tool error rate rules."""
    # 1. Duplicate calls: calling terminal with same args twice
    dup_tools = [
        {"name": "terminal", "args": {"command": "ls -la"}, "result": "ok", "error": False},
        {"name": "terminal", "args": {"command": "ls -la"}, "result": "ok", "error": False},
    ]
    rep_dup = rules_mod.audit_turn({
        "prompt": "list files",
        "output": "listed",
        "tools": dup_tools,
        "capsule": "<jit_capsule></jit_capsule>",
    })
    keys_dup = {f["key"] for f in rep_dup["findings"]}
    assert "duplicate_calls" in keys_dup

    # 2. Distinct arguments to patch do NOT trigger duplicate_calls
    patch_tools = [
        {"name": "patch", "args": {"path": "app.py", "old_string": "foo", "new_string": "bar"}, "result": "ok", "error": False},
        {"name": "patch", "args": {"path": "app.py", "old_string": "baz", "new_string": "qux"}, "result": "ok", "error": False},
    ]
    rep_patch = rules_mod.audit_turn({
        "prompt": "patch files",
        "output": "patched",
        "tools": patch_tools,
        "capsule": "<jit_capsule></jit_capsule>",
    })
    keys_patch = {f["key"] for f in rep_patch["findings"]}
    assert "duplicate_calls" not in keys_patch

    # 3. Tool error rate: >= 4 calls with > 25% errors
    err_tools = [
        {"name": "terminal", "args": {"command": "cmd1"}, "result": "Error: command not found", "error": True},
        {"name": "terminal", "args": {"command": "cmd2"}, "result": "Traceback (most recent call last):", "error": True},
        {"name": "terminal", "args": {"command": "cmd3"}, "result": "ok", "error": False},
        {"name": "terminal", "args": {"command": "cmd4"}, "result": "ok", "error": False},
    ]
    rep_err = rules_mod.audit_turn({
        "prompt": "run commands",
        "output": "ran",
        "tools": err_tools,
        "capsule": "<jit_capsule></jit_capsule>",
    })
    keys_err = {f["key"] for f in rep_err["findings"]}
    assert "tool_error_rate" in keys_err


def test_ledger_merges_repeated_findings_and_renders_markdown(tmp_path):
    """Verify mods ledger merging, counting, example cap, status transition, and markdown generation."""
    json_path = tmp_path / "mods.json"
    md_path = tmp_path / "jitjevmods.md"

    finding = rules_mod.finding("claim_without_proof", "output claims 'działa' with tools=[]")
    source = {"session": "s1", "turn": "t1"}

    # Record 4 times to test count and max examples cap (MAX_EXAMPLES = 3)
    for i in range(4):
        mods_mod.record_mods([finding], {**source, "turn": f"t{i}"}, mods_json=json_path, mods_md=md_path)

    mods = mods_mod.load_mods(json_path)
    assert "claim_without_proof" in mods
    assert mods["claim_without_proof"]["count"] == 4
    assert len(mods["claim_without_proof"]["examples"]) == 3  # MAX_EXAMPLES cap

    md_content = md_path.read_text(encoding="utf-8")
    assert "## claim_without_proof" in md_content
    assert "4x" in md_content
    assert "| open |" in md_content

    # Transition status to done
    assert mods_mod.set_status("claim_without_proof", "done", mods_json=json_path, mods_md=md_path)
    mods_updated = mods_mod.load_mods(json_path)
    assert mods_updated["claim_without_proof"]["status"] == "done"

    md_content_updated = md_path.read_text(encoding="utf-8")
    assert "| done |" in md_content_updated


def test_jsonl_written_to_tmp_data_dir(tmp_path, monkeypatch):
    """Verify extension appends jsonl audit line and updates mods in tmp data directory."""
    audit_dir = tmp_path / "audits"
    monkeypatch.setenv("JIT_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("JIT_A0_TURN_AUDIT", "1")

    agent = _Agent("agent-sess-42")
    loop_data = {
        "user_message": {"content": "napraw serwer"},
        "last_response": "Naprawione, działa.",
        "history": [
            {"ai": False, "content": "napraw serwer"},
            {"ai": True, "content": "Naprawione, działa."},
        ],
        "duration_s": 2.5,
    }

    ext = ext_mod.JITTurnAuditExtension(agent=agent)
    asyncio.run(ext.execute(loop_data=loop_data))

    jsonl_file = audit_dir / "agent-sess-42.jsonl"
    assert jsonl_file.exists()
    lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["session"] == "agent-sess-42"
    assert "claim_without_proof" in [f["key"] for f in entry["findings"]]

    # Run second turn and verify append
    asyncio.run(ext.execute(loop_data=loop_data))
    lines_2 = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_2) == 2

    # mods.json and jitjevmods.md should also be created
    assert (audit_dir / "mods.json").exists()
    assert (audit_dir / "jitjevmods.md").exists()


def test_disabled_switch(tmp_path, monkeypatch):
    """Verify JIT_A0_TURN_AUDIT=0 disables extension completely without writing any files."""
    audit_dir = tmp_path / "audits"
    monkeypatch.setenv("JIT_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("JIT_A0_TURN_AUDIT", "0")

    agent = _Agent("sess-disabled")
    ext = ext_mod.JITTurnAuditExtension(agent=agent)
    asyncio.run(ext.execute(loop_data={"user_message": "test", "last_response": "done"}))

    assert not audit_dir.exists()


def test_agent_none(tmp_path, monkeypatch):
    """Verify extension handles agent=None safely without raising."""
    audit_dir = tmp_path / "audits"
    monkeypatch.setenv("JIT_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("JIT_A0_TURN_AUDIT", "1")

    ext = ext_mod.JITTurnAuditExtension(agent=None)
    loop_data = _LiveLoopData(user_msg="hello", last_resp="world")
    # Should not raise
    asyncio.run(ext.execute(loop_data=loop_data))

    # Should default to "default.jsonl"
    jsonl_file = audit_dir / "default.jsonl"
    assert jsonl_file.exists()


def test_status_api_includes_turn_audit(tmp_path, monkeypatch):
    """Verify Status API response includes turn_audit key with score, findings, and open_mods."""
    audit_dir = tmp_path / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JIT_AUDIT_DIR", str(audit_dir))

    # Initially empty
    handler = status_mod.Status(None, None)
    res_empty = asyncio.run(handler.process({}, None))
    assert "turn_audit" in res_empty
    assert res_empty["turn_audit"]["score"] is None
    assert res_empty["turn_audit"]["findings"] == []
    assert res_empty["turn_audit"]["open_mods"] == 0

    # Write audit log and mods.json
    audit_record = {
        "score": 85,
        "findings": [{"key": "spec_missing", "severity": "medium"}],
    }
    (audit_dir / "sess-api.jsonl").write_text(json.dumps(audit_record) + "\n", encoding="utf-8")
    mods = {
        "spec_missing": {"status": "open", "count": 1},
        "resolved_mod": {"status": "done", "count": 2},
    }
    (audit_dir / "mods.json").write_text(json.dumps(mods), encoding="utf-8")

    res = asyncio.run(handler.process({}, None))
    assert res["ok"] is True
    assert "turn_audit" in res
    ta = res["turn_audit"]
    assert ta["score"] == 85
    assert ta["findings"] == ["spec_missing"]
    assert ta["open_mods"] == 1

    # Verify existing keys remain intact
    for expected_key in ("ok", "jit", "jev", "tiers", "counts", "issues"):
        assert expected_key in res
