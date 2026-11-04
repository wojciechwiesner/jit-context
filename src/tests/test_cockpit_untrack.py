"""`jit cockpit untrack`: removes the cockpit from the index only after a yes, never commits."""

import os
import subprocess
import sys
from pathlib import Path

import init as init_mod
from hub import untrack

SRC_DIR = Path(init_mod.__file__).resolve().parent
ENTRY = ".planning/state.html"


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )
    return res.stdout


def make_repo_with_cockpit(path: Path) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "state.html").write_text("<html>cockpit</html>\n", encoding="utf-8")
    (path / ".gitignore").write_text("node_modules", encoding="utf-8")  # no trailing newline on purpose
    git(path, "init", "-q")
    git(path, "add", "-A")
    git(path, "add", "-f", ENTRY)  # a global excludesFile may ignore it; the scenario is a tracked cockpit
    git(path, "commit", "-q", "-m", "init")
    return path


def run_cli(repo: Path, home: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home)}
    env.pop("JIT_DEV_LIVE", None)
    return subprocess.run(
        [sys.executable, "-m", "init", "cockpit", "untrack", str(repo), *extra],
        cwd=SRC_DIR, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )


def snapshot(repo: Path) -> tuple:
    return git(repo, "ls-files"), (repo / ".gitignore").read_text(encoding="utf-8"), git(repo, "rev-parse", "HEAD")


def test_yes_removes_from_index_keeps_file_and_never_commits(tmp_path):
    repo = make_repo_with_cockpit(tmp_path / "repo")
    head = git(repo, "rev-parse", "HEAD")
    proc = run_cli(repo, tmp_path / "home", "--yes")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (repo / ENTRY).read_text(encoding="utf-8") == "<html>cockpit</html>\n"
    assert ENTRY not in git(repo, "ls-files").splitlines()
    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"node_modules\n{ENTRY}\n"
    assert git(repo, "rev-parse", "HEAD") == head
    assert "git -C" in proc.stdout and "commit -m" in proc.stdout and "add .gitignore" in proc.stdout
    assert git(repo, "check-ignore", ENTRY).strip() == ENTRY


def test_non_interactive_without_yes_changes_nothing_and_exits_2(tmp_path):
    repo = make_repo_with_cockpit(tmp_path / "repo")
    before = snapshot(repo)
    proc = run_cli(repo, tmp_path / "home")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert snapshot(repo) == before
    assert git(repo, "status", "--porcelain") == ""
    assert "--yes" in proc.stdout


def test_interactive_answer_decides(tmp_path):
    repo = make_repo_with_cockpit(tmp_path / "repo")
    before = snapshot(repo)
    assert untrack.untrack(repo, assume_yes=False, interactive=True, ask=lambda _q: "n") == 1
    assert snapshot(repo) == before
    assert untrack.untrack(repo, assume_yes=False, interactive=True, ask=lambda _q: "tak") == 0
    assert ENTRY not in git(repo, "ls-files").splitlines()
    assert (repo / ENTRY).is_file()


def test_eof_on_prompt_is_a_no(tmp_path):
    repo = make_repo_with_cockpit(tmp_path / "repo")
    before = snapshot(repo)

    def closed_stdin(_question: str) -> str:
        raise EOFError

    assert untrack.untrack(repo, assume_yes=False, interactive=True, ask=closed_stdin) == 1
    assert snapshot(repo) == before


def test_untracked_cockpit_is_a_no_op(tmp_path):
    repo = make_repo_with_cockpit(tmp_path / "repo")
    assert untrack.untrack(repo, assume_yes=True, interactive=False) == 0
    before = snapshot(repo)
    assert untrack.untrack(repo, assume_yes=False, interactive=False) == 0
    assert snapshot(repo) == before
    assert (repo / ".gitignore").read_text(encoding="utf-8").count(ENTRY) == 1


def test_file_path_and_existing_gitignore_entry(tmp_path):
    repo = make_repo_with_cockpit(tmp_path / "repo")
    (repo / ".gitignore").write_text(f"/{ENTRY}\n", encoding="utf-8")
    assert untrack.untrack(repo / ENTRY, assume_yes=True, interactive=False) == 0
    assert ENTRY not in git(repo, "ls-files").splitlines()
    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"/{ENTRY}\n"


def test_outside_git_fails_without_changes(tmp_path):
    plain = tmp_path / "plain"
    (plain / ".planning").mkdir(parents=True)
    assert untrack.untrack(plain, assume_yes=True, interactive=False) == 1
    assert not (plain / ".gitignore").exists()
