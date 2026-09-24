"""Deterministic shadow-verdict judge (Slot 1). Pure, no I/O, no LLM.

Contract mirrors runtime.record_shadow_verdict: HELPFUL | NEUTRAL | HARMFUL.
The optional HTTP backend must emit the same three labels.
"""
from __future__ import annotations

import re
from typing import Dict, List

_TOKEN_RE = re.compile(r"[a-z0-9_:\-.]{3,}")
_STOP = {
    "the", "and", "for", "that", "this", "with", "you", "are", "not",
    "nie", "jest", "tak", "jak", "dla", "oraz", "przez", "ktore",
}
MIN_HELPFUL_RATIO = 0.25


def tokens(text: str) -> set:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP}


def fact_hit(fact: Dict[str, str], response_tokens: set) -> bool:
    ft = tokens(f"{fact.get('key', '')} {fact.get('value', '')}")
    if not ft:
        return False
    overlap = ft & response_tokens
    return len(overlap) >= max(1, int(round(0.5 * len(ft))))


def classify_turn(
    capsule_facts: List[Dict[str, str]],
    response_text: str,
    invariant_flags: int = 0,
) -> str:
    if invariant_flags:
        return "HARMFUL"
    if not capsule_facts:
        return "NEUTRAL"
    rt = tokens(response_text)
    hits = sum(1 for f in capsule_facts if fact_hit(f, rt))
    if hits / len(capsule_facts) >= MIN_HELPFUL_RATIO:
        return "HELPFUL"
    return "NEUTRAL"
