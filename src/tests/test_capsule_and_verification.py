"""Tests for the capsule/verification changes of 2026-09-26.

goal_anchor (verbatim extract), PRIOR filtering, Sumienie evidence checks, Rozwaga judge,
tool-routing telemetry.
"""

import json

from cognitive.judge import Candidate, deliberate
from context.compiler import _prior_user_statements
from context.goal_anchor import build_goal_anchor
from hooks import _response_tool_names, is_synthetic_harness_message
from l0.epistemics import answer_grounding, check_answer_format, evaluate_conscience_gate
from telemetry.collector import (
    record_tool_recommendation,
    record_tool_use,
    tool_routing_report,
)
from telemetry.db_schema import init_telemetry_schema


# --- goal anchor -------------------------------------------------------------------------

def _is_verbatim_extract(anchor: str, source: str) -> bool:
    return all(piece.strip() in source for piece in anchor.split(" … ") if piece.strip())


def test_short_message_is_verbatim():
    a = build_goal_anchor("Napraw test logowania.")
    assert a.is_verbatim_full and a.text == "Napraw test logowania."


def test_long_message_respects_limit_and_is_verbatim():
    msg = ("Kontekst projektu, długi opis bez polecenia. " * 20) + "Zacommituj zmiany i popraw README."
    a = build_goal_anchor(msg, limit=300)
    assert len(a.text) <= 300
    assert _is_verbatim_extract(a.text, msg)
    assert "Zacommituj zmiany i popraw README." in a.text
    assert "full message" in a.render()


def test_pasted_transcript_does_not_hijack_the_goal():
    paste = "[10:01] Klaudia: prosze wyslij fakture\n[10:02] Klaudia: i zadzwon jutro\n" * 12
    msg = paste + "Podsumuj tę rozmowę i przygotuj mi szkic odpowiedzi do Klaudii."
    a = build_goal_anchor(msg)
    assert a.text == "Podsumuj tę rozmowę i przygotuj mi szkic odpowiedzi do Klaudii."


def test_negation_is_kept_with_the_actual_task():
    msg = ("Kontekst: mamy serwis X z 40 plikami i sporo legacy kodu w module auth. " * 4
           + "Nie refaktoruj modułu auth. Tylko napraw test test_login w tests/test_auth.py.")
    a = build_goal_anchor(msg)
    assert "Nie refaktoruj modułu auth." in a.text
    assert "Tylko napraw test test_login" in a.text


def test_pure_transcript_uses_header_and_recent_lines():
    msg = "Historia rozmowy (najstarsze u góry):\n" + "".join(
        f"[2026-09-2{i % 10}T10:0{i % 10}:00Z] Ala: wiadomosc numer {i}\n" for i in range(60)
    )
    a = build_goal_anchor(msg)
    assert a.text.startswith("Historia rozmowy")
    assert "wiadomosc numer 59" in a.text
    assert len(a.text) <= 300


# --- PRIOR filtering ---------------------------------------------------------------------

def test_prior_excludes_current_turn_and_notifications():
    overlays = [
        {"kind": "statement", "value": "zrob X oraz Y"},
        {"kind": "statement", "value": "[IMPORTANT: Background process proc_1 completed normally (exit code 0)."},
        {"kind": "statement", "value": "starsze polecenie: popraw testy"},
        {"kind": "verified_fact", "value": "fact"},
    ]
    prior = _prior_user_statements(overlays, "zrob X oraz Y")
    assert prior == ["starsze polecenie: popraw testy"]


def test_synthetic_filter_covers_host_notifications():
    assert is_synthetic_harness_message("[IMPORTANT: Background process proc_x completed normally")
    assert is_synthetic_harness_message("<system-reminder>ctx</system-reminder>")
    assert not is_synthetic_harness_message("Napraw bramkę sumienie")


# --- Sumienie (conscience gate) ----------------------------------------------------------

def _ev(text, tool="web_extract", status="SUCCESS"):
    return {"tool": tool, "output_preview": text, "status": status}


