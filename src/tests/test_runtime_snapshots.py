"""Immutable runtime snapshots: Claude Code hooks and Hermes plugin never import the live checkout."""

import importlib.util
import os
import stat

import pytest

from installer import claude_code, hermes
from installer.common import OK, SNAPSHOT_KEEP, SNAPSHOT_STAMP_FILE, create_snapshot, prune_snapshots

RESOLVER_PATH = claude_code.HOOKS_SRC / "jit_src_path.py"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("JIT_INSTALL_HOME", "JIT_DEV_LIVE", "JIT_SRC"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".claude").mkdir()
    return tmp_path


def _writable_paths(tree):
    paths = [tree]
    for root, dirs, files in os.walk(tree):
        paths += [os.path.join(root, n) for n in (*dirs, *files)]
    return [p for p in paths if os.stat(p).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)]


def _snapshots(releases, prefix):
    return sorted(p for p in releases.iterdir() if p.name.startswith(f"{prefix}-"))


def _load_resolver(hook_dir):
    spec = importlib.util.spec_from_file_location("jit_src_path_under_test", hook_dir / "jit_src_path.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claude_install_deploys_read_only_snapshot(fake_home):
    assert claude_code.install().status == OK
    current = fake_home / ".claude/jit-context-runtime/current"
    assert current.is_symlink()
    snap = current.resolve()
    assert (snap / "hooks.py").exists() and not (snap / "tests").exists()
    assert (snap / SNAPSHOT_STAMP_FILE).read_text().split()[2] == str(claude_code.INTEGRATIONS_DIR.parent / "src")
    assert _writable_paths(snap) == []


def test_installed_hook_resolves_snapshot_not_checkout(fake_home):
    claude_code.install()
    resolver = _load_resolver(fake_home / ".claude/hooks")
    assert resolver.resolve_jit_src() == str((fake_home / ".claude/jit-context-runtime/current").resolve())


def test_reinstall_replaces_snapshot_and_keeps_previous(fake_home):
    claude_code.install()
    current = fake_home / ".claude/jit-context-runtime/current"
    first = current.resolve()
    claude_code.install()
    assert current.resolve() != first
    assert first.exists()  # previous one kept for rollback until pruned


def test_live_mode_opt_out(fake_home, monkeypatch):
    claude_code.install()
    monkeypatch.setenv("JIT_DEV_LIVE", "1")
    result = claude_code.install()
    assert result.status == OK and "JIT_DEV_LIVE=1" in result.detail
    assert not (fake_home / ".claude/jit-context-runtime/current").exists()
    resolver = _load_resolver(fake_home / ".claude/hooks")
    assert resolver.resolve_jit_src() == str(fake_home / ".jit-context/src")


def test_live_mode_env_wins_over_existing_snapshot(fake_home, monkeypatch):
    claude_code.install()
    monkeypatch.setenv("JIT_DEV_LIVE", "1")
    resolver = _load_resolver(fake_home / ".claude/hooks")
    assert resolver.resolve_jit_src() == str(fake_home / ".jit-context/src")


def test_prune_keeps_newest_and_protected(fake_home):
    releases = fake_home / "releases"
    made = [create_snapshot(releases, "src") for _ in range(SNAPSHOT_KEEP + 2)]
    os.utime(made[0], (1, 1))  # oldest by far, but protected below
    removed = prune_snapshots(releases, "src", keep=made[0])
    left = _snapshots(releases, "src")
    assert removed == 1 and made[0] in left and made[1] not in left and made[-1] in left and len(left) == SNAPSHOT_KEEP + 1


def test_claude_reinstall_prunes_and_uninstall_removes_read_only_runtime(fake_home):
    for _ in range(SNAPSHOT_KEEP + 2):
        claude_code.install()
    runtime = fake_home / ".claude/jit-context-runtime"
    assert len(_snapshots(runtime, "src")) == SNAPSHOT_KEEP
    assert claude_code.uninstall().status == OK
    assert not runtime.exists()


def test_hermes_snapshot_is_read_only_and_pruned(fake_home, monkeypatch):
    monkeypatch.setattr(hermes, "_hermes", lambda *args: False)
    (fake_home / ".hermes").mkdir()
    for _ in range(SNAPSHOT_KEEP + 1):
        assert hermes.install().status == OK
    link = fake_home / ".hermes/plugins/ona-context"
    releases = fake_home / ".hermes/plugin-releases"
    assert _writable_paths(link.resolve()) == []
    assert (link / SNAPSHOT_STAMP_FILE).exists()
    assert len(_snapshots(releases, "ona-context")) == SNAPSHOT_KEEP
    assert link.resolve() in _snapshots(releases, "ona-context")
