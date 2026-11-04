"""Suggestion rules that read tracked files: oversized code files, missing tests, README quickstart and the open
blockers listed in STATE.md."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from hub.bench_tasks import README_NAMES
from hub.suggestion_model import (
    SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM, STATE_FILE, ProjectContext, Suggestion, file_evidence,
    value_evidence,
)
from hub.suggestion_state import open_blockers as parse_blockers

MAX_FILE_LINES = 300
TOP_LARGE_FILES = 5
MAX_COUNTED_BYTES = 2_000_000  # bigger files are generated or data, not hand-written code
MAX_SHOWN_BLOCKERS = 5
CODE_EXTENSIONS = frozenset((
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".go", ".rs", ".java", ".kt",
    ".swift", ".rb", ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".sh", ".css", ".scss", ".html",
))
SKIPPED_DIRS = frozenset(("vendor", "node_modules", "dist", "build", "third_party", "migrations"))
TEST_DIR_NAMES = frozenset(("test", "tests", "__tests__", "spec", "specs", "e2e"))
TEST_FILE_RE = re.compile(
    r"(^test_.+\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(java|kt|swift)$|_spec\.rb$)")
PYTHON_TEST_RE = re.compile(r"(^test_.+\.py$|_test\.py$)")
NPM_DEFAULT_TEST = "no test specified"
TEST_TARGET_RE = re.compile(r"^test\s*:", re.M)
QUICKSTART_RE = re.compile(
    r"^#{1,6}\s.*(quick\s*start|getting started|szybki start|pierwsze kroki|instal|uruchom|setup|how to run)",
    re.I | re.M)


def _line_count(ctx: ProjectContext, rel_path: str) -> Optional[int]:
    try:
        data = (ctx.path / rel_path).read_bytes()
    except OSError:
        return None
    return data.count(b"\n") if len(data) <= MAX_COUNTED_BYTES else None


def _is_counted_code(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix.lower() not in CODE_EXTENSIONS or ".min." in pure.name:
        return False
    return not any(part in SKIPPED_DIRS for part in pure.parts[:-1])


def large_files(ctx: ProjectContext) -> Optional[Suggestion]:
    sizes: List[Tuple[int, str]] = []
    for path in filter(_is_counted_code, ctx.tracked_files):
        lines = _line_count(ctx, path)
        if lines is not None and lines > MAX_FILE_LINES:
            sizes.append((lines, path))
    if not sizes:
        return None
    top = sorted(sizes, key=lambda item: (-item[0], item[1]))[:TOP_LARGE_FILES]
    return Suggestion(
        "large_files", SEVERITY_LOW,
        f"{len(sizes)} plików z kodem ma ponad {MAX_FILE_LINES} linii (pokazano {len(top)} największych).",
        f"Podziel {top[0][1]} na moduły o jednej odpowiedzialności (< {MAX_FILE_LINES} linii), potem kolejne.",
        tuple(file_evidence(path, f"{lines} linii") for lines, path in top),
    )


def _test_files(files: List[str]) -> List[str]:
    found = []
    for path in files:
        pure = PurePosixPath(path)
        if TEST_FILE_RE.search(pure.name) or any(part.lower() in TEST_DIR_NAMES for part in pure.parts[:-1]):
            found.append(path)
    return found


def _npm_test_script(ctx: ProjectContext) -> Optional[str]:
    raw = ctx.read("package.json")
    if raw is None:
        return None
    try:
        script = (json.loads(raw).get("scripts") or {}).get("test")
    except (ValueError, AttributeError):
        return None
    return script if isinstance(script, str) and NPM_DEFAULT_TEST not in script else None


def _test_command(ctx: ProjectContext, tests: List[str]) -> Optional[str]:
    """Where a test command is declared, or None. Python test files count: pytest finds them without config."""
    script = _npm_test_script(ctx)
    if script:
        return f"package.json scripts.test: {script}"
    for name in ("Makefile", "justfile"):
        if TEST_TARGET_RE.search(ctx.read(name) or ""):
            return f"{name}: cel test"
    if "[tool.pytest" in (ctx.read("pyproject.toml") or "") or "[tool:pytest]" in (ctx.read("setup.cfg") or ""):
        return "konfiguracja pytest"
    for name in ("pytest.ini", "tox.ini", "noxfile.py", "Cargo.toml"):
        if ctx.read(name) is not None:
            return name
    if any(PYTHON_TEST_RE.search(PurePosixPath(path).name) for path in tests):
        return "pytest (wykrywa pliki test_*.py)"
    return None


def no_tests(ctx: ProjectContext) -> Optional[Suggestion]:
    tests = _test_files(ctx.tracked_files)
    command = _test_command(ctx, tests)
    if tests and command:
        return None
    missing = " ani ".join(name for name, ok in (("testów", tests), ("komendy testowej", command)) if not ok)
    return Suggestion(
        "no_tests", SEVERITY_HIGH if not tests else SEVERITY_MEDIUM,
        f"Brak {missing} w repozytorium.",
        "Dodaj katalog tests/ z testem kluczowego przepływu i jedną komendę, która go uruchamia (np. pytest, npm test).",
        (value_evidence("pliki testów (git ls-files)", f"{len(tests)}" + (f", np. {tests[0]}" if tests else "")),
         value_evidence("komenda testowa", command or "brak")),
    )


def readme_quickstart(ctx: ProjectContext) -> Optional[Suggestion]:
    name = next((candidate for candidate in README_NAMES if ctx.read(candidate) is not None), None)
    text = ctx.read(name) if name else None
    if text is not None and QUICKSTART_RE.search(text):
        return None
    return Suggestion(
        "readme_quickstart", SEVERITY_MEDIUM,
        "README nie istnieje." if text is None else f"{name} nie ma sekcji Quickstart.",
        "Dodaj do README sekcję Quickstart: instalacja, zmienne środowiskowe i uruchomienie w mniej niż 2 minuty.",
        (file_evidence(name or "README.md", "brak pliku" if text is None else "brak nagłówka Quickstart/Instalacja"),),
    )


def open_blockers(ctx: ProjectContext) -> Optional[Suggestion]:
    blockers = parse_blockers(ctx.require_state())
    if not blockers:
        return None
    shown = blockers[:MAX_SHOWN_BLOCKERS]
    return Suggestion(
        "open_blockers", SEVERITY_HIGH,
        f"{STATE_FILE} ma {len(blockers)} otwartych blokerów.",
        f"Rozwiąż lub eskaluj bloker: {shown[0]}; potem oznacz go w {STATE_FILE} jako zamknięty.",
        tuple(file_evidence(STATE_FILE, text) for text in shown),
    )
