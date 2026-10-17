"""Exercise real hooks in a fresh HOME: no production session, notes, or legacy files."""

import json
import os
from pathlib import Path
import subprocess
import sys


HOOK_SCRIPT = r'''
import builtins
import json
import os
import re
from pathlib import Path

import config
import hooks
import l1.obsidian_sync
from l0.db import get_db
from l0.overlay import append_event, ensure_session, update_session_cwd

root = Path(os.environ["WORKSPACE"])
session_id = "test_runtime_goal"
config.MODE_FILE.write_text('{"mode":"active"}')
real_open = builtins.open

def isolated_open(path, *args, **kwargs):
    if str(path).startswith("/tmp/hermes-jit-"):
        path = Path.home() / Path(path).name
    return real_open(path, *args, **kwargs)

hooks.open = isolated_open
# Only the external note sink is isolated; compiler, DB, hooks and metadata are real.
l1.obsidian_sync.record_session_snapshot_to_obsidian = lambda **kwargs: None
conn = get_db(session_id=session_id)
ensure_session(conn, session_id)
update_session_cwd(conn, session_id, str(root))
foreign = Path.home() / "old-deployment.md"
foreign.write_text("Historical task from a different project")
append_event(conn, session_id, "tool", foreign.read_text(), "runtime_tool_verified",
             fact_key="read:" + str(foreign), fact_value="read_ok")
conn.close()

first_goal = "Analyze auth.py, do not deploy."
first = hooks.pre_llm_call({"session_id": session_id, "turn_id": "t1", "user_message": first_goal})
assert first and any("<ONA_CONTEXT" in str(v) for v in first.values()), first
notification = "[IMPORTANT: 3 background processes completed. Treat these results as one batch.]\nFix foreign.py"
second = hooks.pre_llm_call({"session_id": session_id, "turn_id": "t2", "user_message": notification})
meta_path = config.get_session_meta_path(session_id)
meta = json.loads(meta_path.read_text())
assert meta["goal_text"] == first_goal, meta["goal_text"]
working = meta["capsule"].split("[WORKING SET & CONTRACTS]", 1)
working = working[1].split("  [", 1)[0] if len(working) == 2 else ""
assert "old-deployment.md" not in working
assert "Target Files:" not in meta["capsule"].split("[DEV RUNTIME", 1)[0]
assert len(meta["capsule"]) <= meta["budget_chars"] <= 14000
assert meta["complexity"] == re.search(r'complexity="([^"]+)"', meta["capsule"]).group(1)
assert meta["compression_ratio"] is None
assert meta["savings_status"] == "not_measured"
assert meta["capsule"].endswith("</ONA_CONTEXT>")
assert "INFERRED" not in meta["capsule"].split("[CURRENT", 1)[0]

third_goal = "Fix auth.py"
third = hooks.pre_llm_call({
    "session_id": session_id, "turn_id": "t3",
    "user_message": "[IMPORTANT: MCP servers have been reloaded. Added servers: wunderui.]\n\n" + third_goal,
})
assert third
conn = get_db(session_id=session_id)
users = [row[0] for row in conn.execute("SELECT content FROM events WHERE origin='direct_user' ORDER BY seq")]
assert users == [first_goal, third_goal], users
assert conn.execute("SELECT COUNT(*) FROM events WHERE origin='harness_event' AND authority != 0").fetchone()[0] == 0
assert conn.execute("SELECT COUNT(*) FROM events WHERE origin='harness_event' AND role != 'system'").fetchone()[0] == 0
conn.close()
report = {
    "real_hook_calls": 3, "notification_preserves_goal": True,
    "reload_preserves_genuine_request": True, "foreign_working_set_excluded": True,
    "compiler_metadata_preserved": True, "capsule_chars": len(meta["capsule"]),
    "budget_chars": meta["budget_chars"], "invented_savings_removed": True,
    "production_state_used": False,
}
Path(os.environ["PROOF_PATH"]).write_text(json.dumps(report, indent=2))
'''


def test_real_pre_llm_hook_keeps_notification_and_user_authority_separate(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname="hook-runtime-test"\nversion="0.0.0"\n')
    (root / "auth.py").write_text("def login(): pass\n")
    home = tmp_path / "home"
    home.mkdir()
    proof = tmp_path / "hook-proof.json"
    environment = {
        "HOME": str(home), "HERMES_HOME": str(home / ".hermes"),
        "PATH": os.environ["PATH"], "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "WORKSPACE": str(root), "PROOF_PATH": str(proof), "JIT_L2_ENABLED": "0",
    }
    result = subprocess.run(
        [sys.executable, "-c", HOOK_SCRIPT], cwd=root, env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(proof.read_text())
    assert report["real_hook_calls"] == 3
    assert report["production_state_used"] is False
