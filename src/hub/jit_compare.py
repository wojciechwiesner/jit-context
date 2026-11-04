"""Observational JIT comparison per project and day: sessions with a recorded capsule vs sessions without.

Input is the per-session rollup in usage.sqlite (session_days, filled by the H8 collectors). A session counts as
"JIT on" when any overlay turn_telemetry row with capsule_tokens_est > 0 was recorded for its session id (on any
day); every other Claude/Hermes session is "JIT off". Only medians and group sizes are reported. Nothing here
compares the two groups numerically: this is an observation (sessions choose themselves into the groups), not an
experiment, so no difference or "saved tokens" value is computed. Savings come only from the controlled A/B.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from hub import registry
from hub import usage_store as store
from hub.usage import ProjectResolver
from hub.usage_claude import SOURCE as CLAUDE_SOURCE
from hub.usage_dbs import HERMES_SOURCE, JIT_SOURCE

OBSERVATION_LABEL = "obserwacja, nie eksperyment"
LOW_N_LABEL = "za mało danych"
MIN_GROUP_N = 20
JIT_ON = "jit_on"
JIT_OFF = "jit_off"
USAGE_SOURCES = (CLAUDE_SOURCE, HERMES_SOURCE)
# Hermes sessions keep api call counts, not user turns: their turn count is unknown, not zero.
SOURCES_WITH_TURNS = (CLAUDE_SOURCE,)
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
METRICS = ("tokens_per_turn", "cache_read_share", "turns_per_session", "tool_errors_per_session")
METRIC_DEFINITIONS = {
    "tokens_per_turn": "(input + output + cache-read + cache-write) / tury sesji danego dnia",
    "cache_read_share": "cache-read / (input + cache-read + cache-write)",
    "turns_per_session": "tury użytkownika w sesji danego dnia (Claude Code; Hermes nie zapisuje tur)",
    "tool_errors_per_session": "błędy narzędzi w sesji (kolektory ich jeszcze nie zbierają)",
}

Resolver = Callable[[Optional[str], Optional[str]], Tuple[Optional[str], bool]]


def jit_sessions(conn: sqlite3.Connection) -> set:
    """Session ids with at least one recorded capsule in the overlay DBs."""
    rows = conn.execute(
        "SELECT DISTINCT session_id FROM session_days WHERE source = ? AND capsules > 0 AND session_id IS NOT NULL",
        (JIT_SOURCE,),
    )
    return {row["session_id"] for row in rows}


def _usage_rows(conn: sqlite3.Connection, since: Optional[str]) -> Iterable[sqlite3.Row]:
    clauses = [f"source IN ({', '.join('?' for _ in USAGE_SOURCES)})"]
    params: List[str] = list(USAGE_SOURCES)
    if since is not None:
        clauses.append("day >= ?")
        params.append(since)
    return conn.execute(f"SELECT * FROM session_days WHERE {' AND '.join(clauses)} ORDER BY day", params)


def session_days(conn: sqlite3.Connection, resolve: Resolver, since: Optional[str] = None) -> List[dict]:
    """One record per (source, session, day, project); units of one session (subagent files) are summed."""
    merged: Dict[tuple, dict] = {}
    for row in _usage_rows(conn, since):
        project, registered = resolve(row["path"], row["scope"])
        session = row["session_id"] or row["unit"]
        key = (row["source"], session, row["day"], project)
        record = merged.setdefault(key, {
            "source": row["source"], "session_id": session, "day": row["day"], "project": project,
            "registered": registered, "turns": 0, **{name: 0 for name in TOKEN_FIELDS},
        })
        record["turns"] += row["turns"] or 0
        for name in TOKEN_FIELDS:
            record[name] += row[name] or 0
    return list(merged.values())


def session_metrics(record: dict) -> Dict[str, Optional[float]]:
    """Per session-day metric values; None where the source does not record the input."""
    has_turns = record["source"] in SOURCES_WITH_TURNS
    turns = record["turns"] if has_turns else None
    total = sum(record[name] for name in TOKEN_FIELDS)
    prompt_side = record["input_tokens"] + record["cache_read_tokens"] + record["cache_write_tokens"]
    return {
        "tokens_per_turn": total / turns if turns else None,
        "cache_read_share": record["cache_read_tokens"] / prompt_side if prompt_side else None,
        "turns_per_session": float(turns) if turns is not None else None,
        "tool_errors_per_session": record.get("tool_errors"),
    }


def summarize(records: List[dict]) -> dict:
    """n, sessions per source and the median of each metric over the sessions that have it."""
    values: Dict[str, List[float]] = {name: [] for name in METRICS}
    sources: Dict[str, int] = {}
    for record in records:
        sources[record["source"]] = sources.get(record["source"], 0) + 1
        for name, value in session_metrics(record).items():
            if value is not None:
                values[name].append(float(value))
    metrics = {name: {"median": median(found) if found else None, "n": len(found)}
               for name, found in values.items()}
    return {"n": len(records), "sources": sources, "metrics": metrics}


def _group_row(project: Optional[str], registered: bool, day: str, on: List[dict], off: List[dict]) -> dict:
    jit_on, jit_off = summarize(on), summarize(off)
    enough = jit_on["n"] >= MIN_GROUP_N and jit_off["n"] >= MIN_GROUP_N
    return {
        "project": project, "registered": registered, "day": day,
        JIT_ON: jit_on, JIT_OFF: jit_off,
        "enough_data": enough, "warning": None if enough else LOW_N_LABEL,
    }


def compare_records(records: List[dict], jit_ids: set) -> List[dict]:
    """Group session-days by (project, day) and split them by the JIT flag."""
    groups: Dict[Tuple[Optional[str], str], Dict[str, List[dict]]] = {}
    registered: Dict[Optional[str], bool] = {}
    for record in records:
        bucket = groups.setdefault((record["project"], record["day"]), {JIT_ON: [], JIT_OFF: []})
        bucket[JIT_ON if record["session_id"] in jit_ids else JIT_OFF].append(record)
        registered[record["project"]] = bool(record["registered"])
    ordered = sorted(groups.items(), key=lambda item: (item[0][0] or "", item[0][1]))
    return [_group_row(project, registered[project], day, split[JIT_ON], split[JIT_OFF])
            for (project, day), split in ordered]


def build_comparison(conn: sqlite3.Connection, resolve: Resolver, since: Optional[str] = None,
                     project: Optional[str] = None) -> dict:
    """Full comparison document; rows are filtered to one project when given."""
    rows = compare_records(session_days(conn, resolve, since), jit_sessions(conn))
    if project is not None:
        rows = [row for row in rows if row["project"] == project]
    return {
        "label": OBSERVATION_LABEL, "min_group_n": MIN_GROUP_N, "low_n_label": LOW_N_LABEL,
        "since": since, "definitions": dict(METRIC_DEFINITIONS), "rows": rows,
    }


def jit_comparison(days: Optional[int] = None, project: Optional[str] = None, db_path: Optional[Path] = None,
                   projects: Optional[List[dict]] = None) -> dict:
    """Comparison over the last N days (all stored days when None) from the usage store."""
    since = (date.today() - timedelta(days=days - 1)).isoformat() if days else None
    projects = registry.load_projects() if projects is None else projects
    conn = store.connect(db_path)
    try:
        return build_comparison(conn, ProjectResolver(projects), since=since, project=project)
    finally:
        conn.close()
