"""Project registry: <hub dir>/projects.json, one entry per project (worktrees map to their main repo).

Writes are atomic (temp file + os.replace) and serialised with an exclusive lock on a sidecar file.
An unreadable registry is moved aside to projects.json.corrupt-<timestamp> and rebuilt from scratch.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import config
from hub.gitinfo import RepoIdentity, resolve_repo

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX hosts run without the lock
    fcntl = None  # type: ignore[assignment]

REGISTRY_FILE_NAME = "projects.json"
LOCK_SUFFIX = ".lock"
CORRUPT_SUFFIX = ".corrupt-"
REGISTRY_VERSION = 1
DEFAULT_SLUG = "project"
FIRST_SLUG_SUFFIX = 2


def registry_path() -> Path:
    return config.hub_dir() / REGISTRY_FILE_NAME


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + LOCK_SUFFIX, "a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _valid_entry(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("slug"), str) and bool(entry["slug"])
        and isinstance(entry.get("path"), str) and bool(entry["path"])
    )


def _parse(raw: bytes) -> Optional[List[dict]]:
    """Entries, or None when the file is not a valid registry."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list) or not all(_valid_entry(e) for e in projects):
        return None
    return [dict(e) for e in projects]


def _backup_corrupt(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}{CORRUPT_SUFFIX}{stamp}")
    counter = FIRST_SLUG_SUFFIX
    while backup.exists():
        backup = path.with_name(f"{path.name}{CORRUPT_SUFFIX}{stamp}-{counter}")
        counter += 1
    os.replace(path, backup)
    print(f"jit hub: uszkodzony rejestr przeniesiony do {backup}, budowany od nowa", file=sys.stderr)
    return backup


def _write_unlocked(path: Path, entries: List[dict]) -> None:
    payload = json.dumps({"version": REGISTRY_VERSION, "projects": entries}, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_unlocked(path: Path) -> List[dict]:
    """Current entries. A corrupt file is backed up and replaced by an empty registry."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    entries = _parse(raw)
    if entries is None:
        _backup_corrupt(path)
        _write_unlocked(path, [])
        return []
    return entries


def load_projects() -> List[dict]:
    """All registry entries (empty list when the registry does not exist yet)."""
    path = registry_path()
    with _locked(path):
        return _read_unlocked(path)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or DEFAULT_SLUG


def _unique_slug(base: str, taken: set) -> str:
    slug, counter = base, FIRST_SLUG_SUFFIX
    while slug in taken:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _upsert(entries: List[dict], identity: RepoIdentity, from_init: bool, now: str) -> Tuple[dict, bool]:
    path_str = str(identity.main_path)
    common = str(identity.git_common_dir) if identity.git_common_dir else None
    for entry in entries:
        if entry["path"] == path_str:
            if common:
                entry["git_common_dir"] = common
            if from_init:
                entry["last_init_at"] = now
            return entry, False
    entry = {
        "slug": _unique_slug(_slugify(identity.main_path.name), {e["slug"] for e in entries}),
        "path": path_str,
        "git_common_dir": common,
        "added_at": now,
        "last_init_at": now if from_init else None,
    }
    entries.append(entry)
    return entry, True


def register_identities(identities: Sequence[RepoIdentity], from_init: bool = False) -> List[Tuple[dict, bool]]:
    """Add or refresh entries. Returns (entry, created) per identity; writes only when something changed."""
    path = registry_path()
    with _locked(path):
        entries = _read_unlocked(path)
        before = json.dumps(entries, sort_keys=True)
        now = _now()
        results = [_upsert(entries, identity, from_init, now) for identity in identities]
        if not path.exists() or json.dumps(entries, sort_keys=True) != before:
            _write_unlocked(path, entries)
    return [(dict(entry), created) for entry, created in results]


def register_project(path: Path, from_init: bool = False) -> Tuple[dict, bool]:
    """Register one project directory; a worktree resolves to (and updates) its main repo entry."""
    return register_identities([resolve_repo(path)], from_init=from_init)[0]
