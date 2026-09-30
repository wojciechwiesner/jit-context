"""Tests for the Agent Zero deterministic Loop Guard extensions and helper.

Covers:
1. Exact repeat detected (normalized args, before-hook classification, after-hook nudge)
2. Near-repeat search detected (Jaccard query similarity, repeat label)
3. No-progress streak nudge (stall window triggers steering message in response.message)
4. Disabled switch (via environment variable JIT_A0_LOOP_GUARD=0 and plugin config)
5. Agent is None (graceful no-op)
"""

import asyncio
import importlib.util
import os
import pytest
from typing import Any, Dict

from tests import conftest  # noqa: F401 (stubs framework)
from helpers.loop_guard import LoopGuard, CONTINUE, NUDGE, FORCE_ANSWER

BEFORE_EXT_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/tool_execute_before/_20_jit_loop_guard.py",
)
AFTER_EXT_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/tool_execute_after/_20_jit_loop_guard.py",
)


def _load_ext(path: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MockResponse:
    def __init__(self, message: str = ""):
        self.message = message
        self.break_loop = False
        self.additional = None


class MockLoopData:
    def __init__(self, iteration: int = 0):
        self.iteration = iteration


class MockAgent:
    def __init__(self, iteration: int = 0):
        self.data: Dict[str, Any] = {}
        self.loop_data = MockLoopData(iteration)

    def get_data(self, key: str, recursive: bool = True) -> Any:
        return self.data.get(key, None)

    def set_data(self, key: str, value: Any, recursive: bool = True) -> None:
        self.data[key] = value


def test_helper_direct_contract():
    """Verify helpers/loop_guard.py maintains exact contract and thresholds."""
    g = LoopGuard(max_turns=15)
    assert g.classify_call("web_search", {"query": "Mercedes Sosa albums"}) is None
    assert g.classify_call("web_search", {"query": "mercedes  sosa albums"}) == "exact_repeat"
    assert g.classify_call("web_search", {"query": "Girls Who Code women 37%"}) is None
    assert g.classify_call("web_search", {"query": "Girls Who Code women 37% 24%"}) == "near_repeat"

    # Novelty tracking
    assert g.observe_output(1, "web_search", "unique token alpha beta gamma") > 0.0
    assert g.observe_output(2, "web_search", "unique token alpha beta gamma") == 0.0


def test_exact_repeat_detected_and_nudged():
    """Exact repeat is detected in before-hook and nudged in after-hook."""
    mod_before = _load_ext(BEFORE_EXT_PATH, "test_before_exact")
    mod_after = _load_ext(AFTER_EXT_PATH, "test_after_exact")

    agent = MockAgent(iteration=0)
    ext_before = mod_before.JitLoopGuardBeforeExtension(agent=agent)
    ext_after = mod_after.JitLoopGuardAfterExtension(agent=agent)

    # Call 1: first execution of web_search
    asyncio.run(ext_before.execute(tool_name="web_search", tool_args={"query": "Mercedes Sosa albums"}))
    last_call = agent.get_data("jit_loop_guard_last_call")
    assert last_call["repeat"] is None
    assert agent.get_data("jit_loop_guard_pending_nudge") is None

    resp1 = MockResponse("Discography: 1959 La voz de la zafra, 1965 Canciones con fundamento")
    asyncio.run(ext_after.execute(response=resp1, tool_name="web_search"))
    assert "[LOOP GUARD]" not in resp1.message

    # Call 2: exact repeat with extra whitespace and case variations
    agent.loop_data.iteration = 1
    asyncio.run(ext_before.execute(tool_name="web_search", tool_args={"query": "mercedes  sosa albums"}))
    last_call = agent.get_data("jit_loop_guard_last_call")
    assert last_call["repeat"] == "exact_repeat"
    assert "Exact repeat" in agent.get_data("jit_loop_guard_pending_nudge")

    resp2 = MockResponse("Discography: 1959 La voz de la zafra, 1965 Canciones con fundamento")
    asyncio.run(ext_after.execute(response=resp2, tool_name="web_search"))
    assert "[LOOP GUARD] Warning: Exact repeat of tool 'web_search'" in resp2.message

    guard: LoopGuard = agent.get_data("jit_loop_guard")
    assert guard.summary()["repeats"] == 1


def test_near_repeat_search():
    """Near-repeat search query is classified and tracked as zero-progress."""
    mod_before = _load_ext(BEFORE_EXT_PATH, "test_before_near")
    mod_after = _load_ext(AFTER_EXT_PATH, "test_after_near")

    agent = MockAgent(iteration=0)
    ext_before = mod_before.JitLoopGuardBeforeExtension(agent=agent)
    ext_after = mod_after.JitLoopGuardAfterExtension(agent=agent)

    # Search 1
    asyncio.run(ext_before.execute(
        tool_name="web_search",
        tool_args={"query": "Girls Who Code women computer scientists 37%"},
    ))
    assert agent.get_data("jit_loop_guard_last_call")["repeat"] is None
    resp1 = MockResponse("Results about female representation in computing")
    asyncio.run(ext_after.execute(response=resp1, tool_name="web_search"))

    # Search 2: high token overlap (>75% Jaccard)
    agent.loop_data.iteration = 1
    asyncio.run(ext_before.execute(
        tool_name="web_search",
        tool_args={"query": "Girls Who Code women computer scientists 37% 24%"},
    ))
    assert agent.get_data("jit_loop_guard_last_call")["repeat"] == "near_repeat"
    resp2 = MockResponse("Results about female representation in computing updated")
    asyncio.run(ext_after.execute(response=resp2, tool_name="web_search"))

    guard: LoopGuard = agent.get_data("jit_loop_guard")
    events = guard.events
    assert len(events) == 2
    assert events[1]["repeat"] == "near_repeat"
    assert events[1]["streak"] == 1  # near_repeat counted as no progress


def test_no_progress_streak_nudge():
    """3 consecutive no-progress calls trigger a stall nudge in response.message."""
    mod_before = _load_ext(BEFORE_EXT_PATH, "test_before_streak")
    mod_after = _load_ext(AFTER_EXT_PATH, "test_after_streak")

    agent = MockAgent(iteration=0)
    ext_before = mod_before.JitLoopGuardBeforeExtension(agent=agent)
    ext_after = mod_after.JitLoopGuardAfterExtension(agent=agent)

    stale_output = "alpha beta gamma delta epsilon zeta eta theta iota kappa"

    # Call 1: establishes evidence pool (novelty > 10%)
    asyncio.run(ext_before.execute(tool_name="code_exec", tool_args={"code": "run_0()"}))
    resp1 = MockResponse(stale_output)
    asyncio.run(ext_after.execute(response=resp1, tool_name="code_exec"))
    assert "[LOOP GUARD]" not in resp1.message

    # Calls 2, 3: zero novelty, but streak < stall_window (3)
    for i in range(1, 3):
        agent.loop_data.iteration = i
        asyncio.run(ext_before.execute(tool_name="code_exec", tool_args={"code": f"run_{i}()"}))
        resp = MockResponse(stale_output)
        asyncio.run(ext_after.execute(response=resp, tool_name="code_exec"))
        assert "LOOP DETECTED" not in resp.message

    # Call 4: 3rd consecutive no-progress call -> stall window (3) hit!
    agent.loop_data.iteration = 3
    asyncio.run(ext_before.execute(tool_name="code_exec", tool_args={"code": "run_3()"}))
    resp4 = MockResponse(stale_output)
    asyncio.run(ext_after.execute(response=resp4, tool_name="code_exec"))

    assert "[LOOP GUARD]" in resp4.message
    assert "LOOP DETECTED: your last 3 tool calls returned no new information" in resp4.message
    guard: LoopGuard = agent.get_data("jit_loop_guard")
    assert guard.nudges >= 1


def test_disabled_switch_via_env(monkeypatch):
    """Setting JIT_A0_LOOP_GUARD=0 disables both before and after hooks."""
    monkeypatch.setenv("JIT_A0_LOOP_GUARD", "0")

    mod_before = _load_ext(BEFORE_EXT_PATH, "test_before_disabled_env")
    mod_after = _load_ext(AFTER_EXT_PATH, "test_after_disabled_env")

    agent = MockAgent(iteration=0)
    ext_before = mod_before.JitLoopGuardBeforeExtension(agent=agent)
    ext_after = mod_after.JitLoopGuardAfterExtension(agent=agent)

    asyncio.run(ext_before.execute(tool_name="web_search", tool_args={"query": "test"}))
    # No guard created, no state recorded
    assert agent.get_data("jit_loop_guard") is None
    assert agent.get_data("jit_loop_guard_last_call") is None

    resp = MockResponse("sample output")
    asyncio.run(ext_after.execute(response=resp, tool_name="web_search"))
    assert resp.message == "sample output"


def test_disabled_switch_via_config(monkeypatch):
    """Setting loop_guard_enabled: False in plugin config disables hooks."""
    from helpers import plugins
    monkeypatch.setattr(plugins, "get_plugin_config", lambda name, agent=None: {"loop_guard_enabled": False})

    mod_before = _load_ext(BEFORE_EXT_PATH, "test_before_disabled_cfg")
    mod_after = _load_ext(AFTER_EXT_PATH, "test_after_disabled_cfg")

    agent = MockAgent(iteration=0)
    ext_before = mod_before.JitLoopGuardBeforeExtension(agent=agent)
    ext_after = mod_after.JitLoopGuardAfterExtension(agent=agent)

    asyncio.run(ext_before.execute(tool_name="web_search", tool_args={"query": "test"}))
    assert agent.get_data("jit_loop_guard") is None

    resp = MockResponse("sample output")
    asyncio.run(ext_after.execute(response=resp, tool_name="web_search"))
    assert resp.message == "sample output"


def test_agent_none_safe_noop():
    """When agent is None, extensions safely return without exceptions."""
    mod_before = _load_ext(BEFORE_EXT_PATH, "test_before_none")
    mod_after = _load_ext(AFTER_EXT_PATH, "test_after_none")

    ext_before = mod_before.JitLoopGuardBeforeExtension(agent=None)
    ext_after = mod_after.JitLoopGuardAfterExtension(agent=None)

    # Must complete safely without error
    asyncio.run(ext_before.execute(tool_name="web_search", tool_args={"query": "test"}))
    resp = MockResponse("sample output")
    asyncio.run(ext_after.execute(response=resp, tool_name="web_search"))
    assert resp.message == "sample output"
