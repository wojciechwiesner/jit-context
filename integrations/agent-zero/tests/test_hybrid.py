from jev_bridge.hybrid import make_hybrid_reranker
from jev_bridge.rerank import RecentQuery


class FixedScorer:
    def __init__(self, scores):
        self.scores = scores

    def cached_scores(self, q):
        return dict(self.scores)


class BoomScorer:
    def cached_scores(self, q):
        raise RuntimeError("boom")


def test_jev_scores_win():
    rq = RecentQuery(); rq.update("nginx boocco")
    rr = make_hybrid_reranker(rq, lambda: FixedScorer({"b": 0.9}))
    out = rr([{"key": "a", "value": "boocco nginx config"}, {"key": "b", "value": "unrelated words"}])
    assert out[0]["key"] == "b"


def test_lazy_getter_raises_silent_fallback():
    rq = RecentQuery(); rq.update("nginx")
    rr = make_hybrid_reranker(rq, lambda: (_ for _ in ()).throw(RuntimeError("cfg")))
    out = rr([{"key": "a", "value": "nginx setup"}, {"key": "b", "value": "recipes"}])
    assert out[0]["key"] == "a"


def test_new_fact_tiebreak_by_tokens():
    rq = RecentQuery(); rq.update("nginx boocco")
    rr = make_hybrid_reranker(rq, lambda: FixedScorer({}))
    out = rr([{"key": "x", "value": "groceries apples"}, {"key": "y", "value": "boocco nginx conf"}])
    assert out[0]["key"] == "y"


def test_fallback_on_scorer_crash_keeps_order_deterministic():
    rq = RecentQuery(); rq.update("nginx")
    rr = make_hybrid_reranker(rq, lambda: BoomScorer())
    cands = [{"key": str(i), "value": f"fact {i}"} for i in range(5)]
    out = rr(list(cands))
    assert [c["key"] for c in out] == [str(i) for i in range(5)]  # no qt hits -> stable


def test_none_scorer_behaves_like_deterministic():
    rq = RecentQuery(); rq.update("nginx")
    rr = make_hybrid_reranker(rq, lambda: None)
    out = rr([{"key": "a", "value": "nginx setup"}, {"key": "b", "value": "recipes"}])
    assert out[0]["key"] == "a"


def test_plain_scorer_object_still_supported():
    rq = RecentQuery(); rq.update("nginx boocco")
    rr = make_hybrid_reranker(rq, FixedScorer({"z": 0.8}))
    out = rr([{"key": "a", "value": "boocco nginx"}, {"key": "z", "value": "zzz"}])
    assert out[0]["key"] == "z"
