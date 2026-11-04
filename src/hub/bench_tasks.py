"""Task sets for `jit bench ab`: default read-only questions from STATE.md + README, or a user file.

Default set: one question per open STATE.md task (`- [ ] ...`) and one question about running the project from
README, DEFAULT_TASK_COUNT in total (open tasks first, README question kept when a README exists). Nothing is
invented: with no open tasks and no README the default set is empty and the caller reports it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

DEFAULT_TASK_COUNT = 3
MAX_TASK_TEXT_CHARS = 300
STATE_RELATIVE = Path(".planning") / "STATE.md"
README_NAMES = ("README.md", "README.MD", "Readme.md", "readme.md", "README")
OPEN_TASK_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$")
HEADING_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")
READ_ONLY_RULE = "Nie modyfikuj żadnych plików i nie uruchamiaj komend; tylko czytaj kod."
OPEN_TASK_PROMPT = (
    "Zadanie z .planning/STATE.md tego repozytorium: \"{task}\". Na podstawie kodu wskaż pliki i funkcje, "
    "które trzeba zmienić lub przeczytać, aby je zrealizować (ścieżka:linia), i krótko uzasadnij. " + READ_ONLY_RULE
)
README_PROMPT = (
    "Projekt \"{title}\": na podstawie README i kodu podaj dokładne komendy do lokalnego uruchomienia projektu "
    "i jego testów oraz pliki, na których się opierasz (ścieżka:linia). " + READ_ONLY_RULE
)


@dataclass(frozen=True)
class BenchTask:
    task_id: str
    prompt: str


class TaskFileError(ValueError):
    """The --tasks file is missing, empty or malformed."""


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def open_tasks(project: Path) -> List[str]:
    """Texts of unchecked checklist items in .planning/STATE.md, in file order."""
    text = _read(project / STATE_RELATIVE) or ""
    found = []
    for line in text.splitlines():
        match = OPEN_TASK_RE.match(line)
        if match:
            found.append(match.group(1)[:MAX_TASK_TEXT_CHARS])
    return found


def readme_title(project: Path) -> Optional[str]:
    """First `# ` heading of the README, else the project folder name; None when there is no README."""
    for name in README_NAMES:
        text = _read(project / name)
        if text is None:
            continue
        for line in text.splitlines():
            match = HEADING_RE.match(line)
            if match:
                return match.group(1)[:MAX_TASK_TEXT_CHARS]
        return project.name
    return None


def default_tasks(project: Path, count: int = DEFAULT_TASK_COUNT) -> List[BenchTask]:
    """Up to `count` read-only questions: open STATE.md tasks first, then one README question."""
    title = readme_title(project)
    task_slots = count - 1 if title is not None else count
    tasks = [BenchTask(f"state-{index + 1}", OPEN_TASK_PROMPT.format(task=text))
             for index, text in enumerate(open_tasks(project)[:task_slots])]
    if title is not None:
        tasks.append(BenchTask("readme", README_PROMPT.format(title=title)))
    return tasks


def _from_json(raw: str) -> List[BenchTask]:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise TaskFileError(f"niepoprawny JSON: {exc}") from exc
    if not isinstance(data, list):
        raise TaskFileError("JSON musi być listą zadań")
    tasks = []
    for index, item in enumerate(data, 1):
        if isinstance(item, str) and item.strip():
            tasks.append(BenchTask(f"task-{index}", item.strip()))
        elif isinstance(item, dict) and str(item.get("prompt") or "").strip():
            tasks.append(BenchTask(str(item.get("id") or f"task-{index}"), str(item["prompt"]).strip()))
        else:
            raise TaskFileError(f"zadanie {index}: oczekiwano tekstu albo obiektu z polem prompt")
    return tasks


def load_task_file(path: Path) -> List[BenchTask]:
    """JSON list (strings or {id, prompt}) for *.json, else one prompt per non-empty line (# = comment)."""
    raw = _read(path)
    if raw is None:
        raise TaskFileError(f"nie można odczytać pliku: {path}")
    if path.suffix.lower() == ".json":
        tasks = _from_json(raw)
    else:
        lines = [line.strip() for line in raw.splitlines()]
        tasks = [BenchTask(f"task-{index}", line)
                 for index, line in enumerate((x for x in lines if x and not x.startswith("#")), 1)]
    if not tasks:
        raise TaskFileError(f"brak zadań w pliku: {path}")
    return tasks
