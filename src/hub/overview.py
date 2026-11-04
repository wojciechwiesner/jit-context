"""Read-only per project summary for the hub API: freshness, last activity, open tasks, blockers, tokens, advice.

Every section is either data or {"missing": reason} / {"error": text}; nothing is estimated or defaulted to zero.
Sources: the registry entry, the refresher state (<hub dir>/state/<slug>.json), the refresher-written stats file
(<hub dir>/stats/<slug>.json), the repo's .planning/STATE.md and `git for-each-ref` over local branches (worktree
branches included, detached worktrees are not seen).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from hub import project_links, refresher
from hub import stats as hub_stats
from hub.bench_tasks import STATE_RELATIVE, open_tasks
from hub.gitinfo import _git_lines
from hub.signature import compute_signature
from hub.suggestion_state import open_blockers

TOKEN_WINDOW_DAYS = 7
MAX_LISTED_ITEMS = 5
FIELD_SEPARATOR = "\x1f"
LAST_ACTIVITY_FORMAT = FIELD_SEPARATOR.join(
    ("%(committerdate:iso-strict)", "%(refname:short)", "%(objectname:short)", "%(subject)"))

FRESH = "fresh"
STALE = "stale"
NEVER_BUILT = "never_built"
BUILD_ERROR = "error"


def _missing(reason: str) -> dict:
    return {"missing": reason}


def version(slug: str) -> dict:
    """What the cockpit polls: changes whenever the refresher records a new build."""
    state = refresher.load_state(slug)
    return {"slug": slug, "built_at": state.get("built_at"), "signature": state.get("signature"),
            "error": state.get("error")}


def freshness(entry: dict) -> dict:
    state = refresher.load_state(entry["slug"])
    record = {key: state.get(key) for key in
              ("built_at", "source_sha", "source_branch", "error", "failures", "output")}
    if not state:
        return dict(record, status=NEVER_BUILT, signature_matches=None)
    try:
        current: Optional[str] = compute_signature(Path(entry["path"]))
    except Exception as exc:  # report it, the row still renders
        current, record["signature_error"] = None, f"{type(exc).__name__}: {exc}"
    matches = None if current is None else current == state.get("signature")
    if state.get("error"):
        status = BUILD_ERROR
    elif matches and state.get("output") and Path(state["output"]).exists():
        status = FRESH
    else:
        status = STALE
    return dict(record, status=status, signature_matches=matches)


def last_activity(path: Path) -> dict:
    lines = _git_lines(path, "for-each-ref", "--sort=-committerdate", "--count=1",
                       f"--format={LAST_ACTIVITY_FORMAT}", "refs/heads")
    if lines is None:
        return {"error": "git for-each-ref nie powiodło się (brak repozytorium git?)"}
    if not lines or not lines[0].strip():
        return _missing("brak commitów w lokalnych gałęziach")
    at, branch, sha, subject = (lines[0].split(FIELD_SEPARATOR) + ["", "", "", ""])[:4]
    return {"at": at, "branch": branch, "sha": sha, "subject": subject}


def _state_md(path: Path) -> Optional[str]:
    try:
        return (path / STATE_RELATIVE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _listing(items: List[str]) -> dict:
    return {"count": len(items), "items": items[:MAX_LISTED_ITEMS]}


def tasks_and_blockers(path: Path) -> dict:
    text = _state_md(path)
    if text is None:
        reason = _missing(f"brak pliku {STATE_RELATIVE}")
        return {"open_tasks": reason, "blockers": dict(reason)}
    return {"open_tasks": _listing(open_tasks(path)), "blockers": _listing(open_blockers(text))}


def load_stats(slug: str) -> dict:
    path = hub_stats.stats_path(slug)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _missing(f"brak pliku {path} (zapisuje go refresher huba)")
    except (OSError, ValueError) as exc:
        return {"error": f"nieczytelny {path}: {exc}"}
    return doc if isinstance(doc, dict) else {"error": f"nieczytelny {path}: to nie jest obiekt JSON"}


def tokens_last_days(stats: dict, today: date, days: int = TOKEN_WINDOW_DAYS) -> dict:
    if "missing" in stats or "error" in stats:
        return stats
    usage = stats.get("usage")
    if not isinstance(usage, dict):
        return _missing("plik statystyk bez sekcji usage")
    if "error" in usage or "missing" in usage:
        return {key: usage[key] for key in ("error", "missing") if key in usage}
    since = (today - timedelta(days=days - 1)).isoformat()
    window = [day for day in usage.get("days") or [] if str(day.get("day", "")) >= since]
    if not window:
        return dict(_missing(f"brak zapisanego użycia od {since}"), since=since,
                    stats_generated_at=stats.get("generated_at"))
    return {"total_tokens": sum(int(day.get("total_tokens") or 0) for day in window),
            "days_with_data": len(window), "since": since, "stats_generated_at": stats.get("generated_at")}


def top_suggestion(stats: dict) -> Optional[dict]:
    """The highest severity suggestion; None when the engine found nothing (not when data is missing)."""
    if "missing" in stats or "error" in stats:
        return stats
    report = stats.get("suggestions")
    if not isinstance(report, dict):
        return _missing("plik statystyk bez sekcji suggestions")
    if "error" in report:
        return {"error": report["error"]}
    found = report.get("suggestions") or []
    return found[0] if found else None


def project_summary(entry: dict, today: Optional[date] = None) -> dict:
    path = Path(entry["path"])
    row = {key: entry.get(key) for key in ("slug", "path", "added_at", "last_init_at")}
    row["exists"] = path.is_dir()
    row["freshness"] = freshness(entry)
    if not row["exists"]:
        gone = _missing(f"katalog projektu nie istnieje: {path}")
        row.update(last_activity=gone, open_tasks=gone, blockers=gone, worktrees=gone, dossier=gone)
    else:
        row["last_activity"] = last_activity(path)
        row.update(tasks_and_blockers(path))
        row["worktrees"] = project_links.worktrees(path)
        row["dossier"] = project_links.dossier(path)
    stats = load_stats(entry["slug"])
    row["tokens_7d"] = tokens_last_days(stats, today or date.today())
    row["top_suggestion"] = top_suggestion(stats)
    return row