def test_gate_verifies_grounded_answer():
    g = evaluate_conscience_gate("Paris", [_ev("The capital of France is Paris.")], "What is the capital of France?")
    assert g.decision == "VERIFIED" and "GROUNDED_EXACT" in g.reason


def test_gate_flags_ungrounded_answer():
    g = evaluate_conscience_gate("Lyon", [_ev("The capital of France is Paris.")], "What is the capital of France?")
    assert g.decision == "UNVERIFIED" and "UNGROUNDED" in g.reason


def test_gate_flags_forced_answer():
    events = [_ev("Paris is the capital."), {"tool": "loop_guard", "status": "FORCED_ANSWER"}]
    g = evaluate_conscience_gate("Paris", events, "What is the capital of France?")
    assert g.decision == "UNVERIFIED" and "FORCED_BY_BUDGET" in g.reason


def test_gate_normalizes_requested_whitespace_losslessly():
    g = evaluate_conscience_gate("1/2, 3/4", [_ev("values 1/2 and 3/4")],
                                 "As a comma separated list with no whitespace, give the fractions.")
    assert g.verified_answer == "1/2,3/4"


def test_format_checks():
    assert "NOT_ALPHABETICAL" in check_answer_format("Quincy, Honolulu", "list in alphabetical order, comma separated")
    assert "EXPECTED_NUMBER" in check_answer_format("many", "How many albums were released?")
    assert check_answer_format("3", "How many albums were released?") == []


def test_grounding_computed_via_python():
    events = [{"tool": "python_exec", "output_preview": "result: 17", "status": "SUCCESS"}]
    assert answer_grounding("17", events) == "GROUNDED_EXACT"
    assert answer_grounding("42", events) == "COMPUTED"


# --- Rozwaga (judge) ---------------------------------------------------------------------

def test_judge_agreement_needs_no_llm():
    called = []
    v = deliberate("q", [Candidate("Paris", "UNVERIFIED"), Candidate("paris", "UNVERIFIED")],
                   llm_fn=lambda p: called.append(p) or "CHOICE: 1")
    assert v.index == 0 and v.method == "agreement" and not called


def test_judge_prefers_verified_candidate():
    v = deliberate("q", [Candidate("A", "UNVERIFIED"), Candidate("B", "VERIFIED")])
    assert v.index == 1 and v.method == "gate_preference"


def test_judge_llm_can_only_pick_an_index():
    v = deliberate("q", [Candidate("A", "UNVERIFIED"), Candidate("B", "UNVERIFIED")],
                   llm_fn=lambda p: "CHOICE: 1 | better evidence")
    assert v.index == 1 and v.method == "llm"
    v2 = deliberate("q", [Candidate("A", "UNVERIFIED"), Candidate("B", "UNVERIFIED")],
                    llm_fn=lambda p: "The answer is actually C")
    assert v2.index == 0 and v2.method == "fallback"


# --- tool routing telemetry --------------------------------------------------------------

def test_tool_routing_recommended_vs_used(test_db):
    init_telemetry_schema(test_db)
    record_tool_recommendation(test_db, "s1", "t1", ["terminal:curl_wa", "read_file"], ["whatsapp"])
    record_tool_use(test_db, "s1", "t1", "terminal")
    record_tool_use(test_db, "s1", "t1", "terminal")
    record_tool_use(test_db, "s1", "t1", "web_search")
    row = test_db.execute("SELECT used_json, used_calls FROM tool_routing WHERE turn_id='t1'").fetchone()
    assert json.loads(row[0]) == ["terminal", "web_search"] and row[1] == 3
    rep = tool_routing_report(test_db)
    assert rep["precision"] == 0.5 and rep["recall"] == 0.5


def test_response_tool_names_from_hermes_payload():
    class Fn:
        def __init__(self, name):
            self.name = name

    class Call:
        def __init__(self, name):
            self.function = Fn(name)

    class Msg:
        tool_calls = [Call("terminal"), Call("read_file")]

    assert _response_tool_names({"assistant_message": Msg()}) == ["terminal", "read_file"]
    assert _response_tool_names({"assistant_message": {"tool_calls": [{"function": {"name": "patch"}}]}}) == ["patch"]
