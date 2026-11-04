"""Freshness refresher: rebuild a registered project's cockpit when its signature changes.

Untracked `.planning/state.html` is rebuilt in place; a tracked one is never touched and the hub keeps its own
copy at <hub dir>/cockpits/<slug>.html. Per project state lives in <hub dir>/state/<slug>.json:
{signature, built_at, source_sha, source_branch, duration_ms, error, failures, output, stats_digest, stats_error}.
Before a build (and at least every stats.STATS_MAX_AGE_SECONDS) the refresher writes <hub dir>/stats/<slug>.json
from the usage store and the suggestions engine; a changed stats digest rebuilds the cockpit even when the
signature did not change.
One failing project never stops the others; after MAX_FAILURES failed builds with the same signature the
project is skipped until the signature changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import config
from hub import registry
from hub import stats as hub_stats
from hub.gitinfo import _git_lines
from hub.signature import compute_signature
from l1.cockpit_sync import COCKPIT_FILE, is_tracked

MAX_FAILURES = 3
BUILD_TIMEOUT_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 60
ERROR_TEXT_LIMIT = 500
ROOT_COCKPIT_FILE = "state.html"
COCKPITS_DIR_NAME = "cockpits"
STATE_DIR_NAME = "state"

REBUILT = "rebuilt"
UNCHANGED = "unchanged"
FAILED = "failed"
SKIPPED_FAILING = "skipped-failing"


@dataclass
class RefreshResult:
    slug: str
    status: str
    detail: str = ""


def cockpits_dir() -> Path:
    return config.hub_dir() / COCKPITS_DIR_NAME


def state_path(slug: str) -> Path:
    return config.hub_dir() / STATE_DIR_NAME / f"{slug}.json"


def hub_cockpit_path(slug: str) -> Path:
    return cockpits_dir() / f"{slug}.html"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(slug: str) -> dict:
    try:
        data = json.loads(state_path(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(slug: str, state: dict) -> None:
    path = state_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def cockpit_is_tracked(project: Path) -> bool:
    """True when the repo tracks .planning/state.html (or a root state.html the builder would refresh)."""
    if is_tracked(project, COCKPIT_FILE):
        return True
    return (project / ROOT_COCKPIT_FILE).exists() and is_tracked(project, ROOT_COCKPIT_FILE)


def _git_value(project: Path, *args: str) -> Optional[str]:
    lines = _git_lines(project, *args)
    return lines[0].strip() if lines else None


def _run_builder(project: Path, output: Optional[Path], slug: str) -> None:
    """Run the vendored generator; raises RuntimeError with the builder's own message on failure."""
    builder = config.cockpit_builder()
    if not builder.exists():
        raise RuntimeError(f"builder missing: {builder}")
    command = ["node", str(builder), str(project), "--hub-slug", slug]
    if output is not None:
        command += ["--out", str(output)]
    try:
        res = subprocess.run(command, capture_output=True, text=True, timeout=BUILD_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"builder failed: {exc}") from exc
    if res.returncode != 0:
        message = (res.stderr or res.stdout).strip()[:ERROR_TEXT_LIMIT]
        raise RuntimeError(f"builder exit {res.returncode}: {message}")


def build_project(entry: dict, signature: str, previous: dict) -> dict:
    """Build one cockpit and return its new state record (errors are recorded, never raised)."""
    project = Path(entry["path"])
    started = time.monotonic()
    state = {"signature": signature, "built_at": None, "source_sha": None, "source_branch": None,
             "duration_ms": None, "error": None, "failures": 0, "output": None}
    try:
        if not project.is_dir():
            raise RuntimeError(f"project path missing: {project}")
        tracked = cockpit_is_tracked(project)
        output = hub_cockpit_path(entry["slug"]) if tracked else project / COCKPIT_FILE
        _run_builder(project, output if tracked else None, entry["slug"])
        state.update(built_at=_now(), output=str(output),
                     source_sha=_git_value(project, "rev-parse", "HEAD"),
                     source_branch=_git_value(project, "rev-parse", "--abbrev-ref", "HEAD"))
    except Exception as exc:  # one broken project must not stop the loop
        same_signature = previous.get("signature") == signature
        state.update(error=str(exc)[:ERROR_TEXT_LIMIT],
                     failures=(int(previous.get("failures") or 0) if same_signature else 0) + 1,
                     built_at=previous.get("built_at"), output=previous.get("output"),
                     source_sha=previous.get("source_sha"), source_branch=previous.get("source_branch"))
    state["duration_ms"] = int((time.monotonic() - started) * 1000)
    return state


