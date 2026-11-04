"""Per project stats document for the cockpit "Statystyki" tab: <hub dir>/stats/<slug>.json.

The refresher writes it before it builds a cockpit; cockpit/stats.js reads it. Sections, each with its own
error or "missing" reason so one broken input never hides the others:
- usage: measured daily tokens (Claude Code + Hermes), session-days, turns (Claude Code), JIT capsules and cost
  (only where a source recorded it) for the last WINDOW_DAYS days,
- comparison: observational JIT on/off medians over the same window with n and labels (no difference computed),
- ab: the newest controlled A/B batch of the project (date, model, calls, paired on-minus-off medians with n),
  or None when no batch exists,
- suggestions: the deterministic suggestions report.
Nothing is estimated: a value the sources did not record stays None.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import config
from hub import bench_store, jit_compare, registry
from hub import usage_store as store
from hub.suggestions import project_suggestions
from hub.usage import ProjectResolver, collect_usage
from hub.usage_claude import SOURCE as CLAUDE_SOURCE
from hub.usage_dbs import HERMES_SOURCE, JIT_SOURCE

STATS_DIR_NAME = "stats"
SCHEMA_VERSION = 1
WINDOW_DAYS = 30
STATS_MAX_AGE_SECONDS = 600
ERROR_TEXT_LIMIT = 300
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
TOKEN_SOURCES = (CLAUDE_SOURCE, HERMES_SOURCE)
COST_SOURCES = (HERMES_SOURCE,)
COLLECTOR_ERROR_KEY = "collector"
GROUP_UNIT = "sesja-dzień"


def stats_dir() -> Path:
    return config.hub_dir() / STATS_DIR_NAME


def stats_path(slug: str) -> Path:
    return stats_dir() / f"{slug}.json"


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_LIMIT]


def collect_usage_errors() -> Dict[str, List[str]]:
    """Ingest new usage once per refresh cycle; returns the per-source errors (a crash is one error)."""
    try:
        return dict(collect_usage().errors)
    except Exception as exc:  # the refresher must keep building cockpits
        return {COLLECTOR_ERROR_KEY: [_error_text(exc)]}


def _empty_day(day: str) -> dict:
    record: dict = {name: 0 for name in TOKEN_FIELDS}
    record.update(day=day, total_tokens=0, sessions=0, turns=0, capsules=0, capsule_tokens=0,
                  cost_usd=None, cost_sessions=0, sources=[])
    return record


def _add_row(record: dict, row: dict) -> None:
    source = row["source"]
    if source == JIT_SOURCE:
        record["capsules"] += row["capsules"]
        record["capsule_tokens"] += row["capsule_tokens"]
        return
    if source not in TOKEN_SOURCES:
        return
    record["sources"].append(source)
    for name in TOKEN_FIELDS:
        record[name] += row[name]
    record["total_tokens"] = sum(record[name] for name in TOKEN_FIELDS)
    record["sessions"] += row["sessions"]
    if source == CLAUDE_SOURCE:  # Hermes keeps api calls, not user turns
        record["turns"] += row["turns"]
    if row["cost_usd"] is not None:
        record["cost_usd"] = (record["cost_usd"] or 0.0) + row["cost_usd"]
        record["cost_sessions"] += row["cost_sessions"]


def _totals(days: List[dict]) -> dict:
    totals: dict = {name: sum(day[name] for day in days) for name in
                    (*TOKEN_FIELDS, "total_tokens", "sessions", "turns", "capsules", "cost_sessions")}
    costs = [day["cost_usd"] for day in days if day["cost_usd"] is not None]
    totals["cost_usd"] = sum(costs) if costs else None
    totals["active_days"] = sum(1 for day in days if day["sources"])
    return totals


def usage_section(conn, slug: str, since: str) -> dict:
    """Daily usage of one project; days without any stored row are absent (not zero)."""
    days: Dict[str, dict] = {}
    for row in store.read_daily(conn, project=slug, since=since):
        _add_row(days.setdefault(row["day"], _empty_day(row["day"])), row)
    ordered = [days[day] for day in sorted(days)]
    return {"days": ordered, "totals": _totals(ordered), "cost_sources": list(COST_SOURCES)}


def comparison_section(conn, slug: str, since: str, resolve: Callable) -> dict:
    """JIT on/off medians over the whole window for one project; groups are session-days."""
    records = [r for r in jit_compare.session_days(conn, resolve, since) if r["project"] == slug]
    jit_ids = jit_compare.jit_sessions(conn)
    jit_on = jit_compare.summarize([r for r in records if r["session_id"] in jit_ids])
    jit_off = jit_compare.summarize([r for r in records if r["session_id"] not in jit_ids])
    enough = jit_on["n"] >= jit_compare.MIN_GROUP_N and jit_off["n"] >= jit_compare.MIN_GROUP_N
    return {
        "label": jit_compare.OBSERVATION_LABEL, "low_n_label": jit_compare.LOW_N_LABEL,
        "min_group_n": jit_compare.MIN_GROUP_N, "unit": GROUP_UNIT,
        jit_compare.JIT_ON: jit_on, jit_compare.JIT_OFF: jit_off,
        "enough_data": enough, "warning": None if enough else jit_compare.LOW_N_LABEL,
        "definitions": dict(jit_compare.METRIC_DEFINITIONS),
    }


def ab_section(conn, slug: str) -> Optional[dict]:
    """Newest A/B batch of the project, or None when it never ran."""
    newest = conn.execute("SELECT batch_id FROM ab_runs WHERE project = ? ORDER BY id DESC LIMIT 1",
                          (slug,)).fetchone()
    if newest is None:
        return None
    rows = bench_store.read_batch(conn, newest["batch_id"])
    summary = bench_store.summarize(rows)
    return {
        "batch_id": newest["batch_id"], "date": min(row["started_at"] for row in rows),
        "model": ", ".join(sorted({row["model"] for row in rows})), "head": rows[0]["head"],
        "calls": len(rows), "errors": sum(1 for row in rows if row["is_error"]),
        "tasks": len({row["task_id"] for row in rows}), "runs": len({row["run_index"] for row in rows}),
        "arms": summary["arms"], "paired_on_minus_off": summary["paired_on_minus_off"],
    }


def _guarded(build: Callable[[], object]) -> object:
    try:
        return build()
    except Exception as exc:  # one broken section must not hide the others
        return {"error": _error_text(exc)}


def _store_sections(doc: dict, slug: str, since: str, db_path: Path, projects: List[dict]) -> None:
    if not db_path.exists():
        missing = {"missing": f"brak magazynu zużycia {db_path} (uruchom `jit hub usage`)"}
        doc.update(usage=dict(missing), comparison=dict(missing), ab=dict(missing))
        return
    try:
        conn = bench_store.connect(db_path)
    except Exception as exc:
        error = {"error": _error_text(exc)}
        doc.update(usage=dict(error), comparison=dict(error), ab=dict(error))
        return
    try:
        doc["usage"] = _guarded(lambda: usage_section(conn, slug, since))
        doc["comparison"] = _guarded(lambda: comparison_section(conn, slug, since, ProjectResolver(projects)))
        doc["ab"] = _guarded(lambda: ab_section(conn, slug))
    finally:
        conn.close()


def build_stats(entry: dict, now: Optional[datetime] = None, db_path: Optional[Path] = None,
                projects: Optional[List[dict]] = None,
                collect_errors: Optional[Dict[str, List[str]]] = None) -> dict:
    """The stats document of one registered project (local naive `now`, like the suggestions engine)."""
    slug = entry["slug"]
    now = now or datetime.now()
    since = (now.date() - timedelta(days=WINDOW_DAYS - 1)).isoformat()
    db = Path(db_path) if db_path else store.usage_db_path()
    projects = registry.load_projects() if projects is None else projects
    doc: dict = {
        "schema": SCHEMA_VERSION, "slug": slug, "project_path": entry["path"],
        "generated_at": now.astimezone().isoformat(timespec="seconds"), "window_days": WINDOW_DAYS,
        "since": since, "until": now.date().isoformat(), "usage_db": str(db),
        "collect_errors": dict(collect_errors or {}),
    }
    _store_sections(doc, slug, since, db, projects)
    doc["suggestions"] = _guarded(lambda: project_suggestions(Path(entry["path"]), slug=slug, now=now,
                                                              usage_db=db, projects=projects))
    return doc


def stats_digest(doc: dict) -> str:
    """Content hash without generation timestamps: equal digests mean nothing to show changed."""
    stable = {key: value for key, value in doc.items() if key not in ("generated_at", "digest")}
    suggestions = stable.get("suggestions")
    if isinstance(suggestions, dict):
        stable["suggestions"] = {k: v for k, v in suggestions.items() if k != "generated_at"}
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_stats(entry: dict, collect_errors: Optional[Dict[str, List[str]]] = None, **kwargs) -> str:
    """Build and atomically write stats/<slug>.json; returns the content digest."""
    doc = build_stats(entry, collect_errors=collect_errors, **kwargs)
    doc["digest"] = stats_digest(doc)
    path = stats_path(entry["slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
    os.replace(tmp, path)
    return doc["digest"]


def is_due(slug: str, max_age: float = STATS_MAX_AGE_SECONDS) -> bool:
    """True when the stats file is missing or older than `max_age` seconds."""
    try:
        return time.time() - stats_path(slug).stat().st_mtime >= max_age
    except OSError:
        return True
