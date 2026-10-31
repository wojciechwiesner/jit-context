"""Hermes JIT engine against a real Hermes checkout (skipped when Hermes is not installed).

Run inside Hermes' interpreter so ``agent.*`` imports resolve:
  ~/.hermes/hermes-agent/venv/bin/python -m pytest src/tests/test_hermes_engine_integration.py
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

HERMES_ROOT = Path(os.environ.get("HERMES_AGENT_ROOT", Path.home() / ".hermes" / "hermes-agent"))
ENGINE_DIR = Path(__file__).resolve().parents[1] / "hermes_engine"

pytestmark = pytest.mark.skipif(
    not (HERMES_ROOT / "agent" / "context_compressor.py").exists() or importlib.util.find_spec("openai") is None,
    reason="needs a Hermes checkout and its venv",
)


@pytest.fixture()
def engine_module(monkeypatch):
    monkeypatch.syspath_prepend(str(HERMES_ROOT))
    spec = importlib.util.spec_from_file_location(
        "jit_engine_under_test", ENGINE_DIR / "__init__.py", submodule_search_locations=[str(ENGINE_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["jit_engine_under_test"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("jit_engine_under_test", None)


def _request(n_old_turns: int = 3) -> list[dict]:
    messages = [{"role": "system", "content": "sys"}]
    for turn in range(n_old_turns + 2):
        call_id = f"c{turn}"
        messages += [
            {"role": "user", "content": f"turn {turn}"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "terminal", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": call_id, "content": "out\n" + "y" * 6000},
        ]
    return messages


def test_engine_is_a_real_context_engine(engine_module):
    from agent.context_engine import ContextEngine
    engine = engine_module.JitContextEngine()
    assert isinstance(engine, ContextEngine)
    assert engine.name == "jit"


def test_compression_settings_come_from_hermes_parser(engine_module):
    kwargs = engine_module.compressor_kwargs_from_config()
    assert {"threshold_percent", "protect_last_n", "tail_mode"} <= set(kwargs)


def test_select_context_elides_old_results_only(engine_module):
    engine = engine_module.JitContextEngine()
    request = _request()
    selected = engine.select_context(request, conversation_messages=request)
    assert selected is not None and len(selected) == len(request)
    tool_contents = [m["content"] for m in selected if m["role"] == "tool"]
    assert sum(c.startswith("[JIT: earlier tool output elided") for c in tool_contents) == 3
    assert tool_contents[-1] == request[-1]["content"]
    assert engine.elided_results == 3


def test_disabled_flag_passes_through(engine_module, monkeypatch):
    monkeypatch.setenv("JIT_ENGINE_DISABLED", "1")
    assert engine_module.JitContextEngine().select_context(_request()) is None


def test_clone_for_agent_is_independent(engine_module):
    engine = engine_module.JitContextEngine()
    clone = engine.clone_for_agent()
    clone.select_context(_request())
    assert clone.elided_results == 3 and engine.elided_results == 0


def test_host_accepts_the_selection(engine_module):
    from types import SimpleNamespace
    import logging
    from agent.conversation_loop import _apply_context_engine_selection
    engine = engine_module.JitContextEngine()
    agent = SimpleNamespace(context_compressor=engine, session_id="t")
    request = _request()
    sent = _apply_context_engine_selection(agent, request, request, None, logger=logging.getLogger("t"))
    assert sent is not request
    assert sum(1 for m in sent if str(m.get("content", "")).startswith("[JIT:")) == 3


def test_register_hands_hermes_an_instance(engine_module):
    registered = []
    engine_module.register(type("Ctx", (), {"register_context_engine": lambda self, e: registered.append(e)})())
    assert len(registered) == 1 and registered[0].name == "jit"