def _decide(previous: dict, signature: str) -> Optional[str]:
    """Return a skip status, or None when the project needs a build."""
    if previous.get("signature") != signature:
        return None
    if previous.get("error"):
        return SKIPPED_FAILING if int(previous.get("failures") or 0) >= MAX_FAILURES else None
    output = previous.get("output")
    return UNCHANGED if output and Path(output).exists() else None


def _refresh_stats(entry: dict, previous: dict, force: bool,
                   collect_errors: Optional[Dict[str, List[str]]]) -> Tuple[Optional[str], Optional[str]]:
    """Write stats/<slug>.json when a build is due or the file is stale; returns (digest, error).
    A failed write keeps the previous digest and never blocks the build."""
    if not force and not hub_stats.is_due(entry["slug"]):
        return previous.get("stats_digest"), previous.get("stats_error")
    try:
        return hub_stats.write_stats(entry, collect_errors=collect_errors), None
    except Exception as exc:
        return previous.get("stats_digest"), str(exc)[:ERROR_TEXT_LIMIT]


def refresh_project(entry: dict, collect_errors: Optional[Dict[str, List[str]]] = None,
                    force: bool = False) -> RefreshResult:
    """Refresh one project; `force` rebuilds even an unchanged or repeatedly failing one (hub "rebuild now")."""
    slug = entry["slug"]
    previous = load_state(slug)
    try:
        signature = compute_signature(Path(entry["path"]))
    except Exception as exc:  # signature errors are reported like build errors
        signature = f"error:{exc}"
    skip = None if force else _decide(previous, signature)
    digest, stats_error = _refresh_stats(entry, previous, skip is None, collect_errors)
    if skip == UNCHANGED and digest != previous.get("stats_digest"):
        skip = None
    if skip is not None:
        return RefreshResult(slug, skip, previous.get("error") or "")
    state = build_project(entry, signature, previous)
    state.update(stats_digest=digest, stats_error=stats_error)
    save_state(slug, state)
    if state["error"]:
        return RefreshResult(slug, FAILED, f"{state['error']} (próba {state['failures']}/{MAX_FAILURES})")
    return RefreshResult(slug, REBUILT, f"{state['output']} ({state['duration_ms']} ms)")


def refresh_all(entries: Optional[List[dict]] = None,
                collect: Optional[Callable[[], Dict[str, List[str]]]] = None) -> List[RefreshResult]:
    """Ingest new usage once, then refresh every project (stats first, the cockpit when something changed)."""
    entries = registry.load_projects() if entries is None else entries
    collect_errors = (collect or hub_stats.collect_usage_errors)() if entries else {}
    results = []
    for entry in entries:
        try:
            results.append(refresh_project(entry, collect_errors))
        except Exception as exc:  # e.g. an unwritable state dir for one slug
            results.append(RefreshResult(str(entry.get("slug")), FAILED, str(exc)[:ERROR_TEXT_LIMIT]))
    return results


def run(interval: float, once: bool, report: Callable[[List[RefreshResult]], None],
        sleep: Callable[[float], None] = time.sleep) -> int:
    """Refresh every registered project, then repeat every `interval` seconds unless `once`.
    With `once` the exit code is 1 when any project failed, so scripts can tell."""
    while True:
        results = refresh_all()
        report(results)
        if once:
            return 1 if any(r.status == FAILED for r in results) else 0
        sleep(interval)
