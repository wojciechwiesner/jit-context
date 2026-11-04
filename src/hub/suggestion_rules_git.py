"""Suggestion rules that read git history and the index: freshness of STATE.md, the diagram, tracked cockpit,
CHANGELOG discipline, tracked .env files and a project that stopped moving with work still open."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from hub.bench_tasks import open_tasks
from hub.suggestion_model import (
    SECONDS_PER_DAY, SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM, STATE_FILE, MissingData, ProjectContext,
    Suggestion, command_evidence, file_evidence, format_ts, value_evidence,
)
from l1.cockpit_sync import ARCHITECTURE_FILE, COCKPIT_FILE, architecture_drift, is_tracked

STATE_STALE_DAYS = 3
INACTIVE_DAYS = 14
CHANGELOG_WINDOW_COMMITS = 10
# Enough history to find CHANGELOG_WINDOW_COMMITS code commits between docs-only commits.
CHANGELOG_SCAN_COMMITS = 200
CHANGELOG_NAMES = ("changelog.md", "changelog", "changes.md", "history.md")
NON_CODE_DIRS = (".planning/", "docs/")
ENV_SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")
NEWEST_COMMIT_COMMAND = "git log --branches HEAD -1 --format=%ct"


def _state_updated_at(ctx: ProjectContext) -> Tuple[float, str]:
    """When STATE.md last changed: its mtime when it differs from git, else its newest commit on any branch."""
    dirty = ctx.git("status", "--porcelain", "--", STATE_FILE)
    if dirty is None or dirty.strip():
        return (ctx.path / STATE_FILE).stat().st_mtime, "zmiana niezatwierdzona (mtime pliku)"
    out = ctx.git("log", "--branches", "HEAD", "-1", "--format=%ct", "--", STATE_FILE)
    if not out or not out.strip():
        return (ctx.path / STATE_FILE).stat().st_mtime, "mtime pliku"
    return float(out.strip()), "ostatni commit pliku"


def state_stale(ctx: ProjectContext) -> Optional[Suggestion]:
    ctx.require_state()
    newest_ts, sha, subject = ctx.require_newest_commit()
    state_ts, how = _state_updated_at(ctx)
    lag_days = (newest_ts - state_ts) / SECONDS_PER_DAY
    if lag_days <= STATE_STALE_DAYS:
        return None
    return Suggestion(
        "state_stale", SEVERITY_MEDIUM,
        f"{STATE_FILE} jest starszy od najnowszego commita o {lag_days:.1f} dni (próg {STATE_STALE_DAYS}).",
        f"Zaktualizuj {STATE_FILE}: odhacz zrobione zadania i wpisz bieżącą fazę oraz blokery.",
        (file_evidence(STATE_FILE, f"{format_ts(state_ts)} ({how})"),
         command_evidence(NEWEST_COMMIT_COMMAND, f"{format_ts(newest_ts)} {sha} {subject}")),
    )


def architecture_stale(ctx: ProjectContext) -> Optional[Suggestion]:
    if ctx.read(ARCHITECTURE_FILE) is None:
        raise MissingData(f"brak {ARCHITECTURE_FILE}")
    warning = architecture_drift(ctx.path)
    if warning is None:
        return None
    return Suggestion(
        "architecture_drift", SEVERITY_LOW, warning,
        f"Przerysuj {ARCHITECTURE_FILE} według aktualnych modułów i zatwierdź go razem z kodem.",
        (file_evidence(ARCHITECTURE_FILE, warning),),
    )


def cockpit_tracked(ctx: ProjectContext) -> Optional[Suggestion]:
    if not is_tracked(ctx.path, COCKPIT_FILE):
        return None
    return Suggestion(
        "cockpit_tracked", SEVERITY_LOW,
        f"{COCKPIT_FILE} jest śledzony w git, więc odświeżanie kokpitu brudziłoby drzewo roboczego repozytorium.",
        "Uruchom `jit cockpit untrack` i zatwierdź zmianę .gitignore.",
        (command_evidence(f"git ls-files --error-unmatch {COCKPIT_FILE}", "plik jest w indeksie"),),
    )


def _is_code_path(path: str) -> bool:
    return not (path.startswith(NON_CODE_DIRS) or path.lower().endswith(".md"))


def _commits_with_files(ctx: ProjectContext) -> List[Tuple[str, List[str]]]:
    out = ctx.git("log", "--no-merges", f"-{CHANGELOG_SCAN_COMMITS}", "--format=%x01%h", "--name-only")
    if out is None:
        raise MissingData("git log nie działa")
    commits = []
    for block in out.split("\x01")[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines:
            commits.append((lines[0], lines[1:]))
    return commits


def changelog_stale(ctx: ProjectContext) -> Optional[Suggestion]:
    code_commits = [(sha, files) for sha, files in _commits_with_files(ctx) if any(map(_is_code_path, files))]
    window = code_commits[:CHANGELOG_WINDOW_COMMITS]
    if len(window) < CHANGELOG_WINDOW_COMMITS:
        return None  # too little history to judge the habit
    touched = [sha for sha, files in window
               if any(PurePosixPath(name).name.lower() in CHANGELOG_NAMES for name in files)]
    if touched:
        return None
    present = any(PurePosixPath(name).name.lower() in CHANGELOG_NAMES for name in ctx.tracked_files)
    return Suggestion(
        "changelog_stale", SEVERITY_MEDIUM,
        f"CHANGELOG nie był zmieniany w ostatnich {CHANGELOG_WINDOW_COMMITS} commitach z kodem.",
        "Dopisz do CHANGELOG.md sekcję [Unreleased] z tymi zmianami i aktualizuj ją w każdym commicie.",
        (file_evidence("CHANGELOG.md", "jest w repozytorium" if present else "brak pliku"),
         command_evidence("git log --no-merges --name-only",
                          f"commity z kodem bez CHANGELOG: {', '.join(sha for sha, _ in window)}")),
    )


def _is_env_file(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if name != ".env" and not name.startswith(".env."):
        return False
    return not name.endswith(ENV_SAFE_SUFFIXES)


def env_tracked(ctx: ProjectContext) -> Optional[Suggestion]:
    found = [path for path in ctx.tracked_files if _is_env_file(path)]
    if not found:
        return None
    return Suggestion(
        "env_tracked", SEVERITY_HIGH,
        f"Pliki środowiskowe są śledzone w git: {', '.join(found)}.",
        "Usuń je z indeksu (`git rm --cached <plik>`), dodaj do .gitignore i zrotuj zawarte w nich sekrety.",
        tuple(file_evidence(path, "śledzony w git (treści nie czytano)") for path in found),
    )


def inactive_with_open_tasks(ctx: ProjectContext) -> Optional[Suggestion]:
    ctx.require_state()
    newest_ts, sha, subject = ctx.require_newest_commit()
    idle_days = (ctx.now.timestamp() - newest_ts) / SECONDS_PER_DAY
    tasks = open_tasks(ctx.path)
    if idle_days <= INACTIVE_DAYS or not tasks:
        return None
    return Suggestion(
        "inactive_with_open_tasks", SEVERITY_MEDIUM,
        f"Brak commitów od {idle_days:.0f} dni, a w {STATE_FILE} jest {len(tasks)} otwartych zadań.",
        f"Zdecyduj o projekcie: zaplanuj następny krok albo zamknij lub przenieś otwarte zadania w {STATE_FILE}.",
        (command_evidence(NEWEST_COMMIT_COMMAND, f"{format_ts(newest_ts)} {sha} {subject}"),
         file_evidence(STATE_FILE, f"otwarte zadania: {len(tasks)}, pierwsze: {tasks[0]}"),
         value_evidence("dni bez commitów", f"{idle_days:.0f} (próg {INACTIVE_DAYS})")),
    )
