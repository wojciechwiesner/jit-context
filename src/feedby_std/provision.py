"""Provision Feedby for one repo: Feedby project + widget key + managed snippet in mount files.

Order (each step idempotent, re-run safe):
1. reuse the stored key for this slug if Feedby still has it active, else mint a new one;
2. ensure the Feedby project exists (insert on conflict do nothing);
3. inject the snippet into every mount file (marker block replaced in place);
4. commit only the mount files (pathspec commit; other dirty files are never staged).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from feedby_std import keys, remote, snippet, store

COMMIT_TRAILER = "Developed by Wojciech Wiesner wojciech@theones.io -= join.theones.io =- be The One Who Is Many -"
KEY_LABEL = "jit-feedby"


@dataclass
class ProvisionResult:
    slug: str
    repo: str
    project_id: str = ""
    project_created: bool = False
    key_mask: str = ""
    key_reused: bool = False
    mounts_changed: List[str] = field(default_factory=list)
    commit: str = ""
    dry_run: bool = False
    notes: List[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _resolve_key(slug: str) -> tuple[str, bool]:
    stored = store.get(slug)
    if stored and keys.is_valid_key(stored.get("key", "")):
        if remote.key_is_live(stored["key_hash"]) == slug:
            return stored["key"], True
    return keys.generate_widget_key(), False


def _apply_mounts(repo: Path, mounts: List[str], key: str, locale: str, dry_run: bool) -> List[str]:
    changed = []
    for rel in mounts:
        path = repo / rel
        before = path.read_text(encoding="utf-8")
        after = snippet.inject(before, snippet.kind_for(rel), key, locale)
        if after != before:
            changed.append(rel)
            if not dry_run:
                path.write_text(after, encoding="utf-8")
    return changed


def _commit(repo: Path, paths: List[str], slug: str) -> str:
    message = (
        f"chore(feedby): install Feedby widget (project {slug})\n\n"
        "- managed snippet between feedby:start/feedby:end markers, written by `jit feedby provision`\n"
        "- public widget key bound to the Feedby project of this repo\n\n"
        f"{COMMIT_TRAILER}\n"
    )
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", message, "--", *paths)
    return _git(repo, "rev-parse", "--short", "HEAD")


def provision(repo: Path, slug: str, name: str, mounts: List[str], locale: str = "pl",
              dry_run: bool = False, commit: bool = True) -> ProvisionResult:
    remote.check_slug(slug)
    result = ProvisionResult(slug=slug, repo=str(repo), dry_run=dry_run)
    for rel in mounts:
        if _git(repo, "status", "--porcelain", "--", rel):
            raise RuntimeError(f"{rel} has uncommitted changes; commit or stash them first")
    key, reused = _resolve_key(slug)
    result.key_mask, result.key_reused = keys.mask(key), reused
    if dry_run:
        found = remote.find_project(slug)
        result.project_id = found["id"] if found else "(would create)"
        result.mounts_changed = _apply_mounts(repo, mounts, key, locale, dry_run=True)
        return result
    project = remote.ensure_project(slug, name)
    result.project_id, result.project_created = project["id"], project["created"] == "1"
    if not reused:
        remote.insert_widget_key(project["id"], keys.hash_widget_key(key), KEY_LABEL)
        store.save_entry(slug, {
            "project_id": project["id"], "key": key, "key_hash": keys.hash_widget_key(key),
            "repo": str(repo), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    result.mounts_changed = _apply_mounts(repo, mounts, key, locale, dry_run=False)
    if not mounts:
        result.notes.append("no UI mount: Feedby project + key only")
    if commit and result.mounts_changed:
        result.commit = _commit(repo, result.mounts_changed, slug)
    return result


def lookup_existing(key_plaintext: str) -> Optional[str]:
    """Feedby slug owning an already-installed key (for repos that had Feedby before this tool)."""
    return remote.key_is_live(keys.hash_widget_key(key_plaintext))
