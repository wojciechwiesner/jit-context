"""Operator Wall: "Wymaga mnie" ranking, the verdict sentence and the single next action (deterministic, no LLM)."""
from __future__ import annotations

from typing import Any

from health import wall_readers

NEEDS_ME_MAX = 7
FEEDBY_BOARD = "feedby"
NO_DATA = "brak danych"
HOUR_S = 3600
# Lower rank = more urgent. Feedby cards wait for the owner by design, so they sit below everything else.
RANK = {"autocheck_edge": 0, "cron_failed": 1, "blocked_card": 2, "review": 3, "lost_session": 4, "feedby_decision": 5}
NOT_URGENT = ("review", "feedby_decision")  # counted in their own verdict clauses, not in "N rzeczy"
STATE_PL = {"ok": "OK", "degraded": "spowolnione", "broken": "zepsute"}
STATE_OTHER_PL = "do sprawdzenia"
CRON_STATUS_PL = {"failed": "błąd", "missed": "pominięty"}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Polish noun form for n: 1 -> one, 2-4 (not 12-14) -> few, otherwise many."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def state_pl(state: str) -> str:
    return STATE_PL.get(state, STATE_OTHER_PL)


def _link(slug: str) -> str:
    return f"/mc?project={slug}" if slug else "/mc"


def _item(kind: str, what: str, project: str, since: float, link: str) -> dict[str, Any]:
    return {"kind": kind, "what": what, "project": project, "since": since, "link": link}


def _cards_by_board(cards) -> dict[str, list[dict]]:
    """One needs-me row per kanban board: 200 stale blocked cards must not drown the real signals."""
    groups: dict[str, list[dict]] = {}
    for card in cards or []:
        groups.setdefault(card["board"], []).append(card)
    return groups


def _card_item(board: str, group: list[dict]) -> dict[str, Any]:
    n = len(group)
    since = min(c["since"] for c in group)
    if board == FEEDBY_BOARD:
        what = f"{n} {plural(n, 'zgłoszenie', 'zgłoszenia', 'zgłoszeń')} Feedby " \
               f"{plural(n, 'czeka', 'czekają', 'czeka')} na Twoją decyzję"
        return _item("feedby_decision", what, board, since, "/hub")
    what = f"{n} {plural(n, 'zablokowana karta', 'zablokowane karty', 'zablokowanych kart')} na tablicy {board}"
    return _item("blocked_card", what, board, since, "/hub")


def needs_items(autocheck, crons, cards, sessions) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for slug, entry in ((autocheck or {}).get("projects") or {}).items():
        for bad in entry["failing"]:
            what = f"Przepływ {bad['flow']}: krok {bad['edge'] or '?'} ({state_pl(bad['state'])})"
            items.append(_item("autocheck_edge", what, slug, bad["since"], _link(slug)))
    for cron in crons or []:
        status = CRON_STATUS_PL.get(cron["status"], cron["status"])
        items.append(_item("cron_failed", f"Cron {cron['name']} ({status})", "", cron["since"], "/hub"))
    items += [_card_item(board, group) for board, group in _cards_by_board(cards).items()]
    for row in sessions or []:
        if row["status"] == "review":
            items.append(_item("review", f"Sesja do przeglądu: {row['job']}", row["project"], row["since"], _link(row["project"])))
        elif row["status"] == "lost":
            items.append(_item("lost_session", f"Zgubiona sesja: {row['job']}", row["project"], row["since"], _link(row["project"])))
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


def build_verdict(needs: list[dict], autocheck: dict | None, now: float) -> tuple[str, str]:
    """(sentence, level). "N rzeczy" excludes review sessions and Feedby decisions: each has its own clause."""
    urgent = sum(1 for i in needs if i["kind"] not in NOT_URGENT)
    reviews = [i for i in needs if i["kind"] == "review"]
    feedby = [i for i in needs if i["kind"] == "feedby_decision"]
    parts = [f"{urgent} {plural(urgent, 'rzecz czeka', 'rzeczy czekają', 'rzeczy czeka')} na Ciebie." if urgent
             else "Nic pilnego nie czeka na Ciebie."]
    if feedby:
        parts.append(feedby[0]["what"] + ".")
    if reviews:
        n = len(reviews)
        oldest = _age_words(max(0.0, now - min(r["since"] for r in reviews)))
        parts.append(f"{n} {plural(n, 'sesja', 'sesje', 'sesji')} do przeglądu, najstarsza {oldest}.")
    parts.append(_flows_sentence(autocheck))
    level = "bad" if urgent else ("warn" if reviews or feedby or autocheck is None else "ok")
    return " ".join(parts), level


def next_action(needs: list[dict]) -> dict[str, Any] | None:
    """The single most important thing: simply the top-ranked needs-me row."""
    if not needs:
        return None
    top = needs[0]
    return {"text": top["what"], "link": top["link"], "kind": top["kind"], "since": top["since"]}
