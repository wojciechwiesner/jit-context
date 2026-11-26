"""Operator Wall HTTP glue: page, assets, GET /api/mc/wall and POST /api/mc/charters/approve."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from health import hub_routes, wall_charter_edit, wall_charters, wall_data, wall_external

HERE = Path(__file__).parent
WALL_STATIC = {
    "wall.css": "text/css; charset=utf-8",
    "wall.js": "text/javascript; charset=utf-8",
    "wall_review.js": "text/javascript; charset=utf-8",
    "wall_theme.js": "text/javascript; charset=utf-8",
    "wall_insights.js": "text/javascript; charset=utf-8",
}
WALL_PAGE = "/wall"
WALL_API = "/api/mc/wall"
APPROVE_ROUTE = "/api/mc/charters/approve"
UPDATE_ROUTE = "/api/mc/charters/update"
JSON_TYPE = "application/json"
Reply = hub_routes.Reply


def json_route(path: str) -> Callable[[], dict] | None:
    return wall_data.build_wall if path == WALL_API else None


def page() -> bytes:
    """wall.html with the CSRF meta tag, so the approve POST can pass the same guard as the hub."""
    wall_external.prewarm()
    return hub_routes.with_csrf((HERE / "wall.html").read_bytes())


def _reply(code: int, payload: dict) -> Reply:
    return code, json.dumps(payload, ensure_ascii=False).encode(), JSON_TYPE


def handle_post(path: str, headers, port: int, body: bytes) -> Optional[Reply]:
    """Reply for the approve/update routes (Origin + CSRF guarded), or None when the path is not ours."""
    if path not in (APPROVE_ROUTE, UPDATE_ROUTE):
        return None
    denied = hub_routes.post_guard(headers, port)
    if denied is not None:
        return denied
    try:
        request = json.loads(body or b"{}")
        if not isinstance(request, dict):
            raise wall_charters.CharterError("oczekiwany obiekt JSON")
        if path == UPDATE_ROUTE:
            return _reply(200, wall_charter_edit.update(request))
        return _reply(200, wall_charters.approve(request.get("slugs"), request.get("audience") or {}))
    except wall_charters.CharterError as exc:
        return _reply(exc.code, {"error": str(exc)})
    except ValueError as exc:
        return _reply(400, {"error": f"zły JSON: {exc}"})
    except Exception as exc:  # surface the real error
        return _reply(500, {"error": f"{type(exc).__name__}: {exc}"})
