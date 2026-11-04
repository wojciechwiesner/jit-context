"""Usage suggestion rules on a tmp usage store: week-over-week spike and JIT off in most sessions."""

from datetime import date, datetime, timedelta

import pytest

from hub import suggestion_rules_usage as rules
from hub import suggestions
from hub import usage_store as store
from hub.suggestion_model import MissingData, ProjectContext

NOW = datetime(2026, 11, 4, 12, 0, 0)
TODAY = NOW.date()
SLUG = "alpha"


def day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


class Store:
    def __init__(self, tmp_path):
        self.path = tmp_path / "usage.sqlite"
        self.project = tmp_path / "alpha"
        self.project.mkdir()
        self.projects = [{"slug": SLUG, "path": str(self.project)}]
        self.conn = store.connect(self.path)

    def claude(self, session: str, when: str, tokens: int = 100) -> None:
        identity = {"session_id": session, "path": str(self.project), "scope": None}
        store.add_to_day(self.conn, "claude", f"{session}.jsonl", when, identity,
                         {"turns": 1, "input_tokens": tokens})

    def capsule(self, session: str, when: str) -> None:
        store.add_to_day(self.conn, "jit", f"{SLUG}/{session}/overlay.db", when,
                         {"session_id": session, "path": None, "scope": SLUG}, {"turns": 1, "capsules": 1})

    def ctx(self) -> ProjectContext:
        self.conn.commit()
        view = rules.load_usage(SLUG, TODAY, db_path=self.path, projects=self.projects)
        return ProjectContext(self.project, now=NOW, usage=view)


@pytest.fixture
def usage(tmp_path):
    fixture = Store(tmp_path)
    yield fixture
    fixture.conn.close()


def test_usage_spike_fires_when_week_is_more_than_double(usage):
    usage.claude("old", day(10), tokens=1000)
    usage.claude("new", day(1), tokens=2500)
    found = rules.usage_spike(usage.ctx())
    assert found is not None and found.rule_id == "usage_spike"
    assert [item.value for item in found.evidence[:2]] == ["2500", "1000"]
    assert "2.5x" in found.summary


def test_usage_spike_quiet_below_double_and_skipped_without_baseline(usage):
    usage.claude("old", day(10), tokens=1000)
    usage.claude("new", day(1), tokens=1900)
    usage.claude("other-project", day(1), tokens=10 ** 6)
    usage.conn.execute("UPDATE session_days SET path = '/elsewhere' WHERE session_id = 'other-project'")
    assert rules.usage_spike(usage.ctx()) is None
    usage.conn.execute("DELETE FROM session_days WHERE session_id = 'old'")
    with pytest.raises(MissingData):
        rules.usage_spike(usage.ctx())


def test_jit_mostly_off_fires_when_most_active_sessions_lack_capsules(usage):
    for index in range(6):
        usage.claude(f"s{index}", day(index % 3))
    usage.capsule("s0", day(0))
    found = rules.jit_mostly_off(usage.ctx())
    assert found is not None and found.evidence[0].value == "5 / 6"


def test_jit_mostly_off_quiet_when_jit_on_or_project_inactive(usage):
    for index in range(6):
        usage.claude(f"s{index}", day(1))
    for index in range(4):
        usage.capsule(f"s{index}", day(1))
    assert rules.jit_mostly_off(usage.ctx()) is None
    usage.conn.execute("DELETE FROM session_days")
    for index in range(rules.MIN_ACTIVE_SESSIONS - 1):
        usage.claude(f"quiet{index}", day(1))
    usage.claude("last-month", day(20))
    assert rules.jit_mostly_off(usage.ctx()) is None


def test_usage_rules_skipped_without_store_and_errors_on_broken_store(tmp_path):
    report = suggestions.project_suggestions(tmp_path, slug=SLUG, now=NOW, usage_db=tmp_path / "absent.sqlite",
                                             projects=[])
    reasons = {s["id"]: s["reason"] for s in report["skipped"]}
    assert "brak magazynu zużycia" in reasons["usage_spike"] and "jit_mostly_off" in reasons
    assert not (tmp_path / "absent.sqlite").exists()
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"not a database" * 100)
    report = suggestions.project_suggestions(tmp_path, slug=SLUG, now=NOW, usage_db=broken, projects=[])
    assert {e["id"] for e in report["errors"]} == {"usage_spike", "jit_mostly_off"}


def test_load_usage_without_slug_is_missing(tmp_path):
    with pytest.raises(MissingData):
        rules.load_usage(None, date(2026, 11, 4), db_path=tmp_path / "x.sqlite", projects=[])
