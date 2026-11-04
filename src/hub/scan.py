"""`jit hub scan`: register every git repo under a root that carries a JIT marker; worktrees are skipped."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from hub import registry
from hub.gitinfo import resolve_repo

MARKER_FILES = (Path(".planning") / "STATE.md", Path(".planning") / "jit.json")
SKIP_DIR_NAMES = frozenset({"node_modules", "venv", "__pycache__", "dist", "build", "target", "vendor"})
MAX_SCAN_DEPTH = 4


@dataclass
class ScanReport:
    root: Path
    registered: List[dict] = field(default_factory=list)
    known: List[dict] = field(default_factory=list)
    skipped_worktrees: List[Path] = field(default_factory=list)
    unmarked_repos: int = 0
    git_errors: List[Path] = field(default_factory=list)


def _has_marker(directory: Path) -> bool:
    return any((directory / marker).is_file() for marker in MARKER_FILES)


def find_marked_repos(root: Path, max_depth: int = MAX_SCAN_DEPTH) -> Tuple[List[Path], int]:
    """Repo roots (dirs with .git) under root that have a marker, plus the count of repos without one.

    The walk does not descend into a repo once found, nor into hidden or dependency dirs.
    """
    root = Path(root).expanduser().resolve()
    marked: List[Path] = []
    unmarked = 0
    for current, dirs, _files in os.walk(root):
        here = Path(current)
        if (here / ".git").exists():
            dirs[:] = []
            if _has_marker(here):
                marked.append(here)
            else:
                unmarked += 1
            continue
        if len(here.relative_to(root).parts) >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES and not d.startswith("."))
    return marked, unmarked


def scan(root: Path, max_depth: int = MAX_SCAN_DEPTH) -> ScanReport:
    """Register the marked main repos under root; idempotent (a re-scan creates nothing new)."""
    report = ScanReport(root=Path(root).expanduser().resolve())
    candidates, report.unmarked_repos = find_marked_repos(report.root, max_depth)
    identities = []
    for candidate in candidates:
        identity = resolve_repo(candidate)
        if identity.git_common_dir is None:
            report.git_errors.append(candidate)
        elif identity.is_worktree:
            report.skipped_worktrees.append(candidate)
        else:
            identities.append(identity)
    for entry, created in registry.register_identities(identities):
        (report.registered if created else report.known).append(entry)
    return report
