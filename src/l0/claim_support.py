"""Claim support: does the tool evidence actually back the answer?

Grounding (``answer_grounding``) only answers "is the answer text traceable to
tool output". That is not the same as "the evidence supports the claim":

- "retry the same UPDATE" occurs verbatim inside "do not retry the same UPDATE",
  so it is traceable, but the evidence says the opposite.
- A successful ``python_exec`` run proves a computation happened, not that the
  answer came out of it. Answer "42" with output "result: 17" is not supported.

This module keeps the two questions separate. The conscience gate only marks an
answer VERIFIED when it is both traceable and supported.

Known limits (deterministic heuristic, not semantic entailment): only negation
directly in front of the quoted span is detected, and only answers that occur
verbatim in the evidence are checked for it.
"""

import re
from typing import List

SUPPORTED = "SUPPORTED"
CONTRADICTED_BY_NEGATION = "CONTRADICTED_BY_NEGATION"
NOT_IN_COMPUTED_OUTPUT = "NOT_IN_COMPUTED_OUTPUT"

NEGATION_WORDS = {
    "not", "no", "never", "don't", "dont", "doesn't", "mustn't",
    "shouldn't", "cannot", "can't", "avoid", "without",
}
# How many words before the quoted span may carry a negation that flips it.
# Two covers "do not X", "should never X", "must not X" without catching
# "not Lyon but Paris" (three words back).
NEGATION_WINDOW_WORDS = 2


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_']+", text.lower())


def _has_negation(words: List[str]) -> bool:
    return any(w in NEGATION_WORDS for w in words)


def is_negated_in_evidence(answer: str, evidence: str) -> bool:
    """True when every occurrence of the answer in the evidence is negated.

    Both arguments must already be normalized the same way (see
    ``epistemics._norm_evidence``). An answer that carries its own negation
    ("do not retry ...") is never treated as contradicted by this rule.
    """
    if not answer or not re.search(r"[a-z]", answer):
        return False
    if _has_negation(_words(answer)):
        return False
    occurrences = [m.start() for m in re.finditer(re.escape(answer), evidence)]
    if not occurrences:
        return False
    for start in occurrences:
        preceding = _words(evidence[:start])[-NEGATION_WINDOW_WORDS:]
        if not _has_negation(preceding):
            return False
    return True


def claim_support(grounding: str, answer: str, evidence: str) -> str:
    """Classify whether traceable evidence supports the answer.

    ``grounding`` is the label from ``answer_grounding``; ``answer`` and
    ``evidence`` are normalized text. UNGROUNDED answers are left to the
    grounding check and reported here as SUPPORTED to avoid a double penalty.
    """
    if grounding == "COMPUTED":
        return NOT_IN_COMPUTED_OUTPUT
    if grounding == "GROUNDED_EXACT" and is_negated_in_evidence(answer, evidence):
        return CONTRADICTED_BY_NEGATION
    return SUPPORTED
