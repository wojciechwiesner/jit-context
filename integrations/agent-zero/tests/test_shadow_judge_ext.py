import importlib.util
import os

from tests import conftest  # noqa: F401  (stubs framework)

EXT_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/message_loop_end/_10_shadow_judge.py",
)


def _load_ext():
    spec = importlib.util.spec_from_file_location("_10_shadow_judge", EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def __init__(self):
        self.verdicts = []
        self.hot = [{"key": "phase_6_module", "value": "audit_exporter.py"}]

    def get_hot_facts(self):
        return self.hot

    def record_shadow_verdict(self, v):
        self.verdicts.append(v)


def _history():
    return [
        {"ai": False, "content": "co robisz"},
        {"ai": True, "content": "audit_exporter.py got telemetry export"},
    ]


class _Ctx:
    id = "live-session-1"


class _Agent:
    context = _Ctx()


class LiveLoopData:
    """Replicates the live LoopData object from agent.py (attributes, not dict)."""

    def __init__(self):
        self.user_message = None
        self.history_output = [
            {"ai": False, "content": "jak sprawdzic czy jev dziala"},
            {"ai": True, "content": "probe iteration output"},
            {"ai": False, "content": {"tool_name": "x"}},  # tool result, not a user prompt
            {"ai": True, "content": "audit_exporter.py got telemetry export; shadow verdicts recorded"},
        ]
        self.last_response = "audit_exporter.py got telemetry export"


def test_judge_records_helpful_dict(monkeypatch):
    mod = _load_ext()
    fake = FakeRuntime()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    ext = mod.ShadowJudgeExtension(agent=_Agent())
    ext.execute(loop_data={"history": _history()})
    assert fake.verdicts == ["HELPFUL"]


def test_judge_records_live_object_loopdata(monkeypatch):
    """Contract with the live framework: loop_data is an OBJECT
    (user_message / history_output attrs), session from agent.context.id.
    This was the root cause of 0 verdicts on live traffic in v0.1.0."""
    mod = _load_ext()
    fake = FakeRuntime()
    captured = {}
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    monkeypatch.setattr(
        mod,
        "distill_new_rows",
        lambda rt, db, session_id, since_ts, cap=3: captured.setdefault("sid", session_id) or 1,
    )
    ext = mod.ShadowJudgeExtension(agent=_Agent())
    ext.execute(loop_data=LiveLoopData())
    assert fake.verdicts == ["HELPFUL"], "live LoopData object must produce a verdict"
    assert captured.get("sid") == "live-session-1"


def test_skips_when_no_ai_response_live_object(monkeypatch):
    mod = _load_ext()
    fake = FakeRuntime()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    ld = LiveLoopData()
    ld.history_output = [{"ai": False, "content": "pytanie"}]
    mod.ShadowJudgeExtension(agent=_Agent()).execute(loop_data=ld)
    assert fake.verdicts == []


def test_disabled_writes_nothing(monkeypatch):
    conftest.DEFAULT_CFG["jev_enabled"] = False
    try:
        mod = _load_ext()
        fake = FakeRuntime()
        monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
        mod.ShadowJudgeExtension(agent=_Agent()).execute(loop_data={"history": _history()})
        assert fake.verdicts == []
    finally:
        conftest.DEFAULT_CFG["jev_enabled"] = True


def test_silent_when_runtime_missing(monkeypatch):
    mod = _load_ext()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: None)
    mod.ShadowJudgeExtension(agent=_Agent()).execute(loop_data={"history": _history()})  # must not raise


def test_judge_triggers_distill(monkeypatch, tmp_path):
    mod = _load_ext()
    fake = FakeRuntime()
    called = {}
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    monkeypatch.setattr(
        mod,
        "distill_new_rows",
        lambda rt, db, session_id, since_ts, cap=3: called.setdefault("n", 1),
    )
    monkeypatch.setattr(mod, "jit_db_path", lambda: str(tmp_path / "jev.db"))
    mod.ShadowJudgeExtension(agent=_Agent()).execute(
        loop_data={"session_id": "s1", "history": _history()}
    )
    assert "n" in called
