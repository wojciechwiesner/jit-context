"""Shared helpers for host installers: paths, backups, atomic JSON writes, results."""

from __future__ import annotations

import compileall
import json
import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
INTEGRATIONS_DIR = REPO_ROOT / "integrations"

OK = "OK"
SKIP = "SKIP"
FAIL = "FAIL"
DRY = "DRY-RUN"

SNAPSHOT_IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "*.egg-info")
SNAPSHOT_KEEP = 3
SNAPSHOT_STAMP_FILE = "DEPLOYED_FROM.txt"
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
GIT_TIMEOUT_S = 5


@dataclass
class Result:
    host: str
    status: str
    detail: str


def home() -> Path:
    # Path.home() honours $HOME, which keeps tests and --home overrides simple.
    return Path(os.environ.get("JIT_INSTALL_HOME") or Path.home())


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> Path | None:
    """Copy a file or directory next to itself with a timestamp suffix."""
    if not path.exists() and not path.is_symlink():
        return None
    target = path.with_name(f"{path.name}.bak.{timestamp()}")
    if path.is_dir() and not path.is_symlink():
        shutil.copytree(path, target, symlinks=True)
    else:
        shutil.copy2(path, target, follow_symlinks=False)
    return target


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def git_dirty() -> bool:
    """True when src/ has uncommitted changes (the snapshot then does not match any commit)."""
    return bool(_git("status", "--porcelain", "--", "src"))


def git_head() -> str:
    # `git rev-parse` also works in worktrees, where .git is a file, not a directory.
    resolved = _git("rev-parse", "--short=7", "HEAD")
    if resolved:
        return resolved
    head = REPO_ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            return (REPO_ROOT / ".git" / ref[5:]).read_text().strip()[:7]
        return ref[:7]
    except OSError:
        return "local"


def set_tree_writable(tree: Path, writable: bool) -> None:
    """Add (owner) or strip (everyone) write bits on every file and directory under tree."""
    paths = [tree]
    for root, dirs, files in os.walk(tree):
        paths += [Path(root) / name for name in (*dirs, *files)]
    for path in paths:
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IWUSR if writable else mode & ~WRITE_BITS)


def remove_tree(path: Path) -> None:
    """Delete a file, symlink or directory tree, including read-only snapshots."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        set_tree_writable(path, True)
        shutil.rmtree(path)


def _new_snapshot_path(releases: Path, prefix: str) -> Path:
    dirty = "-dirty" if git_dirty() else ""
    base = f"{prefix}-{git_head()}{dirty}-{timestamp()}"
    target, n = releases / base, 1
    while target.exists():
        target, n = releases / f"{base}.{n}", n + 1
    return target


def create_snapshot(releases: Path, prefix: str) -> Path:
    """Copy SRC_DIR to a fresh releases/<prefix>-<head>-<ts>, precompile it and make it read-only."""
    releases.mkdir(parents=True, exist_ok=True)
    target = _new_snapshot_path(releases, prefix)
    tmp = releases / f".{target.name}.tmp"
    remove_tree(tmp)
    shutil.copytree(SRC_DIR, tmp, ignore=SNAPSHOT_IGNORE)
    (tmp / SNAPSHOT_STAMP_FILE).write_text(f"{git_head()} {timestamp()} {SRC_DIR}\n")
    compileall.compile_dir(tmp, quiet=2)  # read-only tree cannot cache bytecode later
    os.replace(tmp, target)
    set_tree_writable(target, False)
    return target


def prune_snapshots(releases: Path, prefix: str, keep: Path | None = None, limit: int = SNAPSHOT_KEEP) -> int:
    """Delete all but the newest `limit` snapshots; `keep` (the live target) is never deleted."""
    if not releases.is_dir():
        return 0
    snaps = [p for p in releases.iterdir() if p.name.startswith(f"{prefix}-") and p.is_dir() and not p.is_symlink()]
    snaps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    protected = keep.resolve() if keep else None
    removed = 0
    for old in snaps[limit:]:
        if old.resolve() != protected:
            remove_tree(old)
            removed += 1
    return removed


def relink(link: Path, target: Path) -> None:
    """Swap a symlink atomically; a real directory is moved aside, never deleted."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() and not link.is_symlink():
        link.rename(link.with_name(f"{link.name}.bak.{timestamp()}"))
    tmp_link = link.with_name(f".{link.name}.tmp")
    tmp_link.unlink(missing_ok=True)
    tmp_link.symlink_to(target)
    os.replace(tmp_link, link)
