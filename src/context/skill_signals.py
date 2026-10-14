"""Project signals used to pick skills: stack terms plus free-text project hints."""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from context.skill_index import tokenize

README_LINES = 40
STATE_HEADING_LIMIT = 30
# A free-text word triggers a hint only when it recurs, so one stray mention is not enough.
HINT_TEXT_MIN_COUNT = 3
# Stack tokens too generic to identify a skill (e.g. the "google" in "@google/genai").
GENERIC_STACK_TOKENS = frozenset({"google", "js", "node"})
STACK_KEYS = ("languages", "frameworks", "databases", "test_runners", "libraries", "package_managers")
HELPER_KEY = "helper_languages"

# Words that carry no project meaning but show up in READMEs and headings.
TEXT_STOPWORDS = frozenset(
    "the and for with from this that are you your use using into app project phase "
    "state goal tasks active initial core implementation runtime verification "
    "deployment context jit md readme".split()
)

# Stack/text term -> skill-name or tag words that get a boost when the term is present.
# Data-driven: extend this table, not the scoring code.
STACK_SKILL_HINTS: Dict[str, tuple] = {
    "vitest": ("vitest", "frontend"),
    "jest": ("jest",),
    "playwright": ("playwright", "e2e"),
    "typescript": ("typescript",),
    "javascript": ("javascript",),
    "vite": ("vite", "frontend"),
    "react": ("react", "frontend"),
    "next": ("nextjs", "next", "frontend"),
    "astro": ("astro", "frontend"),
    "tailwind": ("tailwind", "css", "frontend"),
    "pytest": ("pytest", "python"),
    "python": ("python",),
    "fastapi": ("fastapi", "python"),
    "docker": ("docker", "devops"),
    "prisma": ("prisma", "database"),
    "supabase": ("supabase", "database"),
    "audio": ("audio", "dsp"),
    "dsp": ("audio", "dsp"),
    "webaudio": ("audio", "dsp"),
    "synth": ("audio", "dsp"),
    "oscillator": ("audio", "dsp"),
    "whatsapp": ("whatsapp",),
    "mcp": ("mcp",),
}


@dataclass
class ProjectSignals:
    """Weighted token sets: stack terms are strong, free text is weak."""
    name: str
    stack_terms: List[str] = field(default_factory=list)
    helper_terms: List[str] = field(default_factory=list)
    text_tokens: List[str] = field(default_factory=list)
    frequent_text_tokens: List[str] = field(default_factory=list)

    def all_tokens(self) -> set:
        tokens = set(self.stack_terms) | set(self.text_tokens)
        tokens |= {tok for term in self.stack_terms for tok in tokenize(term)}
        return tokens


def _read_head(path: Path, max_lines: int) -> List[str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for _, line in zip(range(max_lines), handle)]
    except OSError:
        return []


def _state_headings(planning_state: Path) -> List[str]:
    lines = _read_head(planning_state, 400)
    headings = [ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")]
    return headings[:STATE_HEADING_LIMIT]


def _stack_terms(stack: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    for key in STACK_KEYS:
        terms.extend(str(item).lower() for item in stack.get(key) or [])
    manager = stack.get("package_manager")
    if manager:
        terms.append(str(manager).lower())
    return sorted(set(terms))


def _clean_text_tokens(chunks: List[str]) -> Counter:
    tokens = tokenize(" ".join(chunks))
    return Counter(tok for tok in tokens if tok not in TEXT_STOPWORDS and not tok.isdigit())


def collect_signals(
    project: Path,
    stack: Dict[str, Any],
    dossier_file: Optional[Path] = None,
) -> ProjectSignals:
    """Gather stack terms and free-text tokens (name, README head, STATE headings, dossier)."""
    chunks = [project.name.replace("-", " ").replace("_", " ")]
    chunks.extend(_read_head(project / "README.md", README_LINES))
    chunks.extend(_state_headings(project / ".planning" / "STATE.md"))
    if dossier_file is not None and dossier_file.is_file():
        chunks.extend(_read_head(dossier_file, README_LINES))
    helpers = [str(item).lower() for item in stack.get(HELPER_KEY) or []]
    counts = _clean_text_tokens(chunks)
    return ProjectSignals(
        name=project.name,
        stack_terms=_stack_terms(stack),
        helper_terms=helpers,
        text_tokens=sorted(counts),
        frequent_text_tokens=sorted(t for t, n in counts.items() if n >= HINT_TEXT_MIN_COUNT),
    )


def normalize_hint_term(term: str) -> str:
    """'Next.js' -> 'next', 'Web Audio' -> 'webaudio' so they match STACK_SKILL_HINTS keys."""
    cleaned = re.sub(r"\.js$", "", term.lower())
    return re.sub(r"[^a-z0-9]", "", cleaned)
