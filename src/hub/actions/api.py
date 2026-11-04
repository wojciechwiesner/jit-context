"""HTTP payloads of hub action runs (routes live in health.hub_routes).

  POST /api/hub/actions {slug, action} -> 202 {run} queued; 400 bad body/action; 409 already queued or running
  GET  /api/hub/runs[?slug=]           -> {runs: [...] newest first, total, unreadable, max_concurrent, actions}
  GET  /api/hub/report?run=            -> {run, markdown, path}; 404 unknown run / no report, 403 file outside
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

from hub import actions
from hub.actions import report, run_store, runner

OK = 200
ACCEPTED = 202
FORBIDDEN = 403
NOT_FOUND = 404
CONFLICT = 409
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}-[a-z0-9]+-[0-9a-f]+$")
MAX_REPORT_BYTES = 2 * 1024 * 1024


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


def report_payload(run_id: str) -> Tuple[int, dict]:
    """Markdown of a run's report. Only files under the hub reports dir of the run's project are read."""
    if not RUN_ID_RE.match(run_id or ""):
        return NOT_FOUND, {"error": f"nieprawidłowy identyfikator uruchomienia: {run_id!r}"}
    run = run_store.load(run_id)
    if run is None:
        return NOT_FOUND, {"error": f"nie ma uruchomienia {run_id}"}
    if not run.get("report_path"):
        return NOT_FOUND, {"error": f"uruchomienie {run_id} nie ma raportu (status: {run.get('status')})", "run": run}
    path = Path(run["report_path"]).resolve()
    if report.reports_dir(str(run.get("slug") or "")).resolve() not in path.parents:
        return FORBIDDEN, {"error": f"raport poza katalogiem raportów huba: {path}", "run": run}
    try:
        if path.stat().st_size > MAX_REPORT_BYTES:
            return FORBIDDEN, {"error": f"raport większy niż {MAX_REPORT_BYTES} bajtów: {path}", "run": run}
        markdown = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return NOT_FOUND, {"error": f"nie można odczytać raportu {path}: {exc}", "run": run}
    return OK, {"run": run, "markdown": markdown, "path": str(path)}
