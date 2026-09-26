"""Unit tests for the deterministic tool-loop guard (cognitive/loop_guard.py)."""

from cognitive.loop_guard import CONTINUE, FORCE_ANSWER, NUDGE, LoopGuard


def test_exact_repeat_is_detected_with_normalized_args():
    g = LoopGuard(max_turns=15)
    assert g.classify_call("web_search", {"query": "Mercedes Sosa albums"}) is None
    assert g.classify_call("web_search", {"query": "mercedes  sosa albums"}) == "exact_repeat"
    assert g.classify_call("python_exec", {"code": "print(1)"}) is None


def test_near_repeat_search_is_detected():
    g = LoopGuard(max_turns=15)
    assert g.classify_call("web_search", {"query": "Girls Who Code women computer scientists 37%"}) is None
    assert g.classify_call("web_search", {"query": "Girls Who Code women computer scientists 37% 24%"}) == "near_repeat"
    assert g.classify_call("web_search", {"query": "Scikit-Learn July 2017 changelog"}) is None


def test_stall_nudges_then_forces_answer():
    g = LoopGuard(max_turns=30, stall_window=3, max_nudges=1)
    g.observe_output(1, "web_search", "alpha beta gamma delta epsilon")
    assert g.after_turn(1).action == CONTINUE
    verdicts = []
    for turn in range(2, 8):
        g.observe_output(turn, "web_search", "alpha beta gamma delta epsilon")  # zero novelty
        verdicts.append(g.after_turn(turn).action)
    assert verdicts[2] == NUDGE          # 3rd no-progress call -> first nudge
    assert FORCE_ANSWER in verdicts[3:]  # stalls again after the nudge budget -> force
    assert g.nudges >= 2


def test_novel_output_resets_stall_streak():
    g = LoopGuard(max_turns=30, stall_window=3)
    for turn in range(1, 10):
        g.observe_output(turn, "web_extract", f"unique page {turn} token{turn}a token{turn}b token{turn}c")
        assert g.after_turn(turn).action == CONTINUE


def test_budget_warning_and_forced_answer_on_reserved_turn():
    g = LoopGuard(max_turns=8, answer_reserve=1)
    assert g.last_tool_turn() == 7
    actions = {}
    for turn in range(1, 8):
        g.observe_output(turn, "python_exec", f"result {turn} value{turn} extra{turn}")
        actions[turn] = g.after_turn(turn)
    assert actions[5].action == NUDGE and actions[5].reason == "budget_warning"
    assert actions[7].action == FORCE_ANSWER and actions[7].reason == "budget_exhausted"
