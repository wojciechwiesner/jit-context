"""Wire selection for the Hermes JIT context engine (pure, no Hermes import)."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hermes_engine"))

from selection import POINTER_PREFIX, recent_turn_start, select_wire_messages  # noqa: E402

BIG = "x" * 5000


def _call(call_id: str, name: str = "terminal") -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}]}


def _result(call_id: str, text: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": text}


def _conversation() -> list[dict]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "turn 1"},
        _call("a", "read_file"), _result("a", "line one\n" + BIG),
        _call("b"), _result("b", "short ok"),
        {"role": "assistant", "content": "done with turn 1"},
        {"role": "user", "content": "turn 2"},
        _call("c"), _result("c", BIG),
        {"role": "user", "content": "turn 3"},
        _call("d"), _result("d", BIG),
    ]


def test_old_bulky_tool_results_become_pointers():
    selected, stats = select_wire_messages(_conversation(), keep_recent_turns=2, min_prune_chars=1200)
    assert stats.pruned_results == 1
    assert selected[3]["content"].startswith(POINTER_PREFIX)
    assert "read_file" in selected[3]["content"]
    assert "'line one'" in selected[3]["content"]
    assert stats.chars_saved > 4000


def test_recent_turns_short_results_and_texts_stay_verbatim():
    original = _conversation()
    selected, _ = select_wire_messages(original, keep_recent_turns=2, min_prune_chars=1200)
    assert selected[5]["content"] == "short ok"
    assert selected[9]["content"] == BIG
    assert selected[12]["content"] == BIG
    for index in (0, 1, 6, 7, 10):
        assert selected[index] == original[index]


def test_every_tool_result_keeps_its_call():
    selected, _ = select_wire_messages(_conversation(), keep_recent_turns=1, min_prune_chars=0)
    call_ids = {c["id"] for m in selected for c in (m.get("tool_calls") or [])}
    result_ids = [m["tool_call_id"] for m in selected if m["role"] == "tool"]
    assert len(selected) == len(_conversation())
    assert set(result_ids) <= call_ids


def test_input_is_never_mutated():
    original = _conversation()
    snapshot = copy.deepcopy(original)
    select_wire_messages(original, keep_recent_turns=1, min_prune_chars=0)
    assert original == snapshot


def test_short_conversation_is_untouched():
    messages = _conversation()[:6]
    selected, stats = select_wire_messages(messages, keep_recent_turns=2)
    assert stats.pruned_results == 0
    assert selected == messages


def test_recent_turn_start_boundaries():
    messages = _conversation()
    assert recent_turn_start(messages, 0) == len(messages)
    assert recent_turn_start(messages, 1) == 10
    assert recent_turn_start(messages, 5) == 0


def test_multimodal_content_is_measured():
    messages = [{"role": "user", "content": "q"}, _call("m"),
                {"role": "tool", "tool_call_id": "m", "content": [{"type": "text", "text": BIG}]},
                {"role": "user", "content": "q2"}, {"role": "user", "content": "q3"}]
    selected, stats = select_wire_messages(messages, keep_recent_turns=2, min_prune_chars=1200)
    assert stats.pruned_results == 1
    assert isinstance(selected[2]["content"], str)
