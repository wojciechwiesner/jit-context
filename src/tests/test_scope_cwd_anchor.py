"""W5: the working directory anchors the active scope; prompt words must not hijack it."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from l0.db import get_db, init_db
from l0.overlay import ensure_session
from l1.scope import resolve_scope, scope_from_cwd


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Projects" / "active" / "jit-context" / "src").mkdir(parents=True)
    (tmp_path / "Projects" / "active" / "autocheck").mkdir()
    return tmp_path


def test_subdir_of_active_project_maps_to_project(home):
    assert scope_from_cwd(str(home / "Projects" / "active" / "jit-context" / "src")) == "jit-context"


def test_roots_and_unknown_dirs_have_no_scope(home, tmp_path):
    assert scope_from_cwd(str(home)) is None
    assert scope_from_cwd(str(home / "Projects" / "active")) is None
    assert scope_from_cwd(None) is None
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert scope_from_cwd(str(outside)) is None


def test_git_root_outside_projects_dir(home, tmp_path):
    repo = tmp_path / "other" / "myrepo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pkg").mkdir()
    assert scope_from_cwd(str(repo / "pkg")) == "myrepo"


def test_git_worktree_resolves_main_repo(home, tmp_path):
    wt = tmp_path / "scratch" / "wt-dir"
    wt.mkdir(parents=True)
    gitdir = home / "Projects" / "active" / "jit-context" / ".git" / "worktrees" / "x"
    (wt / ".git").write_text(f"gitdir: {gitdir}\n")
    assert scope_from_cwd(str(wt)) == "jit-context"


def test_worktree_parked_under_projects_dir_resolves_main_repo(home):
    # e.g. ~/Projects/active/dos-wt/CE is a worktree of ~/Projects/active/dos, not a project "dos-wt"
    wt = home / "Projects" / "active" / "jit-context-wt" / "CE"
    (wt / "src").mkdir(parents=True)
    gitdir = home / "Projects" / "active" / "jit-context" / ".git" / "worktrees" / "CE"
    (wt / ".git").write_text(f"gitdir: {gitdir}\n")
    assert scope_from_cwd(str(wt)) == "jit-context"
    assert scope_from_cwd(str(wt / "src")) == "jit-context"
    # a plain folder without a worktree marker keeps the old first-level behaviour
    (home / "Projects" / "active" / "plain" / "sub").mkdir(parents=True)
    assert scope_from_cwd(str(home / "Projects" / "active" / "plain" / "sub")) == "plain"


def test_prompt_mention_does_not_hijack_cwd_scope(home):
    # `home` fixture creates Projects/active/autocheck, so the test does not depend on the host's real dirs (CI).
    active, retrieval, _, _ = resolve_scope("sprawdz autocheck", "general", cwd_scope="jit-context")
    assert active == "jit-context"
    assert "autocheck" in retrieval


def test_stale_stored_scope_is_realigned():
    active, _, _, _ = resolve_scope("dorzuc i dzialaj", "autocheck", cwd_scope="jit-context")
    assert active == "jit-context"


def test_explicit_switch_still_wins_over_cwd():
    active, _, _, _ = resolve_scope("przejdźmy do synthapse", "jit-context", cwd_scope="jit-context")
    assert active == "synthapse"


def test_without_cwd_old_behaviour_unchanged():
    active, retrieval, _, _ = resolve_scope("How did we do auth in InvoiceFlow?", "hermes-jit-context-os")
    assert active == "hermes-jit-context-os"
    assert "invoiceflow" in retrieval


def test_compile_context_realigns_stored_scope(home, tmp_path):
    from context.compiler import compile_context
    db_path = tmp_path / "overlay.db"
    init_db(db_path)
    conn = get_db(db_path)
    ensure_session(conn, "s1", default_scope="autocheck")
    cwd = str(home / "Projects" / "active" / "jit-context" / "src")
    compile_context(conn, "s1", "dorzuc i dzialaj", session_cwd=cwd)
    row = conn.execute("SELECT active_scope, scope_epoch FROM sessions WHERE session_id='s1'").fetchone()
    assert row[0] == "jit-context"
    assert row[1] == 2
