"""Operator Wall: read-only readers for the local Hermes state files.

Every reader returns plain data and raises on a broken source; wall_data wraps each call so one
broken source degrades to "brak danych: <reason>" instead of breaking the whole wall.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERMES_HOME = Path(os.environ.get("JIT_WALL_HERMES_HOME", Path.home() / ".hermes"))
DAY_S = 86400
CRON_WINDOW_S = DAY_S
CRON_BAD_STATUSES = ("failed", "missed")
CRON_ROW_LIMIT = 500
SESSION_STATUSES = ("running", "review", "failed", "lost")


def dispatch_dir() -> Path:
    return HERMES_HOME / "state" / "code-dispatch"


def cron_db() -> Path:
    return HERMES_HOME / "cron" / "executions.db"


def cron_jobs_file() -> Path:
    return HERMES_HOME / "cron" / "jobs.json"


def autocheck_file() -> Path:
    return HERMES_HOME / "state" / "jit-hub" / "autocheck_flows.json"


def charters_dir() -> Path:
    return HERMES_HOME / "state" / "jit-hub" / "charters"


def parse_ts(value: Any) -> float:
    """ISO-8601 string or epoch number -> epoch seconds; 0.0 when missing or unparseable."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def file_age_s(path: Path, now: float) -> float:
    return max(0.0, now - path.stat().st_mtime)


def read_sessions() -> list[dict[str, Any]]:
    """code-dispatch meta.json files -> one dict per job with `project` derived from the repo dir."""
    root = dispatch_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"brak katalogu {root}")
    rows: list[dict[str, Any]] = []
    for meta in sorted(root.glob("*/meta.json")):
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue  # a half-written meta.json must not hide the other sessions
        if not isinstance(data, dict):
            continue
        finished = parse_ts(data.get("finished_at"))
        started = parse_ts(data.get("started_at"))
        rows.append({
            "job": data.get("job") or meta.parent.name,
            "project": Path(str(data.get("repo") or "")).name,
            "status": str(data.get("status") or "unknown"),
            "engine": data.get("engine"), "node": data.get("node"),
            "started_at": started, "since": finished or started,
        })
    return rows


def _job_names() -> dict[str, str]:
    try:
        jobs = json.loads(cron_jobs_file().read_text()).get("jobs", [])
    except (OSError, ValueError):
        return {}  # names are cosmetic: fall back to the job id
    return {str(j.get("id")): str(j.get("name") or j.get("id")) for j in jobs if isinstance(j, dict)}


def read_cron_failures(now: float) -> list[dict[str, Any]]:
    """Latest failed/missed execution per job within 24 h (read-only connection, query_only)."""
    uri = f"file:{cron_db()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        con.execute("PRAGMA query_only=ON")
        marks = ",".join("?" for _ in CRON_BAD_STATUSES)
        rows = con.execute(
            f"SELECT job_id, status, claimed_at, error FROM executions WHERE status IN ({marks})"
            " ORDER BY claimed_at DESC LIMIT ?", (*CRON_BAD_STATUSES, CRON_ROW_LIMIT)).fetchall()
    finally:
        con.close()
    names = _job_names()
    latest: dict[str, dict[str, Any]] = {}
    for job_id, status, claimed_at, error in rows:
        when = parse_ts(claimed_at)
        if now - when > CRON_WINDOW_S or job_id in latest and latest[job_id]["since"] >= when:
            continue
        latest[job_id] = {"job_id": job_id, "name": names.get(job_id, job_id), "status": status,
                          "since": when, "error": (error or "")[:160]}
    return sorted(latest.values(), key=lambda r: r["since"], reverse=True)


def read_autocheck() -> dict[str, Any]:
    """autocheck_flows.json -> {updated_at, projects: {slug: {state, failing: [{flow, edge, state}]}}}."""
    data = json.loads(autocheck_file().read_text())
    projects: dict[str, Any] = {}
    for slug, entry in (data.get("projects") or {}).items():
        failing = []
        worst = "ok"
        for flow in entry.get("flows") or []:
            state = str(flow.get("overall_state") or "unknown")
            if state != "ok":
                worst = state if worst == "ok" else worst
                bad_edges = [e for e in flow.get("edges") or [] if e.get("state") != "ok"]
                for edge in bad_edges or [{"edge_id": "", "state": state}]:
                    failing.append({"flow": flow.get("flow_id"), "edge": edge.get("edge_id") or "",
                                    "state": edge.get("state") or state,
                                    "since": parse_ts(edge.get("last_seen_at") or flow.get("checked_at"))})
        projects[slug] = {"state": worst, "failing": failing}
    return {"updated_at": parse_ts(data.get("updated_at")), "projects": projects}
