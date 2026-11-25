"""Operator Wall: aggregation of all sources into the GET /api/mc/wall payload (deterministic, no LLM)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from health import mission_data, wall_charters, wall_external, wall_readers

ACTIVE_WINDOW_S = 7 * wall_readers.DAY_S
NEEDS_ME_MAX = 5
RANK = {"autocheck_edge": 0, "cron_failed": 1, "blocked_card": 2, "review": 3, "lost_session": 4}
NO_DATA = "brak danych"
HOUR_S = 3600


def plural(n: int, one: str, few: str, many: str) -> str:
    """Polish noun form for n: 1 -> one, 2-4 (not 12-14) -> few, otherwise many."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def read_source(name: str, build: Callable[[], Any], sources: dict[str, dict]) -> Any:
    """Run one reader; on failure record the reason and return None (fail open, never a fake value)."""
    try:
        value, age_s = build()
    except Exception as exc:  # any broken source degrades to "brak danych: <reason>"
        sources[name] = {"ok": False, "age_s": None, "error": f"{NO_DATA}: {type(exc).__name__}: {exc}"[:200]}
        return None
    sources[name] = {"ok": True, "age_s": None if age_s is None else round(age_s, 1), "error": None}
    return value


def _link(slug: str) -> str:
    return f"/mc?project={slug}" if slug else "/mc"


def _cards_by_board(cards) -> dict[str, list[dict]]:
    """One needs-me row per kanban board: 200 stale blocked cards must not drown the real signals."""
    groups: dict[str, list[dict]] = {}
    for card in cards or []:
        groups.setdefault(card["board"], []).append(card)
    return groups


def _needs_items(autocheck, crons, cards, sessions) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for slug, entry in ((autocheck or {}).get("projects") or {}).items():
        for bad in entry["failing"]:
            what = f"Przepływ {bad['flow']}: krawędź {bad['edge'] or '?'} ({bad['state']})"
            items.append({"kind": "autocheck_edge", "what": what, "project": slug,
                          "since": bad["since"], "link": _link(slug)})
    for cron in crons or []:
        items.append({"kind": "cron_failed", "what": f"Cron {cron['name']} ({cron['status']})",
                      "project": "", "since": cron["since"], "link": "/hub"})
    for board, group in _cards_by_board(cards).items():
        n = len(group)
        what = f"{n} {plural(n, 'zablokowana karta', 'zablokowane karty', 'zablokowanych kart')} na tablicy {board}"
        items.append({"kind": "blocked_card", "what": what, "project": board,
                      "since": min(c["since"] for c in group), "link": "/hub"})
    for row in sessions or []:
        if row["status"] == "review":
            items.append({"kind": "review", "what": f"Sesja do review: {row['job']}",
                          "project": row["project"], "since": row["since"], "link": _link(row["project"])})
        elif row["status"] == "lost":
            items.append({"kind": "lost_session", "what": f"Zgubiona sesja: {row['job']}",
                          "project": row["project"], "since": row["since"], "link": _link(row["project"])})
    return sorted(items, key=lambda i: (RANK[i["kind"]], i["since"]))


def _age_words(seconds: float) -> str:
    days = int(seconds // wall_readers.DAY_S)
    if days >= 1:
        return f"{days} {plural(days, 'dzień', 'dni', 'dni')}"
    hours = int(seconds // HOUR_S)
    return f"{hours} h" if hours else "poniżej godziny"


def _flows_sentence(autocheck: dict | None) -> str:
    if autocheck is None:
        return f"Przepływy: {NO_DATA}."
    failing = sum(1 for e in autocheck["projects"].values() if e["state"] != "ok")
    return "Przepływy OK." if failing == 0 else f"Przepływy z błędem: {failing}."


def build_verdict(needs: list[dict], reviews: list[dict], autocheck: dict | None, now: float) -> tuple[str, str]:
    """(sentence, level). `needs` counts everything except review (reviews get their own clause)."""
    urgent = sum(1 for i in needs if i["kind"] != "review")
    if urgent:
        head = f"{urgent} {plural(urgent, 'rzecz czeka', 'rzeczy czekają', 'rzeczy czeka')} na Ciebie."
    else:
        head = "Nic pilnego nie czeka na Ciebie."
    parts = [head]
    if reviews:
        oldest = max(0.0, now - min(r["since"] for r in reviews))
        n = len(reviews)
        parts.append(f"{n} {plural(n, 'sesja', 'sesje', 'sesji')} do review, najstarsza {_age_words(oldest)}.")
    parts.append(_flows_sentence(autocheck))
    level = "bad" if urgent else ("warn" if reviews or autocheck is None else "ok")
    return " ".join(parts), level


def _project_tiles(projects, charters, autocheck, sessions, now) -> list[dict[str, Any]]:
    reviews: dict[str, int] = {}
    for row in sessions or []:
        if row["status"] == "review":
            reviews[row["project"]] = reviews.get(row["project"], 0) + 1
    tiles = []
    for proj in projects or []:
        if now - proj["last_activity"] > ACTIVE_WINDOW_S:
            continue
        slug = proj["slug"]
        check = ((autocheck or {}).get("projects") or {}).get(slug)
        charter = None if charters is None else wall_charters.summary(charters.get(slug))
        tiles.append({
            "slug": slug, "title": proj["title"], "link": _link(slug), "charter": charter,
            "charter_known": charters is not None,
            "last_commit": proj.get("last_commit"), "last_activity": proj["last_activity"],
            "review_count": reviews.get(slug, 0), "blockers": proj.get("blockers", 0),
            "autocheck": check["state"] if check else None,
            "audience": charter["audience"] if charter and charter["status"] == "approved" else [],
        })
    tiles.sort(key=lambda t: (t["autocheck"] not in (None, "ok"), t["review_count"], t["last_activity"]), reverse=True)
    return tiles


def _machines(sessions, crons, cards, nodes) -> dict[str, Any]:
    counts = {s: 0 for s in wall_readers.SESSION_STATUSES}
    for row in sessions or []:
        if row["status"] in counts:
            counts[row["status"]] += 1
    return {
        "sessions": counts if sessions is not None else None,
        "cron_failed_24h": None if crons is None else len(crons),
        "blocked_cards": None if cards is None else len(cards),
        "nodes": nodes,
    }


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
    needs_all = _needs_items(autocheck, crons, cards, sessions)
    reviews = [i for i in needs_all if i["kind"] == "review"]
    verdict, level = build_verdict(needs_all, reviews, autocheck, now)
    return {
        "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict, "level": level,
        "needs_me": needs_all[:NEEDS_ME_MAX], "needs_me_total": len(needs_all),
        "projects": _project_tiles(projects, charters, autocheck, sessions, now),
        "machines": _machines(sessions, crons, cards, nodes),
        "charters": {**(wall_charters.counts(charters) if charters is not None else {"draft": 0, "approved": 0}),
                     "drafts": wall_charters.drafts(charters) if charters is not None else []},
        "sources": sources,
    }


def _with_file_age(path, reader, now: float):
    return reader(), wall_readers.file_age_s(path, now)
