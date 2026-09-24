from jev_bridge.rerank import RecentQuery, make_reranker


def test_relevance_beats_file_order():
    rq = RecentQuery()
    rq.update("how to configure nginx deploy for boocco")
    rr = make_reranker(rq)
    cands = [
        {"key": "a", "value": "user prefers dark theme in editors"},
        {"key": "b", "value": "boocco nginx config lives in /etc/nginx/boocco.conf"},
        {"key": "c", "value": "weekend grocery list apples"},
    ]
    out = rr(cands)
    assert out[0]["key"] == "b"


def test_deterministic_and_stable():
    rq = RecentQuery()
    rq.update("nginx")
    rr = make_reranker(rq)
    cands = [{"key": str(i), "value": f"neutral fact {i}"} for i in range(10)]
    assert [f["key"] for f in rr(cands)] == [f["key"] for f in rr(list(cands))]


def test_empty_query_keeps_order():
    rr = make_reranker(RecentQuery())
    cands = [{"key": "x", "value": "anything at all"}]
    assert rr(cands)[0]["key"] == "x"
