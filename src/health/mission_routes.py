"""Mission Control HTTP routes, mounted by health.livestream.Handler.

Kept separate so the livestream server stays small; every handler here is read-only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from health import mission_data, mission_project

HERE = Path(__file__).parent
MC_STATIC = {
    "mission.css": "text/css; charset=utf-8",
    "mission.js": "text/javascript; charset=utf-8",
    "mission_panels.js": "text/javascript; charset=utf-8",
}


class NotFound(LookupError):
    """Raised by a route when the requested project / file does not exist (-> 404)."""


def _first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return (query.get(key) or [default])[0]


def _project(query: dict[str, list[str]]) -> dict:
    detail = mission_project.project_detail(_first(query, "slug"))
    if detail is None:
        raise NotFound(f"unknown project: {_first(query, 'slug')!r}")
    return detail


def _sessions(query: dict[str, list[str]]) -> dict:
    try:
        rows = mission_data.list_sessions(_first(query, "project"), int(_first(query, "hours", "168")),
                                          int(_first(query, "limit", "40")))
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return {"sessions": rows}


def json_route(path: str, query: dict[str, list[str]], user: str | None, via: str | None) -> Callable[[], dict] | None:
    """Return a payload builder for a Mission Control JSON route, or None if not ours."""
    routes: dict[str, Callable[[], dict]] = {
        "/api/mc/projects": lambda: {"projects": mission_data.list_projects()},
        "/api/mc/project": lambda: _project(query),
        "/api/mc/sessions": lambda: _sessions(query),
        "/api/mc/whoami": lambda: {"user": user, "via": via},
    }
    return routes.get(path)


def cockpit_html(path: str) -> bytes:
    """Bytes of /cockpit/<slug> (the project's state.html); NotFound for anything else."""
    slug = path[len("/cockpit/"):]
    target = mission_project.cockpit_file(slug)
    if target is None:
        raise NotFound(f"no cockpit for {slug!r}")
    return target.read_bytes()


def page() -> bytes:
    return (HERE / "mission.html").read_bytes()
