"""Tests for cockpit freshness: state.html rebuild on commit and architecture diagram drift."""

import subprocess
from pathlib import Path

import pytest

from l1.cockpit_sync import architecture_drift, regenerate_cockpit


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)


def commit(repo: Path, rel: str, text: str, msg: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@theones.io")
    git(repo, "config", "user.name", "Test")
    commit(repo, ".planning/ARCHITECTURE.mmd", "graph TD\n  A-->B\n", "docs: diagram")
    return repo


def test_no_drift_below_threshold(repo):
    for i in range(3):
        commit(repo, f"src/m{i}.js", "x", f"feat: m{i}")
    assert architecture_drift(repo, threshold=5) is None


def test_drift_counts_code_commits_only(repo):
    for i in range(4):
        commit(repo, f"docs/n{i}.md", "x", f"docs: n{i}")
        commit(repo, f".planning/s{i}.txt", "x", f"chore: s{i}")
    assert architecture_drift(repo, threshold=3) is None
    for i in range(3):
        commit(repo, f"src/m{i}.js", "x", f"feat: m{i}")
    warning = architecture_drift(repo, threshold=3)
    assert warning is not None and "3 commitów" in warning


def test_drift_resets_when_diagram_changes(repo):
    for i in range(3):
        commit(repo, f"src/m{i}.js", "x", f"feat: m{i}")
    commit(repo, ".planning/ARCHITECTURE.mmd", "graph TD\n  A-->C\n", "docs: redraw")
    assert architecture_drift(repo, threshold=3) is None


def test_regenerate_runs_builder_for_ignored_cockpit(repo, tmp_path):
    builder = tmp_path / "builder.js"
    builder.write_text("require('fs').writeFileSync(process.argv[2] + '/.planning/state.html', 'ok');")
    ok, msg = regenerate_cockpit(repo, builder=builder)
    assert ok, msg
    assert (repo / ".planning/state.html").read_text() == "ok"


def test_regenerate_skips_tracked_cockpit(repo, tmp_path):
    (repo / ".planning/state.html").write_text("committed")
    git(repo, "add", "-f", ".planning/state.html")  # -f: a global gitignore may list state.html
    git(repo, "commit", "-m", "docs: cockpit")
    builder = tmp_path / "builder.js"
    builder.write_text("require('fs').writeFileSync(process.argv[2] + '/.planning/state.html', 'rebuilt');")
    ok, msg = regenerate_cockpit(repo, builder=builder)
    assert not ok and "tracked" in msg
    assert (repo / ".planning/state.html").read_text() == "committed"


def test_regenerate_reports_builder_failure(repo, tmp_path):
    builder = tmp_path / "builder.js"
    builder.write_text("process.exit(3)")
    ok, msg = regenerate_cockpit(repo, builder=builder)
    assert not ok and "exit 3" in msg
