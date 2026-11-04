"""Suggestion rules over git history, on tmp repos with fixed commit dates: positive and negative case per rule."""

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from hub import suggestion_rules_git as rules
from hub import suggestions
from hub.suggestion_model import ProjectContext
from l1.cockpit_sync import ARCHITECTURE_STALE_COMMITS

NOW = datetime(2026, 11, 4, 12, 0, 0)
STATE_OPEN = "# State\n\n## Tasks\n- [ ] T1 build the thing\n"
STATE_DONE = "# State\n\n## Tasks\n- [x] T1 build the thing\n"


def git(repo: Path, *args: str, when: datetime = NOW) -> str:
    env = dict(os.environ, GIT_AUTHOR_DATE=when.isoformat(), GIT_COMMITTER_DATE=when.isoformat())
    result = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo, env=env, check=True, capture_output=True, text=True)
    return result.stdout


def write(repo: Path, rel: str, text: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str, when: datetime) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, when=when)


def make_repo(tmp_path: Path, state: str = STATE_OPEN, when: datetime = NOW - timedelta(days=1)) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    write(repo, ".planning/STATE.md", state)
    write(repo, "app.py", "print('hi')\n")
    commit(repo, "init", when)
    return repo


def code_commits(repo: Path, count: int, start: datetime, with_changelog_at: int = -1) -> None:
    for index in range(count):
        write(repo, "app.py", f"print({index})\n")
        if index == with_changelog_at:
            write(repo, "CHANGELOG.md", f"## [Unreleased]\n- change {index}\n")
        commit(repo, f"feat: change {index}", start + timedelta(minutes=index))


def ctx(repo: Path) -> ProjectContext:
    return ProjectContext(repo, now=NOW)


def test_state_stale_fires_when_state_lags_newest_commit(tmp_path):
    repo = make_repo(tmp_path, when=NOW - timedelta(days=10))
    code_commits(repo, 1, NOW - timedelta(days=1))
    found = rules.state_stale(ctx(repo))
    assert found is not None and found.rule_id == "state_stale"
    assert found.evidence[0].ref == ".planning/STATE.md"
    assert "feat: change 0" in found.evidence[1].value


def test_state_stale_quiet_when_state_recent_or_edited(tmp_path):
    repo = make_repo(tmp_path, when=NOW - timedelta(days=2))
    code_commits(repo, 1, NOW - timedelta(days=1))
    assert rules.state_stale(ctx(repo)) is None
    old = make_repo(tmp_path / "old", when=NOW - timedelta(days=10))
    code_commits(old, 1, NOW - timedelta(days=1))
    write(old, ".planning/STATE.md", STATE_DONE)  # uncommitted edit: mtime is now, newer than any commit
    assert rules.state_stale(ctx(old)) is None


def test_architecture_drift_fires_after_many_code_commits(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, ".planning/ARCHITECTURE.mmd", "graph TD\n  A-->B\n")
    commit(repo, "docs: diagram", NOW - timedelta(days=1))
    code_commits(repo, ARCHITECTURE_STALE_COMMITS, NOW - timedelta(hours=20))
    found = rules.architecture_stale(ctx(repo))
    assert found is not None and found.rule_id == "architecture_drift"
    assert f"{ARCHITECTURE_STALE_COMMITS} commitów" in found.summary


def test_architecture_drift_quiet_when_diagram_fresh_and_skipped_without_diagram(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, ".planning/ARCHITECTURE.mmd", "graph TD\n  A-->B\n")
    commit(repo, "docs: diagram", NOW - timedelta(days=1))
    code_commits(repo, 2, NOW - timedelta(hours=20))
    assert rules.architecture_stale(ctx(repo)) is None
    bare = make_repo(tmp_path / "bare")
    report = suggestions.evaluate(ctx(bare), rules=(("architecture_drift", rules.architecture_stale),))
    assert report["skipped"] == [{"id": "architecture_drift", "reason": "brak .planning/ARCHITECTURE.mmd"}]


def test_cockpit_tracked_fires_only_for_tracked_cockpit(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, ".planning/state.html", "<html></html>")
    assert rules.cockpit_tracked(ctx(repo)) is None  # untracked file on disk
    git(repo, "add", "-f", ".planning/state.html")  # -f: a global excludes file may ignore state.html
    git(repo, "commit", "-q", "-m", "track cockpit")
    found = rules.cockpit_tracked(ctx(repo))
    assert found is not None and "jit cockpit untrack" in found.action


def test_changelog_stale_fires_after_ten_code_commits_without_changelog(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "CHANGELOG.md", "# Changelog\n")
    commit(repo, "docs: changelog", NOW - timedelta(days=1))
    code_commits(repo, rules.CHANGELOG_WINDOW_COMMITS, NOW - timedelta(hours=20))
    found = rules.changelog_stale(ctx(repo))
    assert found is not None and found.rule_id == "changelog_stale"
    assert found.evidence[0].value == "jest w repozytorium"


def test_changelog_stale_quiet_when_changelog_touched_or_history_short(tmp_path):
    repo = make_repo(tmp_path)
    code_commits(repo, rules.CHANGELOG_WINDOW_COMMITS, NOW - timedelta(hours=20), with_changelog_at=3)
    assert rules.changelog_stale(ctx(repo)) is None
    short = make_repo(tmp_path / "short")
    code_commits(short, 3, NOW - timedelta(hours=20))
    assert rules.changelog_stale(ctx(short)) is None


def test_env_tracked_fires_for_env_files_in_index(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, ".env", "X=1\n")
    write(repo, "config/.env.production", "X=2\n")
    commit(repo, "oops", NOW - timedelta(hours=1))
    found = rules.env_tracked(ctx(repo))
    assert found is not None and found.severity == "high"
    assert sorted(item.ref for item in found.evidence) == [".env", "config/.env.production"]


def test_env_tracked_quiet_for_example_and_ignored_env(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, ".gitignore", ".env\n")
    write(repo, ".env", "X=1\n")
    write(repo, ".env.example", "X=\n")
    commit(repo, "example only", NOW - timedelta(hours=1))
    assert rules.env_tracked(ctx(repo)) is None


def test_inactive_with_open_tasks_fires_after_fourteen_idle_days(tmp_path):
    repo = make_repo(tmp_path, when=NOW - timedelta(days=20))
    found = rules.inactive_with_open_tasks(ctx(repo))
    assert found is not None and "20 dni" in found.summary
    assert "T1 build the thing" in found.evidence[1].value


def test_inactive_with_open_tasks_quiet_when_recent_or_all_done(tmp_path):
    assert rules.inactive_with_open_tasks(ctx(make_repo(tmp_path / "a", when=NOW - timedelta(days=2)))) is None
    done = make_repo(tmp_path / "b", state=STATE_DONE, when=NOW - timedelta(days=20))
    assert rules.inactive_with_open_tasks(ctx(done)) is None
