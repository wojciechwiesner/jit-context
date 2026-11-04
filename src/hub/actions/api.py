"""HTTP payloads of hub action runs (routes live in health.hub_routes).

  POST /api/hub/actions {slug, action} -> 202 {run} queued; 400 bad body/action; 409 already queued or running
  GET  /api/hub/runs[?slug=]           -> {runs: [...] newest first, total, unreadable, max_concurrent, actions}
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from hub import actions
from hub.actions import run_store, runner

ACCEPTED = 202
CONFLICT = 409


class ActionRequestError(ValueError):
    """The client sent an unusable request (HTTP 400)."""


def parse_request(body: bytes) -> Tuple[str, str]:
    """(slug, action) from the JSON body, or ActionRequestError with the reason."""
    try:
        payload = json.loads(body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ActionRequestError(f"treść żądania nie jest JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ActionRequestError("oczekiwano obiektu JSON {slug, action}")
    slug, action = payload.get("slug"), payload.get("action")
    if not isinstance(slug, str) or not slug:
        raise ActionRequestError("brak pola slug")
    if action not in actions.ACTION_LABELS:
        raise ActionRequestError(f"nieznana akcja {action!r}; dozwolone: {', '.join(actions.ACTIONS)}")
    return slug, action


def start(entry: dict, action: str) -> Tuple[int, dict]:
    try:
        run = runner.default_runner().submit(entry, action)
    except runner.ActionBusy as exc:
        return CONFLICT, {"error": str(exc), "run": run_store.active_run(entry["slug"], action)}
    return ACCEPTED, {"run": run}


def runs_payload(slug: Optional[str]) -> dict:
    payload = run_store.list_runs(slug)
    payload["max_concurrent"] = runner.default_runner().max_concurrent
    payload["actions"] = [{"id": key, "label": label} for key, label in actions.ACTION_LABELS.items()]
    return payload
