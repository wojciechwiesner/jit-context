"""Project Hub HTTP routes, mounted by health.livestream.Handler (Mission Control server, port 8767).

  GET  /hub                     -> the hub page (hub.html + CSRF meta); hub.js / hub.css are served from /static/
  GET  /api/hub/projects        -> every registered project with freshness, activity, tasks, tokens, advice
  GET  /api/hub/version?slug=   -> built_at + signature of the last recorded build (polled by cockpits)
  GET  /hub/<slug>              -> the freshest cockpit (hub copy or repo .planning/state.html) + CSRF meta tag
                                   + chat config meta tags (endpoint, slug) read by the cockpit "Czat" tab
                                   + action endpoints meta tags read by the cockpit "Akcje" tab
  POST /api/hub/refresh?slug=   -> rebuild the cockpit now (stats first), synchronous
  GET  /api/hub/chat?slug=      -> the project's chat history
  POST /api/hub/chat            -> {slug, messages} -> model reply grounded in the project's files (hub.chat)
  POST /api/hub/actions         -> {slug, action} -> 202, a queued read-only agent run (hub.actions.api)
  GET  /api/hub/runs[?slug=]    -> action runs, newest first, optionally for one project
  GET  /api/hub/report?run=     -> markdown of a run's report (read from the hub reports dir only)

Access to every route goes through health.mission_access first (livestream does that). POST routes also need
an allowed Origin header and the per-process CSRF token from the hub page (`<meta name="jit-hub-csrf">`) in the
X-JIT-Hub-CSRF header: a custom header cannot be sent cross-site without CORS, and this server sends none.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
from html import escape as html_escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from health.mission_access import HeaderLookup
from health.mission_routes import NotFound
from hub import chat, chat_history, overview, refresher, registry
from hub.actions import api as actions_api
from l1.cockpit_sync import COCKPIT_FILE

Reply = Tuple[int, bytes, str]

JSON_TYPE = "application/json"
HTML_TYPE = "text/html; charset=utf-8"
HUB_PAGE_ROUTE = "/hub"
HUB_PAGE_PREFIX = "/hub/"
HUB_PAGE_FILE = Path(__file__).parent / "hub.html"
HUB_STATIC = {"hub.css": "text/css; charset=utf-8", "hub.js": "text/javascript; charset=utf-8"}
PROJECTS_ROUTE = "/api/hub/projects"
VERSION_ROUTE = "/api/hub/version"
REFRESH_ROUTE = "/api/hub/refresh"
CHAT_ROUTE = "/api/hub/chat"
ACTIONS_ROUTE = "/api/hub/actions"
RUNS_ROUTE = "/api/hub/runs"
REPORT_ROUTE = "/api/hub/report"
POST_PREFIX = "/api/hub/"
CSRF_HEADER = "X-JIT-Hub-CSRF"
CSRF_META_NAME = "jit-hub-csrf"
CHAT_META_NAME = "jit-hub-chat"
SLUG_META_NAME = "jit-hub-slug"
ACTIONS_META_NAME = "jit-hub-actions"
RUNS_META_NAME = "jit-hub-runs"
REPORT_META_NAME = "jit-hub-report"
CSRF_TOKEN_BYTES = 32
ORIGINS_ENV = "JIT_HUB_ALLOWED_ORIGINS"
DEFAULT_EXTRA_ORIGINS = "https://live.borg.tools"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
MAX_POST_BODY_BYTES = 65536
HEAD_TAG_RE = re.compile(rb"<head(\s[^>]*)?>", re.I)

_CSRF_TOKEN = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
_REFRESH_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _json(code: int, payload: dict) -> Reply:
    return code, json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8"), JSON_TYPE


def _first(query: Dict[str, List[str]], key: str) -> str:
    return (query.get(key) or [""])[0]


def csrf_token() -> str:
    """Token of this server process; a restart invalidates pages opened before it."""
    return _CSRF_TOKEN


def csrf_meta() -> str:
    return f'<meta name="{CSRF_META_NAME}" content="{csrf_token()}">'


def allowed_origins(port: int) -> set:
    """Loopback origins of this server's port plus $JIT_HUB_ALLOWED_ORIGINS (default: the Borg SSO proxy)."""
    extra = os.environ.get(ORIGINS_ENV, DEFAULT_EXTRA_ORIGINS)
    origins = {f"http://{host}:{port}" for host in LOOPBACK_HOSTS}
    origins.update(item.strip().rstrip("/").lower() for item in extra.split(",") if item.strip())
    return origins


def post_guard(headers: HeaderLookup, port: int) -> Optional[Reply]:
    """403 reply when the Origin is not allowed or the CSRF token is missing/wrong; None when the POST may run."""
    origin = (headers.get("Origin") or "").strip().rstrip("/").lower()
    if not origin or origin not in allowed_origins(port):
        return _json(403, {"error": f"origin not allowed: {origin or '(brak nagłówka Origin)'}"})
    token = (headers.get(CSRF_HEADER) or "").strip()
    if not token or not hmac.compare_digest(token.encode("utf-8"), csrf_token().encode("utf-8")):
        return _json(403, {"error": f"brak lub zły token CSRF w nagłówku {CSRF_HEADER}"})
    return None


def find_project(slug: str) -> dict:
    """Registry entry by slug; slugs never become paths, so traversal is impossible."""
    if slug:
        for entry in registry.load_projects():
            if entry.get("slug") == slug:
                return entry
    raise NotFound(f"unknown project: {slug!r}")


