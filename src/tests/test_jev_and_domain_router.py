"""Unit tests for JEV Decision Engine, Domain Router, and False-Positive Invariant Elimination."""

import pytest
import time
from pathlib import Path

from cognitive.jev_engine import (
    JevDecisionScorer,
    CircuitBreaker,
    tokenize,
    token_overlap_score,
    get_jev_scorer,
)
from context.domain_router import resolve_domain_routing
from context.compiler import compile_context
from context.cascade_distiller import distill_context_cascade
from l0.overlay import ensure_session


# --- JEV Engine Tests ---

def test_tokenize_and_overlap():
    tokens = tokenize("Wojciech koduje silnik drzew decyzyjnych w Pythonie")
    assert "wojciech" in tokens
    assert "drzew" in tokens
    assert "nie" not in tokens  # Stopword removed

    q_tokens = tokenize("silnik drzew decyzyjnych i probabilistyka")
    score = token_overlap_score("silnik drzew decyzyjnych", q_tokens)
    assert score > 0.0


def test_circuit_breaker():
    cb = CircuitBreaker(failure_threshold=2, cooldown_s=1.0)
    assert cb.allow_request() is True

    cb.record_failure(is_fatal_auth=False)
    assert cb.allow_request() is True

    cb.record_failure(is_fatal_auth=False)
    assert cb.allow_request() is False  # Tripped

    # Fatal auth should disable permanently
    cb2 = CircuitBreaker()
    cb2.record_failure(is_fatal_auth=True)
    assert cb2.allow_request() is False
    assert cb2.disabled_permanently is True


def test_jev_scorer_cache_and_hybrid_rerank():
    scorer = JevDecisionScorer(api_key="test_dummy_key", ttl_s=60.0)

    # Cache should be initially empty
    assert scorer.get_cached_scores("test query") is None

    # Store fake scores
    scorer._store_cache("test query", {"f1": 0.95, "f2": 0.20})
    cached = scorer.get_cached_scores("test query")
    assert cached == {"f1": 0.95, "f2": 0.20}

    # Hybrid reranking: f1 should rank above f2 based on JEV score
    candidates = [
        {"key": "f2", "value": "some unimportant note"},
        {"key": "f1", "value": "critical decision tree node"},
    ]
    reranked = scorer.rerank_hybrid("test query", candidates)
    assert reranked[0]["key"] == "f1"
    assert reranked[1]["key"] == "f2"


def test_jev_scorer_fail_open_invariant_i6():
    """Invariant I6: If JEV is offline / has no key, reranking falls back to deterministic tokens with 0 drops."""
    scorer = JevDecisionScorer(api_key="")
    candidates = [
        {"key": "a", "value": "apple fruit"},
        {"key": "b", "value": "decision tree engine"},
        {"key": "c", "value": "banana yellow"},
    ]
    # Query matching 'decision' should rank 'b' first without errors
    reranked = scorer.rerank_hybrid("decision engine", candidates)
    assert len(reranked) == 3
    assert reranked[0]["key"] == "b"


def test_jev_score_remote_noul_parsing(monkeypatch):
    """Verify that OpenRouter alpha decisions response with 'noul' is correctly parsed."""
    scorer = JevDecisionScorer(api_key="sk-test-key")

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def read(self):
            import json
            return json.dumps(self.data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeResponse({
            "model": "typesafe/jev-1.13-20260917",
            "answers": {
                "q_0": {"type": "noul", "noul": 0.88},
                "q_1": {"type": "noul", "noul": 0.12},
            }
        })

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    candidates = [
        {"key": "fact_a", "value": "first"},
        {"key": "fact_b", "value": "second"},
    ]
    scores = scorer.score_remote("test query", candidates)
    assert scores["fact_a"] == 0.88
    assert scores["fact_b"] == 0.12


def test_jev_does_not_truncate_candidate_value(monkeypatch):
    """The client must send the full fact and the full query."""
    scorer = JevDecisionScorer(api_key="sk-test-key")
    marker = "NEEDLE-" + ("x" * 400)
    query = "where is the needle " + ("q" * 400)
    captured = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"answers": {"q_0": {"noul": 0.5}}}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    import json
    import urllib.request

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    scorer.score_remote(query, [{"key": "target.py", "value": marker}])
    body = captured["body"]
    instructions = body["questions"]["q_0"]["instructions"]
    assert marker in instructions
    assert query in instructions
    assert body["state"]["query"] == query

    captured.clear()
    scorer.score_remote_detailed(query, [{"key": "target.py", "value": marker}])
    body = captured["body"]
    instructions = body["questions"]["q_0"]["instructions"]
    assert marker in instructions
    assert query in instructions
    assert body["state"]["query"] == query


# --- Domain Router Tests ---

def test_domain_router_whatsapp():
    routing = resolve_domain_routing("zobacz dzisiejsza rozmowe z dominikiem udriver")
    assert "whatsapp" in routing["detected_domains"]
    assert any("@source:whatsapp:" in s for s in routing["domain_sources"])
    assert any("Suprawhat" in h for h in routing["action_hints"])


