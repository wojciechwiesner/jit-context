"""Action reports: <hub dir>/reports/<slug>/<date>-<action>.md, copied to <vault projects>/<slug>/reports/.

The model text passes strip_emoji before it is written (product rule: no emoji in anything shown in the UI).
A second report of the same action on the same day gets a -2, -3 ... suffix instead of overwriting the first.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

import config
from hub.actions import ACTION_LABELS

REPORTS_DIR_NAME = "reports"
SAFE_NAME_RE = re.compile(r"[^a-z0-9_-]+")
EMOJI_RE = re.compile("[\\U0001F000-\\U0001FAFF\\u2600-\\u27BF\\u2B50-\\u2B55\\uFE0F\\u200D]")


def strip_emoji(text: str) -> Tuple[str, int]:
    """(text without pictographic characters, how many were removed)."""
    cleaned, count = EMOJI_RE.subn("", text)
    return cleaned, count


def safe_name(slug: str) -> str:
    return SAFE_NAME_RE.sub("-", slug.lower()).strip("-") or "project"


def reports_dir(slug: str) -> Path:
    return config.hub_dir() / REPORTS_DIR_NAME / safe_name(slug)


def mirror_dir(slug: str) -> Path:
    """Read per call so tests (and a moved vault) can point config.PROJECTS_DIR elsewhere."""
    return Path(config.PROJECTS_DIR) / safe_name(slug) / REPORTS_DIR_NAME


def _free_path(directory: Path, stem: str) -> Path:
    candidate, number = directory / f"{stem}.md", 1
    while candidate.exists():
        number += 1
        candidate = directory / f"{stem}-{number}.md"
    return candidate


def render(run: dict, body: str) -> str:
    cost = run.get("cost")
    header = [
        f"# {ACTION_LABELS.get(run['action'], run['action'])}: {run['slug']}",
        "",
        f"- Uruchomienie: `{run['id']}`",
        f"- Katalog projektu: `{run.get('project_path')}`",
        f"- Start: {run.get('started')}, koniec: {run.get('finished')}",
        f"- Koszt: {'brak danych' if cost is None else f'{cost:.4f} USD'}",
        "- Tryb: tylko odczyt (Read, Grep, Glob, WebSearch, WebFetch, git log/status, ls)",
        "",
        "---",
        "",
    ]
    return "\n".join(header) + body.strip() + "\n"


def save_report(run: dict, body: str, day: str) -> dict:
    """Write the report and its vault copy; fields for the run state (paths, mirror error, emoji count)."""
    cleaned, removed = strip_emoji(body)
    directory = reports_dir(run["slug"])
    directory.mkdir(parents=True, exist_ok=True)
    path = _free_path(directory, f"{day}-{run['action']}")
    path.write_text(render(run, cleaned), encoding="utf-8")
    fields = {"report_path": str(path), "emoji_removed": removed}
    mirror_path: Optional[Path] = None
    try:
        target_dir = mirror_dir(run["slug"])
        target_dir.mkdir(parents=True, exist_ok=True)
        mirror_path = _free_path(target_dir, path.stem)
        shutil.copyfile(path, mirror_path)
    except OSError as exc:
        fields["mirror_error"] = f"kopia do Obsidiana nieudana: {exc}"
        mirror_path = None
    fields["obsidian_path"] = str(mirror_path) if mirror_path else None
    return fields
