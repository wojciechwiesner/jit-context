"""Operator Wall: aggregation of all sources into the GET /api/mc/wall payload (deterministic, no LLM)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from health import mission_data, wall_charters, wall_external, wall_needs, wall_projects, wall_readers

NEEDS_ME_MAX = wall_needs.NEEDS_ME_MAX
NO_DATA = wall_needs.NO_DATA
plural = wall_needs.plural


def read_source(name: str, build: Callable[[], Any], sources: dict[str, dict]) -> Any:
    """Run one reader; on failure record the reason and return None (fail open, never a fake value)."""
    try:
        value, age_s = build()
    except Exception as exc:  # any broken source degrades to "brak danych: <reason>"
        sources[name] = {"ok": False, "age_s": None, "error": f"{NO_DATA}: {type(exc).__name__}: {exc}"[:200]}
        return None
    sources[name] = {"ok": True, "age_s": None if age_s is None else round(age_s, 1), "error": None}
    return value


def _machines(sessions, crons, cards, nodes) -> dict[str, Any]:
    counts = {s: 0 for s in wall_readers.SESSION_STATUSES}
    for row in sessions or []:
        if row["status"] in counts:
            counts[row["status"]] += 1
    waiting = [row["since"] for row in sessions or [] if row["status"] == "review"]
    running_on: dict[str, int] = {}
    for row in sessions or []:
        if row["status"] == "running":
            running_on[str(row.get("node") or "")] = running_on.get(str(row.get("node") or ""), 0) + 1
    return {
        "oldest_review": min(waiting) if waiting else None, "running_by_node": running_on,
        "sessions": counts if sessions is not None else None,
        "cron_failed_24h": None if crons is None else len(crons),
        "blocked_cards": None if cards is None else len(cards),
        "nodes": nodes,
    }


def _with_file_age(path, reader, now: float):
    return reader(), wall_readers.file_age_s(path, now)


def build_wall(now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    sources: dict[str, dict] = {}
    sessions = read_source("sessions", lambda: (wall_readers.read_sessions(), 0.0), sources)
    crons = read_source("cron", lambda: (wall_readers.read_cron_failures(now), 0.0), sources)
    autocheck = read_source("autocheck", lambda: _with_file_age(wall_readers.autocheck_file(), wall_readers.read_autocheck, now), sources)
    cards = read_source("kanban", wall_external.blocked_cards, sources)
    nodes = read_source("nodes", wall_external.nodes, sources)
    charters = read_source("charters", lambda: (wall_charters.load_all(), 0.0), sources)
    projects = read_source("projects", lambda: (mission_data.list_projects(), 0.0), sources)
    needs_all = wall_needs.needs_items(autocheck, crons, cards, sessions)
    verdict, level = wall_needs.build_verdict(needs_all, autocheck, now)
    return {
        "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict, "level": level, "next_action": wall_needs.next_action(needs_all),
        "needs_me": needs_all[:NEEDS_ME_MAX], "needs_me_total": len(needs_all),
        "projects": wall_projects.tiles(projects, charters, autocheck, sessions, now),
        "machines": _machines(sessions, crons, cards, nodes),
        "charters": {**(wall_charters.counts(charters) if charters is not None else {"draft": 0, "approved": 0}),
                     "drafts": wall_charters.drafts(charters) if charters is not None else []},
        "sources": sources,
    }
