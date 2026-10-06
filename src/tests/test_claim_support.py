"""Regression tests: the conscience gate must not verify claims the evidence contradicts.

Reported publicly in langgenius/dify discussion #41966 (2026-10-05) against 8b6a119:
"retry the same UPDATE" was VERIFIED/GROUNDED_EXACT from evidence saying
"do not retry the same UPDATE", and "42" was VERIFIED/COMPUTED from "result: 17".
"""

from l0.claim_support import (
    CONTRADICTED_BY_NEGATION,
    NOT_IN_COMPUTED_OUTPUT,
    SUPPORTED,
    is_negated_in_evidence,
)
from l0.epistemics import evaluate_conscience_gate

SQLITE_EVIDENCE = [{
    "tool": "web_extract",
    "status": "SUCCESS",
    "output_preview": (
        "For SQLITE_BUSY_SNAPSHOT, do not retry the same UPDATE. "
        "Roll back and re-read before recomputing."
    ),
}]
SQLITE_QUESTION = "What should the agent do after SQLITE_BUSY_SNAPSHOT?"


def test_answer_negated_by_evidence_is_not_verified():
    gate = evaluate_conscience_gate("retry the same UPDATE", SQLITE_EVIDENCE, SQLITE_QUESTION)
    assert gate.decision == "UNVERIFIED"
    assert CONTRADICTED_BY_NEGATION in (gate.reason or "")


def test_answer_supported_by_evidence_stays_verified():
    gate = evaluate_conscience_gate(
        "Roll back and re-read before recomputing", SQLITE_EVIDENCE, SQLITE_QUESTION
    )
    assert gate.decision == "VERIFIED"
    assert gate.evidence_refs == ["GROUNDED_EXACT", SUPPORTED]


def test_answer_that_keeps_the_negation_stays_verified():
    gate = evaluate_conscience_gate("do not retry the same UPDATE", SQLITE_EVIDENCE, SQLITE_QUESTION)
    assert gate.decision == "VERIFIED"


def test_successful_python_run_does_not_verify_an_absent_value():
    events = [{"tool": "python_exec", "status": "SUCCESS", "output_preview": "result: 17"}]
    gate = evaluate_conscience_gate("42", events, "what is x?")
    assert gate.decision == "UNVERIFIED"
    assert NOT_IN_COMPUTED_OUTPUT in (gate.reason or "")


def test_value_present_in_python_output_stays_verified():
    events = [{"tool": "python_exec", "status": "SUCCESS", "output_preview": "result: 17"}]
    gate = evaluate_conscience_gate("17", events, "what is x?")
    assert gate.decision == "VERIFIED"


def test_negation_rule_needs_every_occurrence_negated():
    evidence = "do not retry the same update. if the lock is released, retry the same update."
    assert not is_negated_in_evidence("retry the same update", evidence)


def test_negation_far_before_the_span_is_ignored():
    assert not is_negated_in_evidence("paris", "the capital is not lyon but paris")


def test_numeric_answers_are_not_checked_for_negation():
    assert not is_negated_in_evidence("17", "not 17")
