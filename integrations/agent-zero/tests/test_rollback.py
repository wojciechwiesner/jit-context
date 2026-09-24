import importlib.util
import os
import sqlite3

from tests import conftest  # noqa: F401

BASE = os.path.join(os.path.dirname(__file__), "..")
ADV_PATH = os.path.join(BASE, "extensions/python/message_loop_end/_20_eviction_advisor.py")


def _load():
    spec = importlib.util.spec_from_file_location("_20_eviction_advisor", ADV_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def compile_capsule(self):
        return "x" * 4000  # 1000 tok, over 0.9*1000


def test_rollback_switch_zero_writes(tmp_path, monkeypatch):
    conftest.DEFAULT_CFG.clear()
    conftest.DEFAULT_CFG.update({"jev_enabled": False})
    try:
        mod = _load()
        fake = FakeRuntime()
        monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
        db = str(tmp_path / "jev.db")
        monkeypatch.setattr(mod, "_jev_db_path", lambda: db)
        mod.EvictionAdvisorExtension(agent=object()).execute(loop_data={"history": []})
        assert not os.path.exists(db) or sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM jev_advice"
        ).fetchone()[0] == 0
    finally:
        conftest.DEFAULT_CFG.clear()
        conftest.DEFAULT_CFG.update({"jev_enabled": True})
