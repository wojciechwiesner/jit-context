import importlib.util
import os

from tests import conftest  # noqa: F401

INIT_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/agent_init/_10_jev_init.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("_10_jev_init", INIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def __init__(self):
        self.reranker = None


def test_init_installs_reranker(monkeypatch):
    mod = _load()
    fake = FakeRuntime()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    mod.JevInitExtension(agent=object()).execute()
    assert callable(fake.fact_reranker)


def test_init_silent_without_runtime(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: None)
    mod.JevInitExtension(agent=object()).execute()  # must not raise


def test_init_installs_hybrid(monkeypatch):
    mod = _load()
    fake = FakeRuntime()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    mod.JevInitExtension(agent=object()).execute()
    assert callable(fake.fact_reranker)
    # hybrid path: no jev scores -> falls back to deterministic ordering
    from jev_bridge._10_shared import RECENT_QUERY
    RECENT_QUERY.update("nginx boocco")
    out = fake.fact_reranker([
        {"key": "a", "value": "groceries"},
        {"key": "b", "value": "boocco nginx conf"},
    ])
    assert out[0]["key"] == "b"
