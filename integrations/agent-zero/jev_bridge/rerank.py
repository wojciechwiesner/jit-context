"""Slot 2: deterministic local relevance scorer for L2 vault facts."""
from __future__ import annotations

from typing import Dict, List

from jev_bridge.judge import tokens


class RecentQuery:
    """Holds the latest user query; updated post-turn by the judge extension."""

    def __init__(self) -> None:
        self.text: str = ""

    def update(self, text: str) -> None:
        self.text = (text or "")[:2000]


def _score(fact: Dict[str, str], q_tokens: set) -> float:
    ft = tokens(f"{fact.get('key', '')} {fact.get('value', '')}")
    if not ft or not q_tokens:
        return 0.0
    return len(ft & q_tokens) / len(ft)


def make_reranker(rq: RecentQuery):
    def rerank(candidates: List[Dict[str, str]]) -> List[Dict[str, str]]:
        qt = tokens(rq.text)
        if not qt:
            return list(candidates)
        # stable sort: ties keep file order -> deterministic, cache-friendly
        return sorted(candidates, key=lambda f: -_score(f, qt))

    return rerank
