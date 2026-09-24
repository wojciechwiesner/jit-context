import importlib.util
import os

from tests import conftest  # noqa: F401

PREFETCH_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/message_loop_start/_05_jev_prefetch.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("_05_jev_prefetch", PREFETCH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def get_hot_facts(self):
        return [{"key": "a", "value": "boocco nginx"}]


class FakeScorer:
    def __init__(self):
        self.prefetched = None

    def prefetch_async(self, q, facts):
        self.prefetched = (q, facts)
        return True


class FakeLoopData:
    """Mirrors agent.py contract: loop_data=LoopData(user_message=...)."""

    def __init__(self, content=None):
        self.user_message = {"content": content} if content is not None else {}
        self.history_output = []


def test_prefetch_fires_async(monkeypatch):
    mod = _load()
    fake_scorer = FakeScorer()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: FakeRuntime()))
    monkeypatch.setattr(
        "jev_bridge.jev_remote.get_shared_scorer", lambda cfg: fake_scorer,
        raising=False,
    )
    mod.JevPrefetchExtension(agent=object()).execute(
        loop_data=FakeLoopData("jak skonfigurowac nginx dla boocco?")
    )
    assert fake_scorer.prefetched is not None
    q, facts = fake_scorer.prefetched
    assert "nginx" in q and facts[0]["key"] == "a"


def test_prefetch_query_from_history_fallback(monkeypatch):
    mod = _load()
    fake_scorer = FakeScorer()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: FakeRuntime()))
    monkeypatch.setattr(
        "jev_bridge.jev_remote.get_shared_scorer", lambda cfg: fake_scorer,
        raising=False,
    )
    ld = FakeLoopData(None)
    ld.history_output = [{"ai": False, "content": "history fallback query"}]
    mod.JevPrefetchExtension(agent=object()).execute(loop_data=ld)
    assert fake_scorer.prefetched is not None


def test_prefetch_silent_when_no_scorer(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: FakeRuntime()))
    monkeypatch.setattr(
        "jev_bridge.jev_remote.get_shared_scorer", lambda cfg: None, raising=False
    )
    mod.JevPrefetchExtension(agent=object()).execute(
        loop_data=FakeLoopData("anything")
    )  # must not raise


def test_prefetch_noop_on_empty_query(monkeypatch):
    mod = _load()
    ext = mod.JevPrefetchExtension(agent=object())
    ext.execute(loop_data=FakeLoopData(None))  # empty user_message + empty history
