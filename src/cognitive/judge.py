"""Rozwaga (deliberation): the judge between independent answer attempts.

Placement in the cognitive stack:
- Podświadomość (intuition)   - fast pre-task extraction (LFM2)
- Nadświadomość (planning)    - strategy / in-loop control (LoopGuard)
- Sumienie (conscience)       - deterministic gate: grounding, format, budget (never rewrites)
- Rozwaga (deliberation)      - THIS: when Sumienie does not verify an answer, a second
                                independent attempt is made and Rozwaga picks between them.

Rules that keep Rozwaga inside Invariant I4 (no LLM token promotes a claim without proof):
1. Rozwaga never writes an answer. It returns an index into the candidates list; any
   output that is not a valid index falls back to a deterministic choice.
2. Deterministic preference first: agreeing candidates win without an LLM call; a
   VERIFIED candidate beats an UNVERIFIED one; the LLM is consulted only on a real tie.
3. The LLM sees only the question, the candidates and their tool-evidence excerpts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class Candidate:
    answer: str
    gate_decision: str
    gate_reason: str = ""
    evidence_excerpt: str = ""
    tools_count: int = 0


@dataclass
class Verdict:
    index: int
    method: str  # "agreement" | "gate_preference" | "llm" | "fallback"
    reason: str = ""
    raw: Optional[str] = field(default=None, repr=False)


def _norm(ans: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (ans or "").lower())


def build_judge_prompt(question: str, candidates: List[Candidate]) -> str:
    blocks = []
    for i, c in enumerate(candidates):
        blocks.append(
            f"CANDIDATE {i}: {c.answer}\n"
            f"  conscience gate: {c.gate_decision} ({c.gate_reason})\n"
            f"  evidence excerpt:\n{c.evidence_excerpt[-2500:]}"
        )
    return (
        "You are a strict judge. Two independent attempts answered the same question. "
        "Pick the candidate whose answer is best supported by its evidence and satisfies the "
        "exact format the question asks for. Do not propose a new answer.\n\n"
        f"QUESTION:\n{question}\n\n" + "\n\n".join(blocks) +
        "\n\nReply with exactly one line: CHOICE: <index> | <one-sentence reason>"
    )


def deliberate(
    question: str,
    candidates: List[Candidate],
    llm_fn: Optional[Callable[[str], str]] = None,
) -> Verdict:
    if not candidates:
        raise ValueError("deliberate() needs at least one candidate")
    if len(candidates) == 1:
        return Verdict(0, "fallback", "single candidate")

    nonempty = [i for i, c in enumerate(candidates) if _norm(c.answer)]
    if not nonempty:
        return Verdict(0, "fallback", "all candidates empty")
    if len(nonempty) == 1:
        return Verdict(nonempty[0], "gate_preference", "only non-empty candidate")

    norms = {_norm(candidates[i].answer) for i in nonempty}
    if len(norms) == 1:
        return Verdict(nonempty[0], "agreement", "independent attempts agree")

    verified = [i for i in nonempty if candidates[i].gate_decision == "VERIFIED"]
    if len(verified) == 1:
        return Verdict(verified[0], "gate_preference", "only candidate verified by Sumienie")

    if llm_fn is None:
        return Verdict(nonempty[0], "fallback", "no judge model configured")

    raw = llm_fn(build_judge_prompt(question, candidates)) or ""
    m = re.search(r"CHOICE:\s*(\d+)\s*(?:\|\s*(.*))?", raw)
    if m:
        idx = int(m.group(1))
        if idx in nonempty:
            return Verdict(idx, "llm", (m.group(2) or "").strip()[:300], raw)
    return Verdict(nonempty[0], "fallback", "judge output unparseable", raw)