def test_domain_router_observatory_and_session():
    routing = resolve_domain_routing("zobacz ostatnia sesje i sprawdz stan")
    assert "session_meta" in routing["detected_domains"]
    assert any("@endpoint:observatory:" in s for s in routing["domain_sources"])
    assert any("@source:state_db:" in s for s in routing["domain_sources"])


def test_domain_router_multimedia():
    routing = resolve_domain_routing("wyciągnij z tych wideo tekst i ramki ze screenshotów")
    assert "multimedia" in routing["detected_domains"]
    assert "vision_analyze" in routing["recommended_tools"]
    assert any("ffmpeg" in h for h in routing["action_hints"])


def test_domain_router_decision_engine():
    routing = resolve_domain_routing("zbuduj silnik bazujący na modelu drzew decyzyjnych i jev")
    assert "decision_engine" in routing["detected_domains"]
    assert any("jev_decision" in s for s in routing["domain_sources"])


# --- False-Positive Invariant Elimination Tests ---

def test_compiler_no_false_positive_auth_on_chat_session(test_db):
    session_id = "s_no_false_auth"
    ensure_session(test_db, session_id)
    capsule = compile_context(
        test_db,
        session_id,
        "zobacz ostatnia sesje i popatrz na zawartosc kapuly vs prompt vs zadanie"
    )
    # MUST NOT contain Auth Graph invariant!
    assert "CASCADE INVARIANT (Auth Graph)" not in capsule
    # MUST contain domain routing pointers for session/observatory
    assert "@endpoint:observatory:" in capsule


def test_compiler_no_false_positive_schema_on_decision_model(test_db):
    session_id = "s_no_false_schema"
    ensure_session(test_db, session_id)
    capsule = compile_context(
        test_db,
        session_id,
        "zbuduj silnik bazujący na modelu drzew decyzyjnych"
    )
    # MUST NOT contain Schema Cascade invariant!
    assert "CASCADE INVARIANT (Schema Cascade)" not in capsule


def test_compiler_true_positive_auth_trigger(test_db):
    session_id = "s_true_auth"
    ensure_session(test_db, session_id)
    capsule = compile_context(
        test_db,
        session_id,
        "użytkownik został wylogowany, sprawdź token sesji jwt"
    )
    # MUST contain Auth Graph invariant when real auth is involved
    assert "CASCADE INVARIANT (Auth Graph)" in capsule


def test_compiler_true_positive_schema_trigger(test_db):
    session_id = "s_true_schema"
    ensure_session(test_db, session_id)
    capsule = compile_context(
        test_db,
        session_id,
        "dodaj migracje alembic i nowa kolumne do tabeli faktur"
    )
    # MUST contain Schema Cascade invariant when database migration is involved
    assert "CASCADE INVARIANT (Schema Cascade)" in capsule


# --- Calibrated Complexity in Cascade Distiller ---

def test_cascade_distiller_calibrated_complexity():
    # S1 prompt: deep exploration + building engine -> should be 'feature'
    res_s1 = distill_context_cascade(
        raw_statements=[
            "zobacz dzisiejsza rozmowe z dominikiem udriver. Weź przeanalizuj wideo i zbuduj silnik drzew decyzyjnych."
        ],
        active_scope="general",
        epoch=1,
    )
    assert res_s1["complexity"] == "feature"

    # Status query -> should be 'status'
    res_query = distill_context_cascade(
        raw_statements=["jaki jest stan projektu i ostatni commit?"],
        active_scope="general",
        epoch=1,
    )
    assert res_query["complexity"] == "status"

    # Simple 1-line direct fix -> should be 'direct_fix'
    res_fix = distill_context_cascade(
        raw_statements=["popraw literówkę w README"],
        active_scope="general",
        epoch=1,
    )
    assert res_fix["complexity"] == "direct_fix"


def test_compiler_observatory_url_capsule_inspection(test_db):
    session_id = "s_obs_url_inspection"
    ensure_session(test_db, session_id)
    url_prompt = "http://127.0.0.1:8765/live?session=20260923_022152_5f9234 czy ta kapsula jest adekwatna?"
    capsule = compile_context(
        test_db,
        session_id,
        url_prompt,
        active_scope="hermes-jit-context-os"
    )
    # 1. MUST NOT trigger false-positive Auth Graph invariant on Observatory URL with session=
    assert "CASCADE INVARIANT (Auth Graph)" not in capsule
    # 2. MUST route Observatory pointers
    assert "@endpoint:observatory:" in capsule
    assert "src/telemetry/observatory.py" in capsule
    # 3. MUST distill project context without redundant invariants or profiler footer
    assert "## Safety Invariants & Engineering Rules" not in capsule
    assert "*Generated by Hermes JIT Context OS Profiler" not in capsule
