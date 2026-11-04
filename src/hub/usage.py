"""Usage collectors per project: Claude Code transcripts, Hermes sessions and JIT turn telemetry.

`collect_usage()` reads only what is new since the previous run (byte offsets, row ids, mtimes) into
<hub dir>/usage.sqlite and rebuilds the daily rollups when rows or the registry changed. Every source fails
open on its own: an error is reported in the result and the other sources still run. Nothing is estimated:
cost is only what Hermes recorded, a missing value stays NULL.

Project attribution: a cwd inside a registered project maps to its slug; a worktree maps to its main repo via
git (while it still exists); a JIT scope equal to a slug maps to it. Anything else keeps its raw path or scope
and is marked registered = 0.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from hub import registry
from hub import usage_store as store
from hub.gitinfo import resolve_repo
from hub.usage_claude import SOURCE as CLAUDE_SOURCE, collect as collect_claude
from hub.usage_dbs import HERMES_SOURCE, JIT_SOURCE, collect_hermes, collect_jit

CLAUDE_PROJECTS_ENV = "JIT_CLAUDE_PROJECTS_DIR"
HERMES_HOME_ENV = "HERMES_HOME"
JIT_STATE_ENV = "JIT_STATE_DIR"
HERMES_DB_NAME = "state.db"


@dataclass(frozen=True)
class UsageSources:
    claude_projects: Path
    hermes_db: Path
    jit_sessions: Path


@dataclass
class CollectResult:
    added: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, List[str]] = field(default_factory=dict)
    rollup_rows: Optional[int] = None


def default_sources() -> UsageSources:
    """Live locations, read from the environment per call (tests point them at a tmp HOME)."""
    hermes_home = Path(os.environ.get(HERMES_HOME_ENV) or Path.home() / ".hermes").expanduser()
    claude = os.environ.get(CLAUDE_PROJECTS_ENV) or Path.home() / ".claude" / "projects"
    state_dir = os.environ.get(JIT_STATE_ENV) or hermes_home / "state" / "ona-context"
    return UsageSources(Path(claude).expanduser(), hermes_home / HERMES_DB_NAME, Path(state_dir) / "sessions")


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


class ProjectResolver:
    """Maps a (path, scope) pair from session_days to (project, registered) using the registry."""

    def __init__(self, projects: List[dict]) -> None:
        self._roots = sorted(((Path(p["path"]), p["slug"]) for p in projects), key=lambda r: -len(str(r[0])))
        self._slugs = {p["slug"] for p in projects}
        self._cache: Dict[Tuple[Optional[str], Optional[str]], Tuple[Optional[str], bool]] = {}

    def _slug_for(self, path: Path) -> Optional[str]:
        return next((slug for root, slug in self._roots if _within(path, root)), None)

    def _resolve_path(self, raw: str) -> Optional[str]:
        path = Path(raw)
        slug = self._slug_for(path)
        if slug is None and path.is_absolute() and path.is_dir():
            slug = self._slug_for(resolve_repo(path).main_path)
        return slug

    def __call__(self, path: Optional[str], scope: Optional[str]) -> Tuple[Optional[str], bool]:
        key = (path, scope)
        if key not in self._cache:
            slug = self._resolve_path(path) if path else None
            if slug is None and scope in self._slugs:
                slug = scope
            self._cache[key] = (slug, True) if slug else (path or scope, False)
        return self._cache[key]


def _registry_signature(projects: List[dict]) -> str:
    return json.dumps(sorted((p["slug"], p["path"]) for p in projects))


def _run_source(result: CollectResult, source: str, reader: Callable[[], Tuple[int, List[str]]]) -> None:
    """Fail-open wrapper: any exception becomes an error entry for this source only."""
    try:
        added, errors = reader()
    except Exception as exc:  # noqa: BLE001 - one broken source must not stop the others
        result.added[source] = 0
        result.errors[source] = [f"{type(exc).__name__}: {exc}"]
        return
    result.added[source] = added
    if errors:
        result.errors[source] = errors


def collect_usage(sources: Optional[UsageSources] = None, db_path: Optional[Path] = None,
                  projects: Optional[List[dict]] = None) -> CollectResult:
    """Ingest new usage from every source and refresh daily rollups when something changed."""
    sources = sources or default_sources()
    projects = registry.load_projects() if projects is None else projects
    known_paths = [p["path"] for p in projects]
    result = CollectResult()
    conn = store.connect(db_path)
    try:
        _run_source(result, CLAUDE_SOURCE, lambda: collect_claude(conn, sources.claude_projects, known_paths))
        _run_source(result, HERMES_SOURCE, lambda: (collect_hermes(conn, sources.hermes_db), []))
        _run_source(result, JIT_SOURCE, lambda: collect_jit(conn, sources.jit_sessions))
        signature = _registry_signature(projects)
        if any(result.added.values()) or store.get_meta(conn, store.META_REGISTRY_KEY) != signature:
            with conn:
                result.rollup_rows = store.rebuild_daily(conn, ProjectResolver(projects))
                store.set_meta(conn, store.META_REGISTRY_KEY, signature)
    finally:
        conn.close()
    return result


def daily_usage(project: Optional[str] = None, days: Optional[int] = None,
                db_path: Optional[Path] = None) -> List[dict]:
    """Daily rollup rows (one per day, source and project), optionally for one project and the last N days."""
    since = (date.today() - timedelta(days=days - 1)).isoformat() if days else None
    conn = store.connect(db_path)
    try:
        return store.read_daily(conn, project=project, since=since)
    finally:
        conn.close()
