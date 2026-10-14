"""Autochecker false positives: synthetic prompts, anchored goals, negated/proven claims (real-shaped inputs)."""
import json

import pytest

import telemetry.jitjevmods as mods_mod
import telemetry.turn_audit as ta
from context.goal_anchor import ANCHOR_MARKER, build_goal_anchor

ASYNC_PROMPT = ("[ASYNC DELEGATION BATCH COMPLETE — deleg_1e468aa5]\n"
                "A background fan-out unit you dispatched has finished.")
LONG_PROMPT = ("Generate 12 photorealistic still images (F01..F12) of Paula in Google Flow, already open in the "
               "browser tab, each 16:9 landscape, saved as F01.png through F12.png in the project folder. ") * 3
VERIFY = {"terminal"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(mods_mod, "MODS_JSON", tmp_path / "mods.json")
    monkeypatch.setattr(mods_mod, "MODS_MD", tmp_path / "jitjevmods.md")
    monkeypatch.setattr(ta, "AUDIT_DIR", tmp_path)


def capsule_with(goal):
    return f'<ONA_CONTEXT scope="general">\n    • Goal: {goal}\n</ONA_CONTEXT>'


def audit(prompt, output="", capsule="", tools=()):
    return ta.audit("s1", "t1", prompt, output, list(tools), capsule, {}, ["general"], None, 5.0)


def keys(report):
    return {f["key"] for f in report["findings"]}


# ---- 1. synthetic prompts
@pytest.mark.parametrize("text", [
    ASYNC_PROMPT,
    "[IMPORTANT: 2 background processes completed. Treat...]",
    "[IMPORTANT: The user has invoked the \"jit\" skill, indicating they want you to follow it.]",
    "[SYSTEM: model was just switched]",
    "<system-reminder>x</system-reminder>",
])
def test_synthetic_prompts_are_not_human_turns(text):
    assert not ta.is_human_turn({"role": "user", "content": text})
    assert ta.is_synthetic_prompt(text)


def test_genuine_prompt_is_a_human_turn():
    assert ta.is_human_turn({"role": "user", "content": "dawaj, zrób to"})
    assert not ta.is_synthetic_prompt("dawaj, zrób to")


def test_synthetic_prompt_never_triggers_goal_checks():
    r = audit(ASYNC_PROMPT, capsule=capsule_with("dawaj,"))
    assert not keys(r) & {"capsule_goal_stale", "capsule_goal_truncated"}


def test_real_stale_goal_still_flagged():
    r = audit("stop the run and build a per-turn autochecker writing improvements",
              capsule=capsule_with("analyse whether the cognitive approach makes sense"))
    assert "capsule_goal_stale" in keys(r)


def test_live_turn_uses_last_genuine_human_turn(monkeypatch):
    seen = {}
    monkeypatch.setattr(ta, "audit", lambda sid, tid, prompt, *a, **k: seen.setdefault("prompt", prompt) and {"p": prompt})
    monkeypatch.setattr(ta, "persist", lambda r: None)
    monkeypatch.setattr(ta, "session_files", lambda s: {"meta": {}, "db": None, "scope_dirs": []})
    monkeypatch.setattr(ta, "session_cwd", lambda s: None)
    history = [{"role": "user", "content": "dawaj, zrób to"}, {"role": "assistant", "content": "ok"},
               {"role": "user", "content": ASYNC_PROMPT}]
    ta.audit_live_turn({"session_id": "s1", "conversation_history": history, "user_message": ASYNC_PROMPT})
    assert seen["prompt"] == "dawaj, zrób to"


# ---- 2. anchored goal
def test_anchored_goal_is_not_truncated():
    goal = build_goal_anchor(LONG_PROMPT).render()
    assert ANCHOR_MARKER in goal
    r = audit(LONG_PROMPT, capsule=capsule_with(goal))
    assert "capsule_goal_truncated" not in keys(r)


def test_plain_prefix_goal_still_flagged_truncated():
    r = audit(LONG_PROMPT, capsule=capsule_with(LONG_PROMPT[:90]))
    assert "capsule_goal_truncated" in keys(r)


# ---- 3. claim_without_proof
@pytest.mark.parametrize("output", ["Gotowe, serwer działa.", "Fixed and deployed."])
def test_bare_claim_is_flagged(output):
    assert "claim_without_proof" in keys(audit("napraw serwer", output))


@pytest.mark.parametrize("output", [
    "Niestety nie działa, trzeba zajrzeć w logi.",
    "This is not done yet.",
    "Powiem Ci, jeśli to działa po restarcie.",
    "Let me know if it works for you.",
    "pytest: 12 passed. Gotowe.",
    "curl returned HTTP/1.1 200 OK, serwer działa.",
    "Command finished with exit=0, wszystko działa.",
])
def test_negated_conditional_or_proven_claim_is_not_flagged(output):
    assert "claim_without_proof" not in keys(audit("napraw serwer", output))


def test_negation_in_earlier_sentence_does_not_mask_claim():
    assert "claim_without_proof" in keys(audit("x", "Tego nie ruszałem. Gotowe, wszystko działa."))


def test_claim_with_verify_tool_is_not_flagged():
    tool = {"name": "terminal", "args": {"command": "pytest"}, "result": "ok"}
    assert "claim_without_proof" not in keys(audit("x", "Gotowe.", tools=[tool]))
