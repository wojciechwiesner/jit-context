"""Hub action runs: read-only research agents (audit 360, security, market, monetization) started from the hub.

Each action has a prompt template `<action>.md` next to this file; `common.md` holds the rules shared by all.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Dict

TEMPLATES_DIR = Path(__file__).parent
COMMON_TEMPLATE = "common.md"
ACTION_LABELS: Dict[str, str] = {
    "audit360": "Audyt 360",
    "security": "Audyt bezpieczeństwa",
    "market": "Badanie rynku",
    "monetization": "Monetyzacja",
}
ACTIONS = tuple(ACTION_LABELS)


def template_path(action: str) -> Path:
    if action not in ACTION_LABELS:
        raise ValueError(f"unknown action: {action!r}")
    return TEMPLATES_DIR / f"{action}.md"


def render_prompt(action: str, slug: str, project_path: str, day: str) -> str:
    """Action template + shared rules with $slug, $path, $date and $label filled in."""
    values = {"slug": slug, "path": project_path, "date": day, "label": ACTION_LABELS[action]}
    parts = [template_path(action), TEMPLATES_DIR / COMMON_TEMPLATE]
    return "\n\n".join(Template(part.read_text(encoding="utf-8")).safe_substitute(values).strip()
                       for part in parts) + "\n"
