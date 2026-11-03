"""Git identity of a project directory: worktrees resolve to the main working tree."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

GIT_TIMEOUT_SECONDS = 10
WORKTREE_PREFIX = "worktree "
BARE_MARKER = "bare"


@dataclass(frozen=True)
class RepoIdentity:
    """main_path: the project path in the main working tree; git_common_dir: None outside git."""

    main_path: Path
    git_common_dir: Optional[Path]
    is_worktree: bool


def _git_lines(path: Path, *args: str) -> Optional[List[str]]:
    try:
        res = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.splitlines()


def _absolute(base: Path, raw: str) -> Path:
    candidate = Path(raw)
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _main_worktree(path: Path) -> Optional[Path]:
    """First entry of `git worktree list --porcelain`, unless the repository is bare."""
    lines = _git_lines(path, "worktree", "list", "--porcelain") or []
    if not lines or not lines[0].startswith(WORKTREE_PREFIX):
        return None
    if len(lines) > 1 and lines[1].strip() == BARE_MARKER:
        return None
    return Path(lines[0][len(WORKTREE_PREFIX):]).resolve()


def resolve_repo(path: Path) -> RepoIdentity:
    """Identity of `path`. A subdirectory keeps its offset, so a worktree subdir maps to the main subdir."""
    path = Path(path).expanduser().resolve()
    lines = _git_lines(path, "rev-parse", "--show-toplevel", "--git-dir", "--git-common-dir")
    if not lines or len(lines) < 3:
        return RepoIdentity(path, None, False)
    toplevel = Path(lines[0]).resolve()
    git_dir, common_dir = _absolute(path, lines[1]), _absolute(path, lines[2])
    is_worktree = git_dir != common_dir
    main_root = (_main_worktree(path) or toplevel) if is_worktree else toplevel
    try:
        offset = path.relative_to(toplevel)
    except ValueError:
        offset = Path()
    return RepoIdentity((main_root / offset).resolve(), common_dir, is_worktree)
