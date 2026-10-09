"""Mission Control project detail: cockpit data for one project.

Calls the canonical cockpit exporter (Node) and maps it to ProjectDetail
(docs/MISSION_CONTROL.md). When the exporter is unavailable it falls back to the raw
.planning files and says so in `cockpit_error` instead of pretending the data is complete.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from health import mission_data as md

EXPORT_TIMEOUT_S = 8
DOSSIER_SESSION_RE = re.compile(r"\*\*Sesja:\*\*\s*(.+)")
DOSSIER_GOAL_RE = re.compile(r"\*\*Cel:\*\*\s*(.+)")


def _export(path: Path) -> dict[str, Any]:
    proc = subprocess.run(["node", str(md.COCKPIT_EXPORT), str(path)],
                          capture_output=True, text=True, timeout=EXPORT_TIMEOUT_S)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "export.js failed").strip().splitlines()[-1][:300])
    return json.loads(proc.stdout)


def _dossier(slug: str) -> dict[str, str | None]:
    text = md._read(md.OBSIDIAN_PROJECTS / f"{slug}.md")
    session = DOSSIER_SESSION_RE.search(text)
    goal = DOSSIER_GOAL_RE.search(text)
    return {"last_session": session.group(1).strip() if session else None,
            "goal": goal.group(1).strip() if goal else None}


def _from_export(data: dict[str, Any]) -> dict[str, Any]:
    state = data.get("state") or {}
    git = data.get("git") or {}
    meta = data.get("architectureMeta") or {}
    return {
        "title": data.get("title"),
        "state": {"exists": state.get("exists", False), "updated": state.get("updated"),
                  "age_days": state.get("ageDays"), "open": state.get("open") or [],
                  "open_count": state.get("openCount", 0), "done_count": state.get("doneCount", 0),
                  "blockers": state.get("blockers") or []},
        "thoughts": data.get("thoughts") or [],
        "deploy": data.get("deploy") or [],
        "checks": data.get("checks") or [],
        "git": {"branch": git.get("branch"), "dirty_count": len(git.get("dirty") or []),
                "log": git.get("log") or []},
        "obsidian": data.get("obsidian") or {"exists": False},
        "diagram": {"source": meta.get("source", "file"), "mermaid": data.get("architecture") or "",
                    "note": meta.get("note", "")},
        "cockpit_error": None,
    }


def _fallback(path: Path, error: str) -> dict[str, Any]:
    state_md = md._read(path / ".planning" / "STATE.md")
    blockers = md._blockers(state_md)
    open_tasks = [{"section": "", "text": ln.split("]", 1)[1].strip()}
                  for ln in state_md.splitlines() if md.OPEN_TASK_RE.match(ln + "\n")]
    return {
        "state": {"exists": bool(state_md), "updated": None, "age_days": None, "open": open_tasks[:12],
                  "open_count": len(open_tasks), "done_count": 0, "blockers": blockers},
        "thoughts": [], "deploy": [], "checks": [],
        "git": {"branch": None, "dirty_count": 0, "log": []},
        "obsidian": {"exists": False},
        "diagram": {"source": "file", "mermaid": md._read(path / ".planning" / "ARCHITECTURE.mmd").strip(),
                    "note": "Surowy ARCHITECTURE.mmd (generator kokpitu niedostępny)."},
        "cockpit_error": error,
    }


def project_detail(slug: str) -> dict[str, Any] | None:
    path = md._project_path(slug)
    if path is None:
        return None

    def build() -> dict[str, Any]:
        summary = next((p for p in md.list_projects() if p["slug"] == slug), None) or md._summary(path, 0)
        try:
            detail = _from_export(_export(path))
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
            detail = _fallback(path, f"{type(exc).__name__}: {exc}")
        has_cockpit = (path / ".planning" / "state.html").is_file()
        return {**summary, **detail, "title": detail.get("title") or slug,
                "cockpit_url": f"/cockpit/{slug}" if has_cockpit else None, "dossier": _dossier(slug)}
    return md._cached(f"detail:{slug}", md.DETAIL_CACHE_S, build)


def cockpit_file(slug: str) -> Path | None:
    path = md._project_path(slug)
    if path is None:
        return None
    target = path / ".planning" / "state.html"
    return target if target.is_file() else None
