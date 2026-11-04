"""Hub row extras: the project's git worktrees and its Obsidian dossier link.

The dossier name follows the cockpit generator (cockpit/collect.js detectProjectSlug): the "SSOT w Obsidianie"
line of STATE.md, then "**Projekt:**", then .planning/jit.json scope/name, then the directory name. The vault is
not read here (launchd has no TCC access to ~/Documents), so the link says where the note should be, not that
it exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from hub.gitinfo import WORKTREE_PREFIX, _git_lines

OBSIDIAN_VAULT = "Wojciech"
OBSIDIAN_FOLDER = "projects"
STATE_RELATIVE = Path(".planning") / "STATE.md"
JIT_JSON_RELATIVE = Path(".planning") / "jit.json"
SSOT_RE = re.compile(r"\*\*SSOT w Obsidianie:\*\*\s*.*?projects/([a-zA-Z0-9_\-]+)\.md", re.I)
PROJECT_RE = re.compile(r"\*\*Projekt:\*\*\s*([a-zA-Z0-9_\-]+)", re.I)
BRANCH_REF_PREFIX = "refs/heads/"
MAX_WORKTREES = 30
FIELD_SEPARATOR = "\x1f"
LAST_COMMIT_FORMAT = FIELD_SEPARATOR.join(("%cI", "%h", "%s"))


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _jit_json_name(path: Path) -> Optional[str]:
    raw = _read(path / JIT_JSON_RELATIVE)
    try:
        doc = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    value = doc.get("scope") or doc.get("name")
    return str(value) if value else None


def dossier(path: Path) -> dict:
    """Name, source and obsidian:// URI of the project's note in the vault."""
    text = _read(path / STATE_RELATIVE) or ""
    ssot, project = SSOT_RE.search(text), PROJECT_RE.search(text)
    jit_name = None if ssot or project else _jit_json_name(path)
    if ssot:
        name, source = ssot.group(1).strip(), "STATE.md: SSOT w Obsidianie"
    elif project:
        name, source = project.group(1).strip().lower(), "STATE.md: Projekt"
    elif jit_name:
        name, source = jit_name, str(JIT_JSON_RELATIVE)
    else:
        name, source = path.name, "nazwa katalogu"
    note = f"{OBSIDIAN_FOLDER}/{name}.md"
    uri = f"obsidian://open?vault={quote(OBSIDIAN_VAULT)}&file={quote(note, safe='')}"
    return {"name": name, "note": note, "source": source, "uri": uri}


def _parse_porcelain(lines: List[str]) -> List[dict]:
    entries: List[dict] = []
    for line in lines:
        if line.startswith(WORKTREE_PREFIX):
            entries.append({"path": line[len(WORKTREE_PREFIX):], "branch": None, "head": None, "detached": False})
        elif not entries:
            continue
        elif line.startswith("HEAD "):
            entries[-1]["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            entries[-1]["branch"] = ref[len(BRANCH_REF_PREFIX):] if ref.startswith(BRANCH_REF_PREFIX) else ref
        elif line == "detached":
            entries[-1]["detached"] = True
        elif line == "bare":
            entries[-1]["bare"] = True
    return entries


def _last_commit(path: str) -> dict:
    lines = _git_lines(Path(path), "log", "-1", f"--format={LAST_COMMIT_FORMAT}")
    if lines is None:
        return {"error": "git log nie powiodło się (worktree usunięty?)"}
    if not lines or not lines[0].strip():
        return {"missing": "brak commitów"}
    at, sha, subject = (lines[0].split(FIELD_SEPARATOR) + ["", "", ""])[:3]
    return {"at": at, "sha": sha, "subject": subject}


def worktrees(path: Path) -> dict:
    """Linked worktrees of the project's repository (the main working tree itself is left out)."""
    lines = _git_lines(path, "worktree", "list", "--porcelain")
    if lines is None:
        return {"error": "git worktree list nie powiodło się (brak repozytorium git?)"}
    entries = [entry for entry in _parse_porcelain(lines)[1:] if not entry.get("bare")]
    items = []
    for entry in entries[:MAX_WORKTREES]:
        items.append(dict(entry, last_commit=_last_commit(entry["path"])))
    return {"count": len(entries), "items": items}
