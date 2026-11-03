"""Hub refresher: rebuild only on signature change, tracked cockpits stay untouched, failures are isolated."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import config
import init as init_mod
from hub import refresher, registry
from hub.signature import compute_signature

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

INIT_PY = Path(init_mod.__file__).resolve()
REPO_BUILDER = Path(__file__).resolve().parents[2] / "cockpit" / "build_state_template.js"
FAKE_BUILDER = """
const fs = require("fs"), path = require("path");
const args = process.argv.slice(2);
const i = args.indexOf("--out");
const out = i >= 0 ? args.splice(i, 2)[1] : null;
const root = path.resolve(args[0]);
fs.appendFileSync(process.env.FAKE_BUILDER_LOG, root + "\\n");
if (fs.existsSync(path.join(root, ".planning", "FAIL"))) { console.error("boom"); process.exit(3); }
const target = out || path.join(root, ".planning", "state.html");
fs.mkdirSync(path.dirname(target), { recursive: true });
fs.writeFileSync(target, "<html>fake</html>");
"""


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                         cwd=cwd, check=True, capture_output=True, text=True)
    return res.stdout.strip()


def make_repo(path: Path, track_cockpit: bool = False) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text("# State\n\n## Tasks\n- [ ] H3 refresher\n", encoding="utf-8")
    if track_cockpit:
        (path / ".planning" / "state.html").write_text("TRACKED COCKPIT\n", encoding="utf-8")
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


def touch_newer(path: Path, text: str) -> None:
    """Write `text` and push the mtime forward, so the change is visible on any mtime resolution."""
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def fake_builder(tmp_path, monkeypatch, home):
    script = tmp_path / "fake_builder.js"
    script.write_text(FAKE_BUILDER, encoding="utf-8")
    log = tmp_path / "builds.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv(config.COCKPIT_BUILDER_ENV, str(script))
    monkeypatch.setenv("FAKE_BUILDER_LOG", str(log))
    return lambda: [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def statuses(results):
    return {r.slug: r.status for r in results}


def test_nothing_changed_means_no_rebuild(tmp_path, fake_builder):
    entry, _ = registry.register_project(make_repo(tmp_path / "alpha"))
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.REBUILT}
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.UNCHANGED}
    assert len(fake_builder()) == 1


def test_state_md_edit_triggers_rebuild(tmp_path, fake_builder):
    repo = make_repo(tmp_path / "alpha")
    entry, _ = registry.register_project(repo)
    refresher.refresh_all()
    before = refresher.load_state(entry["slug"])["signature"]
    touch_newer(repo / ".planning" / "STATE.md", "# State\n\n## Tasks\n- [x] H3 refresher\n")
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.REBUILT}
    assert refresher.load_state(entry["slug"])["signature"] != before
    assert len(fake_builder()) == 2


def test_new_commit_in_worktree_triggers_rebuild(tmp_path, fake_builder):
    repo = make_repo(tmp_path / "alpha")
    worktree = tmp_path / "alpha-wt"
    git(repo, "worktree", "add", "-q", "-b", "feat", str(worktree))
    entry, _ = registry.register_project(worktree)
    assert Path(entry["path"]) == repo.resolve()
    refresher.refresh_all()
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.UNCHANGED}
    (worktree / "feature.py").write_text("x = 1\n", encoding="utf-8")
    git(worktree, "add", "feature.py")
    git(worktree, "commit", "-q", "-m", "feat: work in a worktree")
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.REBUILT}
    assert len(fake_builder()) == 2


def test_dossier_edit_triggers_rebuild(tmp_path, fake_builder, isolated_vault_and_workspace):
    repo = make_repo(tmp_path / "alpha")
    entry, _ = registry.register_project(repo)
    refresher.refresh_all()
    touch_newer(isolated_vault_and_workspace["projects"] / "alpha.md", "# alpha dossier\n")
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.REBUILT}


def test_failing_project_is_isolated_and_skipped_after_three_failures(tmp_path, fake_builder):
    good, _ = registry.register_project(make_repo(tmp_path / "good"))
    bad_repo = make_repo(tmp_path / "bad")
    bad, _ = registry.register_project(bad_repo)
    (bad_repo / ".planning" / "FAIL").write_text("", encoding="utf-8")
    passes = [statuses(refresher.refresh_all()) for _ in range(4)]
    assert [p[good["slug"]] for p in passes] == [refresher.REBUILT] + [refresher.UNCHANGED] * 3
    assert [p[bad["slug"]] for p in passes] == [refresher.FAILED] * 3 + [refresher.SKIPPED_FAILING]
    state = refresher.load_state(bad["slug"])
    assert state["failures"] == refresher.MAX_FAILURES and "boom" in state["error"]
    assert sum(1 for line in fake_builder() if line.endswith("/bad")) == refresher.MAX_FAILURES
    (bad_repo / ".planning" / "FAIL").unlink()
    touch_newer(bad_repo / ".planning" / "STATE.md", "# State\n\nfixed\n")
    assert statuses(refresher.refresh_all())[bad["slug"]] == refresher.REBUILT
    assert refresher.load_state(bad["slug"])["error"] is None


def test_missing_project_path_is_an_error_not_a_crash(tmp_path, fake_builder):
    repo = make_repo(tmp_path / "gone")
    entry, _ = registry.register_project(repo)
    shutil.rmtree(repo)
    result = refresher.refresh_all()[0]
    assert result.status == refresher.FAILED
    assert "project path missing" in refresher.load_state(entry["slug"])["error"]


def test_untracked_cockpit_is_rebuilt_in_place_with_state_record(tmp_path, home, monkeypatch):
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    repo = make_repo(tmp_path / "alpha")
    entry, _ = registry.register_project(repo)
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.REBUILT}
    cockpit = repo / ".planning" / "state.html"
    assert "<html" in cockpit.read_text(encoding="utf-8").lower()
    state = refresher.load_state(entry["slug"])
    assert state["output"] == str(cockpit)
    assert state["signature"] == compute_signature(repo)
    assert state["source_sha"] == git(repo, "rev-parse", "HEAD")
    assert state["source_branch"] == "main"
    assert state["error"] is None and state["built_at"] and state["duration_ms"] >= 0
    assert not refresher.hub_cockpit_path(entry["slug"]).exists()


def test_tracked_cockpit_is_never_modified_in_the_repo(tmp_path, home, monkeypatch):
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    repo = make_repo(tmp_path / "tracked", track_cockpit=True)
    entry, _ = registry.register_project(repo)
    tracked = repo / ".planning" / "state.html"
    original = tracked.read_bytes()
    refresher.refresh_all()
    touch_newer(repo / ".planning" / "STATE.md", "# State\n\n## Tasks\n- [x] H3 refresher\n")
    assert statuses(refresher.refresh_all()) == {entry["slug"]: refresher.REBUILT}
    assert tracked.read_bytes() == original
    assert git(repo, "status", "--porcelain", "--", ".planning/state.html") == ""
    hub_copy = refresher.hub_cockpit_path(entry["slug"])
    assert "<html" in hub_copy.read_text(encoding="utf-8").lower()
    assert refresher.load_state(entry["slug"])["output"] == str(hub_copy)


def test_cli_refresh_once(tmp_path, fake_builder):
    registry.register_project(make_repo(tmp_path / "alpha"))
    res = subprocess.run([sys.executable, str(INIT_PY), "hub", "refresh", "--once"],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert refresher.REBUILT in res.stdout and "alpha" in res.stdout
    state_files = list((Path(os.environ[config.HUB_DIR_ENV]) / refresher.STATE_DIR_NAME).glob("*.json"))
    assert [json.loads(p.read_text())["error"] for p in state_files] == [None]
