"""Tests for the vendored cockpit generator: config.cockpit_builder() and a real build via the repo copy."""

import importlib.util
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import config
from l1.cockpit_sync import regenerate_cockpit

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_BUILDER = REPO_ROOT / "cockpit" / "build_state_template.js"
DATA_RE = re.compile(r'<script type="application/json" id="cockpit-data-json">(.*?)</script>', re.S)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    repo = tmp_path / "demo-hub"
    (repo / ".planning").mkdir(parents=True)
    (repo / ".planning" / "STATE.md").write_text(
        "# Demo Hub\n\n## Project State\n**Current focus:** vendored cockpit\n\n## Tasks\n- [ ] H1 vendor\n")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@theones.io")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".planning/STATE.md")
    git(repo, "commit", "-q", "-m", "docs: state")
    return repo


def test_default_builder_is_the_repo_copy(monkeypatch):
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    assert config.cockpit_builder() == REPO_BUILDER
    assert REPO_BUILDER.exists()


def test_env_override_wins(monkeypatch, tmp_path):
    legacy = tmp_path / "sota-starter" / "build_state_template.js"
    monkeypatch.setenv(config.COCKPIT_BUILDER_ENV, str(legacy))
    assert config.cockpit_builder() == legacy


def test_snapshot_resolves_repo_through_stamp(monkeypatch, tmp_path):
    snapshot = tmp_path / "releases" / "snap"
    snapshot.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "src" / "config.py", snapshot / "config.py")
    (snapshot / config.SNAPSHOT_STAMP_FILE).write_text(f"abc1234 20261103-120000 {REPO_ROOT / 'src'}\n")
    monkeypatch.setenv("JIT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    spec = importlib.util.spec_from_file_location("snapshot_config", snapshot / "config.py")
    snap_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(snap_config)
    assert snap_config.cockpit_builder() == REPO_BUILDER


def test_builds_cockpit_with_repo_copy(project):
    ok, msg = regenerate_cockpit(project)
    assert ok, msg
    html = (project / ".planning" / "state.html").read_text(encoding="utf-8")
    assert "<title>demo hub — Kokpit projektu</title>" in html
    data = json.loads(DATA_RE.search(html).group(1))
    assert data["title"] == "DEMO-HUB"
    assert datetime.fromisoformat(data["generatedAt"].replace("Z", "+00:00")).year >= 2026
    assert "vendored cockpit" in html


def test_missing_builder_is_reported(project, monkeypatch, tmp_path):
    monkeypatch.setenv(config.COCKPIT_BUILDER_ENV, str(tmp_path / "nope.js"))
    ok, msg = regenerate_cockpit(project)
    assert not ok and "builder missing" in msg
    assert not (project / ".planning" / "state.html").exists()
