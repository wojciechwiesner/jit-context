"""System prompt of the hub project chat, built from the project's own files and the refresher's stats.

Sources, in priority order (each with its own character cap): the Obsidian dossier, .planning/STATE.md,
ROADMAP.md (trimmed), README head, .planning/ARCHITECTURE.mmd, the latest stats + suggestions. The whole prompt
is capped at MAX_PROMPT_CHARS. Every source appears in a visible list inside the prompt (and in the API reply):
included with its size and a truncation note, or missing / unreadable with the reason. Nothing is invented.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import config
from hub import overview, project_links

MAX_PROMPT_CHARS = 24000
SOURCE_LIST_RESERVE = 1600
MAX_SUGGESTIONS = 10
MIN_SECTION_CHARS = 200
TRUNCATION_NOTE = "\n[... obcięto {count} znaków]"
STATUS_INCLUDED = "included"
STATUS_MISSING = "missing"
STATUS_ERROR = "error"

STATE_FILE = Path(".planning") / "STATE.md"
ARCHITECTURE_FILE = Path(".planning") / "ARCHITECTURE.mmd"
ROADMAP_FILES = (Path(".planning") / "ROADMAP.md", Path("ROADMAP.md"))
README_FILES = (Path("README.md"), Path("readme.md"), Path("README"))

DOSSIER_CAP = 6000
STATE_CAP = 7000
ROADMAP_CAP = 3000
README_CAP = 2000
ARCHITECTURE_CAP = 2500
STATS_CAP = 2500

HEADER = (
    "Jesteś asystentem projektu \"{slug}\" w Project Hub (JIT Context). Odpowiadaj po polsku, zwięźle i "
    "konkretnie. Opieraj się wyłącznie na źródłach poniżej; jeśli czegoś w nich nie ma, powiedz wprost, że tego "
    "nie wiesz, zamiast zgadywać. Podawaj, z którego źródła pochodzi informacja. Nie używaj emoji. Nie "
    "modyfikujesz plików: proponowane zmiany są tylko propozycjami.\n"
    "Ścieżka projektu: {path}\n"
)


@dataclass
class Source:
    """One prompt source: what it is, where it comes from, and what happened to it."""

    name: str
    ref: str
    status: str
    chars: int = 0
    truncated: bool = False
    reason: str = ""
    text: str = ""

    def public(self) -> dict:
        record = asdict(self)
        record.pop("text")
        return record


def _read_text(path: Path) -> Tuple[Optional[str], str]:
    """(text, "") when readable; (None, reason) when missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace"), ""
    except FileNotFoundError:
        return None, f"brak pliku {path}"
    except OSError as exc:  # e.g. no TCC access to ~/Documents from launchd
        return None, f"nie można odczytać {path}: {type(exc).__name__}: {exc}"


def _file_source(name: str, candidates: Tuple[Path, ...]) -> Source:
    reasons = []
    for path in candidates:
        text, reason = _read_text(path)
        if text is not None:
            return Source(name, str(path), STATUS_INCLUDED, text=text)
        reasons.append(reason)
    unreadable = [reason for reason in reasons if not reason.startswith("brak pliku")]
    status = STATUS_ERROR if unreadable else STATUS_MISSING
    return Source(name, str(candidates[0]), status, reason="; ".join(unreadable or reasons))


def dossier_source(project: Path) -> Source:
    link = project_links.dossier(project)
    source = _file_source("Notatka projektu (Obsidian)", (Path(config.PROJECTS_DIR) / f"{link['name']}.md",))
    if source.status != STATUS_INCLUDED:
        source.reason += f" (nazwa z: {link['source']})"
    return source


def stats_text(stats: dict, today: date) -> Tuple[Optional[str], str]:
    """Compact JSON of the stats file: usage totals, 7-day tokens, comparison, A/B, top suggestions."""
    if "missing" in stats or "error" in stats:
        return None, str(stats.get("missing") or stats.get("error"))
    usage = stats.get("usage") if isinstance(stats.get("usage"), dict) else {}
    suggestions = stats.get("suggestions") if isinstance(stats.get("suggestions"), dict) else {}
    digest = {
        "generated_at": stats.get("generated_at"), "window_days": stats.get("window_days"),
        "usage_totals": usage.get("totals", usage.get("missing") or usage.get("error")),
        "tokens_last_7_days": overview.tokens_last_days(stats, today),
        "jit_comparison": stats.get("comparison"), "ab": stats.get("ab"),
        "suggestions": (suggestions.get("suggestions") or [])[:MAX_SUGGESTIONS]
        if "error" not in suggestions else suggestions,
    }
    return json.dumps(digest, ensure_ascii=False, indent=1, default=str), ""


