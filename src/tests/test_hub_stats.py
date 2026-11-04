"""Hub stats: the refresher writes stats/<slug>.json, build_stats reads measured usage, comparison and A/B."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import config
from hub import bench_store, refresher, registry
from hub import stats as hub_stats
from hub import usage_store as store

NOW = datetime(2026, 11, 4, 12, 0, 0)
FAKE_BUILDER = """
const fs = require("fs"), path = require("path");
const args = process.argv.slice(2);
const i = args.indexOf("--out");
const out = i >= 0 ? args.splice(i, 2)[1] : null;
const root = path.resolve(args[0]);
fs.appendFileSync(process.env.FAKE_BUILDER_LOG, root + "\\n");
const target = out || path.join(root, ".planning", "state.html");
fs.mkdirSync(path.dirname(target), { recursive: true });
fs.writeFileSync(target, "<html>fake</html>");
"""
DAILY_DEFAULTS = {"registered": 1, "sessions": 1, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                  "cache_write_tokens": 0, "turns": 0, "api_calls": 0, "capsules": 0, "capsule_tokens": 0,
                  "hook_ms": 0.0, "cost_usd": None, "cost_sessions": 0}


def make_repo(path: Path) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text("# State\n\n## Tasks\n- [ ] H12 stats\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                       cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def fake_builder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    script = tmp_path / "fake_builder.js"
    script.write_text(FAKE_BUILDER, encoding="utf-8")
    log = tmp_path / "builds.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv(config.COCKPIT_BUILDER_ENV, str(script))
    monkeypatch.setenv("FAKE_BUILDER_LOG", str(log))
    return lambda: [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def add_daily(conn, day: str, source: str, project: str, **values) -> None:
    row = {**DAILY_DEFAULTS, **values, "day": day, "source": source, "project": project}
    names = list(row)
    conn.execute(f"INSERT INTO daily_usage ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                 [row[name] for name in names])


def add_session_day(conn, source: str, session: str, day: str, path: str, **values) -> None:
    row = {"source": source, "unit": f"{session}-unit", "day": day, "session_id": session, "path": path, **values}
    names = list(row)
    conn.execute(f"INSERT INTO session_days ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                 [row[name] for name in names])


def add_ab_run(conn, batch: str, task: str, arm: str, tokens: int, started: str) -> None:
    bench_store.insert_run(conn, {
        "batch_id": batch, "project": "demo", "repo_path": "/tmp/demo", "head": "abc123", "task_id": task,
        "prompt": "p", "run_index": 0, "arm": arm, "model": "sonnet", "started_at": started, "wall_s": 10.0,
        "exit_code": 0, "is_error": 0, "num_turns": 2, "input_tokens": tokens, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
    })


@pytest.fixture
def usage_db(tmp_path):
    db = tmp_path / "usage.sqlite"
    conn = bench_store.connect(db)
    add_daily(conn, "2026-10-20", "claude", "demo", input_tokens=1000, output_tokens=200, turns=4)
    add_daily(conn, "2026-10-20", "jit", "demo", capsules=3, capsule_tokens=900, sessions=1)
    add_daily(conn, "2026-11-03", "hermes", "demo", input_tokens=500, api_calls=7, cost_usd=0.25, cost_sessions=1)
    add_daily(conn, "2026-09-01", "claude", "demo", input_tokens=99999)  # outside the 30-day window
    add_daily(conn, "2026-11-03", "claude", "other", input_tokens=77777)
    add_session_day(conn, "claude", "s-on", "2026-10-20", "/tmp/demo", input_tokens=600, turns=2)
    add_session_day(conn, "claude", "s-off", "2026-10-21", "/tmp/demo", input_tokens=400, turns=2)
    add_session_day(conn, "jit", "s-on", "2026-10-20", "/tmp/demo", capsules=3)
    add_ab_run(conn, "old", "t1", "on", 1, "2026-10-01T09:00:00")
    for task, on, off in (("t1", 900, 1000), ("t2", 800, 1000)):
        add_ab_run(conn, "new", task, "on", on, "2026-11-01T09:00:00")
        add_ab_run(conn, "new", task, "off", off, "2026-11-01T09:05:00")
    conn.commit()
    conn.close()
    return db


ENTRY = {"slug": "demo", "path": "/tmp/demo"}
PROJECTS = [ENTRY]


def test_build_stats_reads_window_comparison_and_latest_ab(usage_db):
    doc = hub_stats.build_stats(ENTRY, now=NOW, db_path=usage_db, projects=PROJECTS, collect_errors={"claude": ["x"]})
    assert (doc["since"], doc["until"], doc["window_days"]) == ("2026-10-06", "2026-11-04", 30)
    usage = doc["usage"]
    assert [day["day"] for day in usage["days"]] == ["2026-10-20", "2026-11-03"]
    assert usage["totals"]["total_tokens"] == 1700
    assert usage["totals"]["turns"] == 4 and usage["totals"]["capsules"] == 3
    assert usage["totals"]["sessions"] == 2  # JIT rows add capsules, never sessions
    assert usage["totals"]["cost_usd"] == pytest.approx(0.25)
    assert usage["days"][0]["cost_usd"] is None
    comparison = doc["comparison"]
    assert comparison["jit_on"]["n"] == 1 and comparison["jit_off"]["n"] == 1
    assert comparison["warning"] == "za mało danych" and comparison["label"] == "obserwacja, nie eksperyment"
    ab = doc["ab"]
    assert (ab["batch_id"], ab["model"], ab["calls"], ab["tasks"]) == ("new", "sonnet", 4, 2)
    assert ab["date"] == "2026-11-01T09:00:00"
    assert ab["paired_on_minus_off"]["total_tokens"] == {"median": -150, "n": 2}
    assert doc["collect_errors"] == {"claude": ["x"]}
    assert "suggestions" in doc


def test_build_stats_without_store_says_what_is_missing(tmp_path):
    doc = hub_stats.build_stats(ENTRY, now=NOW, db_path=tmp_path / "none.sqlite", projects=PROJECTS)
    for section in ("usage", "comparison", "ab"):
        assert "brak magazynu zużycia" in doc[section]["missing"]
    assert not (tmp_path / "none.sqlite").exists()


def test_cost_stays_none_when_no_source_recorded_it(tmp_path):
    db = tmp_path / "usage.sqlite"
    conn = store.connect(db)
    add_daily(conn, "2026-11-01", "claude", "demo", input_tokens=10)
    conn.commit()
    conn.close()
    doc = hub_stats.build_stats(ENTRY, now=NOW, db_path=db, projects=PROJECTS)
    assert doc["usage"]["totals"]["cost_usd"] is None
    assert doc["ab"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_refresher_writes_stats_file_and_rebuilds_only_on_change(tmp_path, fake_builder, monkeypatch):
    repo = make_repo(tmp_path / "demo")
    registry.register_project(repo)
    slug = registry.load_projects()[0]["slug"]
    results = refresher.refresh_all(collect=lambda: {"hermes": ["db locked"]})
    assert [r.status for r in results] == [refresher.REBUILT]
    path = config.hub_dir() / "stats" / f"{slug}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["slug"] == slug and doc["schema"] == hub_stats.SCHEMA_VERSION
    assert doc["collect_errors"] == {"hermes": ["db locked"]}
    assert set(doc) >= {"usage", "comparison", "ab", "suggestions", "digest"}
    assert refresher.load_state(slug)["stats_digest"] == doc["digest"]

    assert [r.status for r in refresher.refresh_all(collect=dict)] == [refresher.UNCHANGED]
    monkeypatch.setattr(hub_stats, "is_due", lambda slug: True)  # the stats file aged past its max age
    assert [r.status for r in refresher.refresh_all(collect=dict)] == [refresher.REBUILT]  # collect_errors changed
    assert [r.status for r in refresher.refresh_all(collect=dict)] == [refresher.UNCHANGED]  # same content
    assert len(fake_builder()) == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_stats_failure_never_blocks_the_cockpit_build(tmp_path, fake_builder, monkeypatch):
    registry.register_project(make_repo(tmp_path / "demo"))

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(hub_stats, "write_stats", broken)
    results = refresher.refresh_all(collect=dict)
    assert [r.status for r in results] == [refresher.REBUILT]
    state = refresher.load_state(results[0].slug)
    assert state["stats_error"] == "disk full" and state["stats_digest"] is None
