import json
import time
import urllib.request

from jev_bridge.jev_remote import JevRemoteScorer, resolve_key


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _scorer(**kw):
    return JevRemoteScorer(api_key="sk-test", now_fn=lambda: 1000.0, **kw)


def test_score_parses_noul_and_caches(monkeypatch):
    def fake_urlopen(req, timeout=None):
        assert b"~typesafe/jev-latest" in req.data
        return FakeResp({"model": "m", "answers": {
            "q0": {"type": "noul", "noul": 0.9},
            "q1": {"type": "noul", "noul": 0.1},
        }})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    s = _scorer()
    out = s.score("query", [{"key": "k0", "value": "v0"}, {"key": "k1", "value": "v1"}])
    assert out == {"k0": 0.9, "k1": 0.1}
    assert s.cached_scores("query") == {"k0": 0.9, "k1": 0.1}


def test_score_clamps_and_skips_bad(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"answers": {"q0": {"noul": 1.7}, "q1": {"noul": "x"}, "q2": {"noul": -0.3}}}))
    s = _scorer()
    out = s.score("q", [{"key": "a", "value": ""}, {"key": "b", "value": ""}, {"key": "c", "value": ""}])
    assert out == {"a": 1.0, "c": 0.0}


def test_ttl_expiry():
    t = {"now": 1000.0}
    s = JevRemoteScorer(api_key="k", now_fn=lambda: t["now"])
    s._store("q", {"a": 1.0})
    assert s.cached_scores("q") == {"a": 1.0}
    t["now"] += 301
    assert s.cached_scores("q") == {}


def test_failure_opens_breaker_after_3(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    s = _scorer()
    facts = [{"key": "a", "value": "v"}]
    assert s.score("q1", facts) == {}
    assert s.score("q2", facts) == {}
    assert s.score("q3", facts) == {}
    # breaker open: immediate empty even if endpoint works now
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"answers": {"q0": {"noul": 0.9}}}))
    assert s.score("q4", facts) == {}


def test_no_key_or_input_returns_empty():
    assert JevRemoteScorer(api_key="").score("q", [{"key": "a", "value": "v"}]) == {}
    s = _scorer()
    assert s.score("", [{"key": "a", "value": "v"}]) == {}
    assert s.score("q", []) == {}


def test_resolve_key_env_priority(monkeypatch, tmp_path):
    from jev_bridge import jev_remote
    monkeypatch.setattr(jev_remote, "_plugin_root", lambda: str(tmp_path))
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "env-key")
    assert resolve_key({}) == "env-key"
    assert resolve_key({"jev_openrouter_key": "cfg-key"}) == "cfg-key"
    monkeypatch.delenv("JEV_OPENROUTER_KEY")
    assert resolve_key({}) == ""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "jev_openrouter_key.txt").write_text("file-key")
    assert resolve_key({}) == "file-key"


def test_403_disables_scorer(monkeypatch):
    import urllib.error

    def forbidden(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "limit", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    s = _scorer()
    facts = [{"key": "a", "value": "v"}]
    assert s.score("q1", facts) == {}
    assert s.api_key == ""  # disabled for process
    # further calls short-circuit, no HTTP
    assert s.score("q2", facts) == {}


def test_500_does_not_disable(monkeypatch):
    import urllib.error

    def server_error(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", server_error)
    s = _scorer()
    facts = [{"key": "a", "value": "v"}]
    s.score("q1", facts)
    assert s.api_key == "sk-test"  # transient -> key kept, breaker handles
