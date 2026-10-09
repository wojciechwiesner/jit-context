"""Mission Control data: projects, project detail (cockpit) and session history.

Read-only. Cockpit data comes from the canonical cockpit generator
(~/Documents/Wojciech/templates/sota-starter/cockpit/export.js) so Mission Control and
.planning/state.html always show the same thing. Spec: docs/MISSION_CONTROL.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from health.livestream_session import _ro

HOME = Path.home()
PROJECTS_ROOT = Path(os.environ.get("JIT_MC_PROJECTS_ROOT", HOME / "Projects" / "active"))
COCKPIT_EXPORT = Path(os.environ.get(
    "JIT_MC_COCKPIT_EXPORT", HOME / "Documents/Wojciech/templates/sota-starter/cockpit/export.js"))
OBSIDIAN_PROJECTS = Path(os.environ.get("JIT_MC_OBSIDIAN_PROJECTS", HOME / "Documents/Wojciech/projects"))
LIST_CACHE_S = 20.0
DETAIL_CACHE_S = 10.0
LIVE_WINDOW_S = 120
WEEK_S = 7 * 86400
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
OPEN_TASK_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+", re.M)
BLOCKERS_RE = re.compile(r"^#+\s*Blocker[s]?[^\n]*\n(.*?)(?=^#+\s|\Z)", re.M | re.S | re.I)

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, build):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = build()
    _cache[key] = (time.time(), value)
    return value


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _last_commit(path: Path) -> dict[str, str] | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%h|%s|%cI"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not out:
        return None
    commit_hash, msg, iso = (out.split("|", 2) + ["", ""])[:3]
    return {"hash": commit_hash, "msg": msg, "iso": iso}


def _blockers(state_md: str) -> list[str]:
    match = BLOCKERS_RE.search(state_md)
    if not match:
        return []
    items = [ln.strip().lstrip("-*").strip() for ln in match.group(1).splitlines()]
    return [i for i in items if i and not re.match(r"^\(?(brak|none|n/a)\)?\.?$", i, re.I)]


def _iso_to_unix(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return 0.0


# --- sessions ---------------------------------------------------------------------

SESSION_SQL = """
SELECT s.id, s.title, s.source, s.model, s.started_at, s.cwd,
       s.message_count AS messages, s.tool_call_count AS tools,
       (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = s.id) AS last_activity
FROM sessions s
WHERE s.started_at >= ? {where}
ORDER BY COALESCE(last_activity, s.started_at) DESC
LIMIT ?
"""


def _session_rows(since: float, limit: int, cwd_prefix: str | None) -> list[dict[str, Any]]:
    where, params = "", [since]
    if cwd_prefix:
        where = "AND (s.cwd = ? OR s.cwd LIKE ? ESCAPE '\\')"
        escaped = cwd_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params += [cwd_prefix, escaped + "/%"]
    with _ro() as con:
        rows = con.execute(SESSION_SQL.format(where=where), [*params, limit]).fetchall()
    now = time.time()
    return [{**dict(r), "live": bool(r["last_activity"] and now - r["last_activity"] < LIVE_WINDOW_S),
             "live_url": f"/live?session={r['id']}"} for r in rows]


def list_sessions(project: str | None, hours: int = 168, limit: int = 40) -> list[dict[str, Any]]:
    hours = max(1, min(int(hours), 2160))
    limit = max(1, min(int(limit), 200))
    prefix = None
    if project:
        match = _project_path(project)
        if match is None:
            raise KeyError(f"unknown project: {project}")
        prefix = str(match)
    return _session_rows(time.time() - hours * 3600, limit, prefix)


def _sessions_7d_by_project(paths: list[Path]) -> dict[str, int]:
    counts = {str(p): 0 for p in paths}
    with _ro() as con:
        rows = con.execute("SELECT cwd FROM sessions WHERE started_at >= ? AND cwd IS NOT NULL",
                           (time.time() - WEEK_S,)).fetchall()
    for (cwd,) in rows:
        for root in counts:
            if cwd == root or cwd.startswith(root + "/"):
                counts[root] += 1
                break
    return counts


# --- projects ---------------------------------------------------------------------

def _project_dirs() -> list[Path]:
    try:
        return sorted(p for p in PROJECTS_ROOT.iterdir()
                      if p.is_dir() and not p.name.startswith(".") and (p / ".planning").is_dir())
    except OSError:
        return []


def _project_path(slug: str) -> Path | None:
    if not SLUG_RE.match(slug or ""):
        return None
    return next((p for p in _project_dirs() if p.name == slug), None)


def _summary(path: Path, sessions_7d: int) -> dict[str, Any]:
    state_md = _read(path / ".planning" / "STATE.md")
    commit = _last_commit(path)
    return {
        "slug": path.name, "path": str(path), "title": path.name,
        "last_commit": commit,
        "open_tasks": len(OPEN_TASK_RE.findall(state_md)),
        "blockers": len(_blockers(state_md)),
        "sessions_7d": sessions_7d,
        "last_activity": _iso_to_unix(commit["iso"] if commit else None),
    }


def list_projects() -> list[dict[str, Any]]:
    def build() -> list[dict[str, Any]]:
        dirs = _project_dirs()
        try:
            counts = _sessions_7d_by_project(dirs)
        except Exception:  # state.db missing must not hide the project list
            counts = {}
        projects = [_summary(p, counts.get(str(p), 0)) for p in dirs]
        return sorted(projects, key=lambda p: (p["sessions_7d"] > 0, p["last_activity"]), reverse=True)
    return _cached("projects", LIST_CACHE_S, build)
