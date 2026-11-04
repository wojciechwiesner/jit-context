"""Run state files of hub actions: <hub dir>/runs/<id>.json, one JSON object per run, written atomically.

Fields: id, slug, action, label, project_path, status (queued | running | succeeded | failed | timeout |
interrupted), created, started, finished, usage, cost, report_path, obsidian_path, mirror_error, error,
server_pid. Runs left queued/running by a server process that no longer exists are marked interrupted when
listed: their worker died with that process and they will never finish.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import config

RUNS_DIR_NAME = "runs"
QUEUED = "queued"
RUNNING = "running"
INTERRUPTED = "interrupted"
ACTIVE_STATUSES = (QUEUED, RUNNING)
RUN_ID_RANDOM_BYTES = 3
DEFAULT_LIST_LIMIT = 100

_WRITE_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def runs_dir() -> Path:
    return config.hub_dir() / RUNS_DIR_NAME


def new_run_id(action: str) -> str:
    """Sortable by creation time; never derived from the slug, so it is always a safe file name."""
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{action}-{secrets.token_hex(RUN_ID_RANDOM_BYTES)}"


def run_path(run_id: str) -> Path:
    return runs_dir() / f"{run_id}.json"


def save(run: dict) -> dict:
    path = run_path(run["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with _WRITE_LOCK:
        tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)
    return run


def update(run_id: str, **fields) -> dict:
    run = load(run_id) or {"id": run_id}
    run.update(fields)
    return save(run)


def load(run_id: str) -> Optional[dict]:
    try:
        payload = json.loads(run_path(run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _process_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _settle_orphan(run: dict) -> dict:
    if run.get("status") in ACTIVE_STATUSES and not _process_alive(run.get("server_pid")):
        run = update(run["id"], status=INTERRUPTED, finished=run.get("finished") or now_iso(),
                     error=f"przerwane: proces serwera hub {run.get('server_pid')} już nie działa")
    return run


def list_runs(slug: Optional[str] = None, limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """Newest first, optionally for one project; unreadable files are counted, not hidden."""
    directory = runs_dir()
    runs: List[dict] = []
    unreadable = 0
    for path in sorted(directory.glob("*.json"), reverse=True) if directory.is_dir() else []:
        run = load(path.stem)
        if run is None:
            unreadable += 1
            continue
        if slug is None or run.get("slug") == slug:
            runs.append(_settle_orphan(run))
    return {"slug": slug, "dir": str(directory), "runs": runs[:limit], "total": len(runs),
            "unreadable": unreadable}


def active_run(slug: str, action: str) -> Optional[dict]:
    """The queued or running run of this project and action, if any (one at a time per pair)."""
    for run in list_runs(slug)["runs"]:
        if run.get("action") == action and run.get("status") in ACTIVE_STATUSES:
            return run
    return None
