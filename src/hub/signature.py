"""Freshness signature of a registered project: what the cockpit is built from.

Inputs: HEAD and branch of every worktree (`git worktree list --porcelain`), mtime and size of the planning
files in the main tree and in every linked worktree, and the mtime of the Obsidian dossier. Same inputs ->
same hex digest. A worktree's uncommitted STATE.md therefore changes the digest even when HEAD does not.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import config
from hub.gitinfo import _git_lines

PLANNING_FILES = ("STATE.md", "ROADMAP.md", "THOUGHTS.md", "ARCHITECTURE.mmd", "links.json")
WORKTREE_PREFIX = "worktree "
HEAD_PREFIX = "HEAD "
BRANCH_PREFIX = "branch "
DETACHED_MARKER = "detached"
# Same rules as detectProjectSlug() in cockpit/collect.js, so the dossier is the one the cockpit shows.
SSOT_RE = re.compile(r"\*\*SSOT w Obsidianie:\*\*\s*.*?projects/([a-zA-Z0-9_\-]+)\.md", re.I)
PROJECT_RE = re.compile(r"\*\*Projekt:\*\*\s*([a-zA-Z0-9_\-]+)", re.I)
WAVE_DIR_RE = re.compile(r"^W\d+$", re.I)
WT_SUFFIX_RE = re.compile(r"-wt$", re.I)


def list_worktrees(path: Path) -> List[Dict[str, Optional[str]]]:
    """[{path, head, branch}] for every worktree; empty outside git. A missing HEAD stays None."""
    lines = _git_lines(path, "worktree", "list", "--porcelain") or []
    worktrees: List[Dict[str, Optional[str]]] = []
    for line in lines:
        if line.startswith(WORKTREE_PREFIX):
            worktrees.append({"path": line[len(WORKTREE_PREFIX):], "head": None, "branch": None})
        elif worktrees and line.startswith(HEAD_PREFIX):
            worktrees[-1]["head"] = line[len(HEAD_PREFIX):].strip()
        elif worktrees and line.startswith(BRANCH_PREFIX):
            worktrees[-1]["branch"] = line[len(BRANCH_PREFIX):].strip()
        elif worktrees and line.strip() == DETACHED_MARKER:
            worktrees[-1]["branch"] = DETACHED_MARKER
    return worktrees


def _file_stamp(path: Path) -> Optional[List[int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return [stat.st_mtime_ns, stat.st_size]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def dossier_slug(project: Path) -> str:
    """Obsidian dossier name for `project`, mirroring the cockpit generator."""
    planning = project / ".planning"
    text = _read(planning / "STATE.md")
    for pattern, lower in ((SSOT_RE, False), (PROJECT_RE, True)):
        match = pattern.search(text)
        if match:
            slug = match.group(1).strip()
            return slug.lower() if lower else slug
    try:
        parsed = json.loads(_read(planning / "jit.json") or "{}")
    except ValueError:
        parsed = {}
    if isinstance(parsed, dict):
        for key in ("scope", "name"):
            if isinstance(parsed.get(key), str) and parsed[key]:
                return parsed[key]
    if WAVE_DIR_RE.match(project.name):
        return WT_SUFFIX_RE.sub("", project.parent.name)
    return project.name


def dossier_path(project: Path) -> Path:
    return Path(config.VAULT_DIR) / "projects" / f"{dossier_slug(project)}.md"


def _planning_stamps(root: Path) -> Dict[str, Optional[List[int]]]:
    planning = root / ".planning"
    return {name: _file_stamp(planning / name) for name in PLANNING_FILES}


def signature_inputs(project: Path) -> dict:
    """The raw inputs; kept separate from the digest so tests and logs can show what changed."""
    project = Path(project)
    worktrees = sorted(list_worktrees(project), key=lambda w: w["path"] or "")
    main = str(project.resolve())
    return {
        "worktrees": worktrees,
        "planning": _planning_stamps(project),
        "worktree_planning": {
            item["path"]: _planning_stamps(Path(item["path"]))
            for item in worktrees
            if item["path"] and str(Path(item["path"]).resolve()) != main
        },
        "dossier": _file_stamp(dossier_path(project)),
    }


def compute_signature(project: Path) -> str:
    payload = json.dumps(signature_inputs(project), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
