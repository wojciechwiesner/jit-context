"""Hybrid reranker: Jev remote scores when fresh, else deterministic tokens.
Same contract as rerank.make_reranker: pure reorder, never raises, never drops.
scorer_getter: zero-arg callable returning a scorer or None (resolved lazily
so config/key changes after agent_init still take effect).
"""
from __future__ import annotations

from typing import Dict, List

from jev_bridge.rerank import RecentQuery, _score, tokens


def make_hybrid_reranker(rq: RecentQuery, scorer_getter):
    def _scorer():
        try:
            return scorer_getter() if callable(scorer_getter) else scorer_getter
        except Exception:
            return None  # I6

    def rerank(candidates: List[Dict[str, str]]) -> List[Dict[str, str]]:
        scores: Dict[str, float] = {}
        try:
            s = _scorer()
            if s is not None:
                scores = s.cached_scores(rq.text) or {}
        except Exception:
            scores = {}
        qt = tokens(rq.text)
        if scores:
            # Jev p desc; facts unknown to Jev (new since prefetch) tiebreak via tokens
            return sorted(
                candidates,
                key=lambda f: (-scores.get(str(f.get("key", "")), 0.0), -_score(f, qt)),
            )
        if not qt:
            return list(candidates)
        return sorted(candidates, key=lambda f: -_score(f, qt))

    return rerank
