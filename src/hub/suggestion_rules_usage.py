"""Suggestion rules over the usage store (H8 session_days): a token spike week over week, and an active project
whose sessions mostly ran without a JIT capsule. Both read the same per-session records as `jit hub compare`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Set

from hub import jit_compare, registry
from hub import usage_store as store
from hub.suggestion_model import (
    SEVERITY_MEDIUM, MissingData, ProjectContext, Suggestion, command_evidence, value_evidence,
)
from hub.usage import ProjectResolver

WEEK_DAYS = 7
USAGE_WINDOW_DAYS = 2 * WEEK_DAYS
SPIKE_FACTOR = 2.0
MIN_ACTIVE_SESSIONS = 5
STORE_COMMAND = "jit hub usage --days 14"


@dataclass(frozen=True)
class UsageView:
    """Session-day records of one project for the last USAGE_WINDOW_DAYS days, plus the JIT session ids."""
    slug: str
    today: date
    records: List[dict]
    jit_ids: Set[str]


def load_usage(slug: Optional[str], today: date, db_path: Optional[Path] = None,
               projects: Optional[List[dict]] = None) -> UsageView:
    """Read the usage store; raises MissingData when there is no slug or no store yet."""
    if not slug:
        raise MissingData("projekt nie jest w rejestrze huba (brak sluga)")
    path = Path(db_path) if db_path else store.usage_db_path()
    if not path.exists():
        raise MissingData(f"brak magazynu zużycia {path} (uruchom `jit hub usage`)")
    since = (today - timedelta(days=USAGE_WINDOW_DAYS - 1)).isoformat()
    resolver = ProjectResolver(registry.load_projects() if projects is None else projects)
    conn = store.connect(path)
    try:
        records = [r for r in jit_compare.session_days(conn, resolver, since) if r["project"] == slug]
        jit_ids = jit_compare.jit_sessions(conn)
    finally:
        conn.close()
    return UsageView(slug, today, records, jit_ids)


def _tokens(record: dict) -> int:
    return sum(record[name] for name in jit_compare.TOKEN_FIELDS)


def usage_spike(ctx: ProjectContext) -> Optional[Suggestion]:
    view: UsageView = ctx.usage_view()
    week_start = (view.today - timedelta(days=WEEK_DAYS - 1)).isoformat()
    current = sum(_tokens(r) for r in view.records if r["day"] >= week_start)
    previous = sum(_tokens(r) for r in view.records if r["day"] < week_start)
    if previous == 0:
        if current == 0:
            return None
        raise MissingData(f"brak zużycia w poprzednich {WEEK_DAYS} dniach, nie ma z czym porównać")
    if current <= SPIKE_FACTOR * previous:
        return None
    return Suggestion(
        "usage_spike", SEVERITY_MEDIUM,
        f"Zużycie tokenów w ostatnich {WEEK_DAYS} dniach jest {current / previous:.1f}x wyższe niż tydzień wcześniej.",
        "Sprawdź w zakładce Statystyki, które sesje urosły, i ogranicz kontekst lub liczbę tur w tych zadaniach.",
        (value_evidence(f"tokeny {week_start}..{view.today.isoformat()}", current),
         value_evidence(f"tokeny poprzednie {WEEK_DAYS} dni", previous),
         command_evidence(STORE_COMMAND, f"próg: więcej niż {SPIKE_FACTOR:g}x")),
    )


def jit_mostly_off(ctx: ProjectContext) -> Optional[Suggestion]:
    view: UsageView = ctx.usage_view()
    week_start = (view.today - timedelta(days=WEEK_DAYS - 1)).isoformat()
    sessions = {(r["source"], r["session_id"]) for r in view.records if r["day"] >= week_start}
    if len(sessions) < MIN_ACTIVE_SESSIONS:
        return None  # not an active project this week
    off = sum(1 for _, session_id in sessions if session_id not in view.jit_ids)
    if off * 2 <= len(sessions):
        return None
    return Suggestion(
        "jit_mostly_off", SEVERITY_MEDIUM,
        f"{off} z {len(sessions)} sesji w ostatnich {WEEK_DAYS} dniach działało bez kapsuły JIT.",
        "Sprawdź, czy hooki JIT są zainstalowane dla tego projektu (`jit install`), i uruchom `jit init` w repo.",
        (value_evidence("sesje bez JIT / wszystkie", f"{off} / {len(sessions)}"),
         command_evidence("jit hub compare --days 7", "sesja z JIT = zapisana kapsuła w overlay DB")),
    )