def projects_payload() -> dict:
    rows = []
    for entry in registry.load_projects():
        try:
            rows.append(overview.project_summary(entry))
        except Exception as exc:  # one broken project must not hide the others
            rows.append({"slug": entry.get("slug"), "path": entry.get("path"),
                         "error": f"{type(exc).__name__}: {exc}"})
    return {"generated_at": time.time(), "registry": str(registry.registry_path()), "projects": rows}


def freshest_cockpit(entry: dict) -> Optional[Path]:
    """Newest existing cockpit file of the project: the hub copy or the repo's .planning/state.html."""
    candidates = [refresher.hub_cockpit_path(entry["slug"]), Path(entry["path"]) / COCKPIT_FILE]
    existing = [path for path in candidates if path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime) if existing else None


def chat_meta(slug: str) -> str:
    """Chat endpoint + project slug for the cockpit served at /hub/<slug> (cockpit/hub_chat.js reads them)."""
    return (f'<meta name="{CHAT_META_NAME}" content="{CHAT_ROUTE}">'
            f'<meta name="{SLUG_META_NAME}" content="{html_escape(slug, quote=True)}">')


def actions_meta() -> str:
    """Action endpoints for the cockpit "Akcje" tab (cockpit/hub_actions.js reads them, slug from chat_meta)."""
    return (f'<meta name="{ACTIONS_META_NAME}" content="{ACTIONS_ROUTE}">'
            f'<meta name="{RUNS_META_NAME}" content="{RUNS_ROUTE}">'
            f'<meta name="{REPORT_META_NAME}" content="{REPORT_ROUTE}">')


def with_csrf(html: bytes, extra_meta: str = "") -> bytes:
    """Insert the CSRF meta tag (and extra_meta) right after <head>, or in front of the document without head."""
    meta = (csrf_meta() + extra_meta).encode("utf-8")
    match = HEAD_TAG_RE.search(html)
    if match is None:
        return meta + html
    return html[:match.end()] + meta + html[match.end():]


def cockpit_page(path: str) -> Reply:
    entry = find_project(unquote(path[len(HUB_PAGE_PREFIX):]))
    target = freshest_cockpit(entry)
    if target is None:
        raise NotFound(f"no cockpit for {entry['slug']!r}: run POST {REFRESH_ROUTE}?slug={entry['slug']}")
    return 200, with_csrf(target.read_bytes(), chat_meta(entry["slug"]) + actions_meta()), HTML_TYPE


def hub_page() -> Reply:
    return 200, with_csrf(HUB_PAGE_FILE.read_bytes()), HTML_TYPE


def _get(path: str, query: Dict[str, List[str]]) -> Optional[Reply]:
    if path == HUB_PAGE_ROUTE:
        return hub_page()
    if path == PROJECTS_ROUTE:
        return _json(200, projects_payload())
    if path == VERSION_ROUTE:
        return _json(200, overview.version(find_project(_first(query, "slug"))["slug"]))
    if path == CHAT_ROUTE:
        return _json(200, chat_history.load(find_project(_first(query, "slug"))["slug"]))
    if path == RUNS_ROUTE:
        slug = _first(query, "slug")
        return _json(200, actions_api.runs_payload(find_project(slug)["slug"] if slug else None))
    if path == REPORT_ROUTE:
        return _json(*actions_api.report_payload(_first(query, "run")))
    if path.startswith(HUB_PAGE_PREFIX) and "/" not in path[len(HUB_PAGE_PREFIX):]:
        return cockpit_page(path)
    return None


def handle_get(path: str, query: Dict[str, List[str]]) -> Optional[Reply]:
    """Reply for a hub GET route, or None when the path is not a hub route."""
    try:
        return _get(path, query)
    except NotFound as exc:
        return _json(404, {"error": str(exc)})
    except Exception as exc:  # surface the real error, never a fake payload
        return _json(500, {"error": f"{type(exc).__name__}: {exc}"})


def _slug_lock(slug: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _REFRESH_LOCKS.setdefault(slug, threading.Lock())


def refresh(slug: str) -> Reply:
    entry = find_project(slug)
    lock = _slug_lock(entry["slug"])
    if not lock.acquire(blocking=False):
        return _json(409, {"error": f"przebudowa {entry['slug']} już trwa"})
    try:
        result = refresher.refresh_project(entry, force=True)
    finally:
        lock.release()
    payload = dict(overview.version(entry["slug"]), status=result.status, detail=result.detail)
    return _json(500 if result.status == refresher.FAILED else 200, payload)


def chat_turn(body: bytes) -> Reply:
    try:
        slug, messages = chat.parse_request(body)
    except chat.ChatRequestError as exc:
        return _json(400, {"error": str(exc)})
    return _json(*chat.run_chat(find_project(slug), messages))


def action_run(body: bytes) -> Reply:
    try:
        slug, action = actions_api.parse_request(body)
    except actions_api.ActionRequestError as exc:
        return _json(400, {"error": str(exc)})
    return _json(*actions_api.start(find_project(slug), action))


def handle_post(path: str, query: Dict[str, List[str]], headers: HeaderLookup, port: int,
                body: bytes = b"") -> Optional[Reply]:
    """Reply for a hub POST route (guarded by Origin + CSRF), or None when the path is not a hub route."""
    if not path.startswith(POST_PREFIX):
        return None
    denied = post_guard(headers, port)
    if denied is not None:
        return denied
    try:
        if path == REFRESH_ROUTE:
            return refresh(_first(query, "slug"))
        if path == CHAT_ROUTE:
            return chat_turn(body)
        if path == ACTIONS_ROUTE:
            return action_run(body)
    except NotFound as exc:
        return _json(404, {"error": str(exc)})
    except Exception as exc:
        return _json(500, {"error": f"{type(exc).__name__}: {exc}"})
    return _json(404, {"error": f"not found: {path}"})