def stats_source(slug: str, today: date) -> Source:
    ref = "stats/" + slug + ".json"
    try:
        text, reason = stats_text(overview.load_stats(slug), today)
    except Exception as exc:  # a broken stats file must not stop the chat
        text, reason = None, f"{type(exc).__name__}: {exc}"
    if text is None:
        status = STATUS_ERROR if reason and not reason.startswith("brak") else STATUS_MISSING
        return Source("Statystyki i sugestie huba", ref, status, reason=reason)
    return Source("Statystyki i sugestie huba", ref, STATUS_INCLUDED, text=text)


def collect_sources(entry: dict, today: Optional[date] = None) -> List[Tuple[Source, int]]:
    """Every source with its character cap, in priority order."""
    project = Path(entry["path"])
    builders: List[Tuple[Callable[[], Source], int]] = [
        (lambda: dossier_source(project), DOSSIER_CAP),
        (lambda: _file_source("STATE.md", (project / STATE_FILE,)), STATE_CAP),
        (lambda: _file_source("ROADMAP.md", tuple(project / rel for rel in ROADMAP_FILES)), ROADMAP_CAP),
        (lambda: _file_source("README (początek)", tuple(project / rel for rel in README_FILES)), README_CAP),
        (lambda: _file_source("ARCHITECTURE.mmd", (project / ARCHITECTURE_FILE,)), ARCHITECTURE_CAP),
        (lambda: stats_source(entry["slug"], today or date.today()), STATS_CAP),
    ]
    return [(build(), cap) for build, cap in builders]


def _fit(source: Source, cap: int) -> None:
    """Trim the source text to `cap` characters, note included size and truncation."""
    text = source.text.strip()
    if text and cap < MIN_SECTION_CHARS:
        source.text, source.status = "", STATUS_MISSING
        source.reason = f"pominięto: wyczerpany limit {MAX_PROMPT_CHARS} znaków promptu"
        return
    if len(text) > cap:
        note = TRUNCATION_NOTE.format(count=len(text) - cap)
        text = text[:max(cap - len(note), 0)].rstrip() + note
        source.truncated = True
    source.text, source.chars = text, len(text)
    if not text:
        source.status, source.reason = STATUS_MISSING, f"pusty plik {source.ref}"


def source_list(sources: List[Source]) -> str:
    lines = ["Źródła w tym prompcie:"]
    for source in sources:
        if source.status == STATUS_INCLUDED:
            extra = ", obcięte" if source.truncated else ""
            lines.append(f"- {source.name} ({source.ref}): {source.chars} znaków{extra}")
        else:
            label = "brak" if source.status == STATUS_MISSING else "błąd"
            lines.append(f"- {source.name}: {label}: {source.reason}")
    return "\n".join(lines) + "\n"


def build_system_prompt(entry: dict, today: Optional[date] = None) -> Tuple[str, List[dict]]:
    """(system prompt <= MAX_PROMPT_CHARS, public source list)."""
    header = HEADER.format(slug=entry["slug"], path=entry["path"])
    budget = MAX_PROMPT_CHARS - len(header) - SOURCE_LIST_RESERVE
    sources = []
    for source, cap in collect_sources(entry, today):
        if source.status == STATUS_INCLUDED:
            _fit(source, min(cap, budget))
            budget -= source.chars
        sources.append(source)
    sections = [f"\n=== {source.name} ({source.ref}) ===\n{source.text}\n"
                for source in sources if source.status == STATUS_INCLUDED and source.chars]
    prompt = header + "\n" + source_list(sources) + "".join(sections)
    if len(prompt) > MAX_PROMPT_CHARS:  # autocheck: the reserve was too small for the source list
        prompt = prompt[:MAX_PROMPT_CHARS]
    return prompt, [source.public() for source in sources]
