"""Regression tests for JEV cache reuse across turns and Polish-aware tokenization."""

import time

from cognitive.jev_engine import JevDecisionScorer, fact_key, tokenize


def _cands(*values):
    return [{"key": fact_key(v), "value": v} for v in values]


def test_tokenize_folds_polish_diacritics_and_keeps_whole_words():
    a = tokenize("Czemu apka gubi połączenie po restarcie serwera?")
    b = tokenize("czemu apka gubi polaczenie po restarcie serwera")
    assert a == b
    assert "polaczenie" in a
    assert "serwera" in a
    # Old ASCII-only regex split 'połączenie' into fragments like 'czenie'.
    assert "czenie" not in a


def test_fact_key_is_content_addressed_and_stable():
    assert fact_key("SmartConvo reconnect backoff") == fact_key("SmartConvo reconnect backoff")
    assert fact_key("fact one") != fact_key("fact two")


def test_cache_hit_ignores_punctuation_and_word_order():
    scorer = JevDecisionScorer(api_key="sk-test", ttl_s=60)
    scorer._store_cache("czemu apka gubi polaczenie po restarcie serwera", {"k": 0.9})
    assert scorer.get_cached_scores("Czemu apka gubi połączenie po restarcie serwera?") == {"k": 0.9}
    assert scorer.get_cached_scores("po restarcie serwera czemu apka gubi polaczenie") == {"k": 0.9}


def test_fuzzy_cache_serves_follow_up_turn_on_same_topic():
    scorer = JevDecisionScorer(api_key="sk-test", ttl_s=60)
    scorer._store_cache("websocket reconnect backoff smartconvo app", {"k": 0.8})
    # Follow-up shares 4 of 6 tokens (Jaccard 0.67) -> reuse.
    assert scorer.get_cached_scores("websocket reconnect backoff smartconvo server") == {"k": 0.8}
    # Unrelated query -> no reuse.
    assert scorer.get_cached_scores("luna salon palette colors") is None


def test_fuzzy_cache_prefers_most_similar_then_freshest():
    scorer = JevDecisionScorer(api_key="sk-test", ttl_s=60)
    scorer._store_cache("alpha beta gamma delta", {"k": 0.1})
    scorer._store_cache("alpha beta gamma epsilon", {"k": 0.2})
    assert scorer.get_cached_scores("alpha beta gamma epsilon zeta") == {"k": 0.2}


def test_expired_entries_are_not_reused():
    scorer = JevDecisionScorer(api_key="sk-test", ttl_s=0.01)
    scorer._store_cache("websocket reconnect backoff", {"k": 0.8})
    time.sleep(0.03)
    assert scorer.get_cached_scores("websocket reconnect backoff") is None
    assert scorer._cache == {}


def test_previous_turn_scores_rerank_next_turn_with_content_keys():
    """Turn N prefetch result must reorder turn N+1 even when the fact list order changes."""
    scorer = JevDecisionScorer(api_key="sk-test", ttl_s=60)
    relevant = "SmartConvo client reconnects the socket with exponential backoff"
    noise = "Luna salon palette is FAF7F5 and 8A2B47"
    turn_n = _cands(noise, relevant)
    scorer._store_cache(
        "czemu apka gubi polaczenie po restarcie serwera",
        {turn_n[0]["key"]: 0.02, turn_n[1]["key"]: 0.91},
    )
    turn_n1 = _cands(relevant, "borg runs cliproxyapi on 8317", noise)
    ranked = scorer.rerank_hybrid("apka dalej gubi polaczenie po restarcie serwera", turn_n1)
    assert ranked[0]["value"] == relevant
    assert len(ranked) == 3
