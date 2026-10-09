"""Small-model capsule profile: tighter capsule + skill pointers for local 2-9B workers.

Small local models (LFM, Qwen 9B, qwen-coder 7B on Ollama) run without the Hermes skills
index and without MEMORY/USER dumps (profile `small`). The JIT capsule compensates with a
short list of skill *pointers* (name + one line, fetched via `skill_view`) ranked against the
current goal, and a hard capsule cap so prefill stays in seconds.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SMALL_MODEL_PATTERNS = (r"\blfm", r"qwen[\d.]*[:-].*?\b[0-9]{1,2}b\b", r"qwen[\d.]*:jit", r"coder:7b",
                        r":[1-9]b\b", r"gemma\d*:\d{1,2}b", r"llama3\.\d:8b", r"norn")
SMALL_CAPSULE_CHAR_CAP = 4800
SMALL_BRIEF_CHAR_CAP = 2000
SKILL_POINTER_LIMIT = 6
SKILL_DESCRIPTION_CHARS = 90
SKILLS_ROOT = Path(os.path.expanduser("~/.hermes/skills"))
STOPWORDS = frozenset("the and for with when use this that from into your are not you all any".split())


def is_small_model(model: Optional[str]) -> bool:
    """True for local small models that get the compact capsule profile."""
    name = (model or "").lower()
    if not name or os.environ.get("JIT_SMALL_MODEL") == "0":
        return False
    if os.environ.get("JIT_SMALL_MODEL") == "1":
        return True
    return any(re.search(pattern, name) for pattern in SMALL_MODEL_PATTERNS)


def load_skill_catalog(root: Path = SKILLS_ROOT) -> List[Tuple[str, str]]:
    """(name, description) for every SKILL.md under root; frontmatter only, no bodies."""
    catalog = []
    for skill_file in sorted(root.glob("**/SKILL.md")):
        try:
            head = skill_file.read_text(encoding="utf-8", errors="ignore")[:1500]
        except OSError:
            continue
        name = re.search(r"^name:\s*(.+)$", head, re.M)
        description = re.search(r"^description:\s*(.+)$", head, re.M)
        if name:
            catalog.append((name.group(1).strip().strip("'\""), (description.group(1) if description else "").strip().strip("'\"")))
    return catalog


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-ząćęłńóśźż0-9]{3,}", text.lower()) if t not in STOPWORDS}


def rank_skill_pointers(goal: str, catalog: List[Tuple[str, str]], limit: int = SKILL_POINTER_LIMIT) -> List[Tuple[str, str]]:
    """Top skills by keyword overlap with the goal; name hits weigh double. Zero-score skills are dropped."""
    goal_tokens = _tokens(goal)
    scored = []
    for name, description in catalog:
        name_hits = len(goal_tokens & _tokens(name.replace("-", " ")))
        score = 2 * name_hits + len(goal_tokens & _tokens(description))
        if score > 0:
            scored.append((score, name, description))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(name, description) for _, name, description in scored[:limit]]


def render_skill_pointers(pointers: List[Tuple[str, str]]) -> str:
    if not pointers:
        return ""
    rows = [f"    - {name}: {description[:SKILL_DESCRIPTION_CHARS]}" for name, description in pointers]
    return "  [SKILL POINTERS — load with skill_view(name) only if needed]\n" + "\n".join(rows) + "\n"


def load_small_brief(session_cwd: Optional[str]) -> str:
    """.planning/CONTEXT_SMALL.md from `jit init --profile small`, searched up to the git root."""
    if not session_cwd:
        return ""
    current = Path(session_cwd)
    for folder in (current, *current.parents):
        brief = folder / ".planning" / "CONTEXT_SMALL.md"
        if brief.is_file():
            return brief.read_text(encoding="utf-8", errors="ignore")[:SMALL_BRIEF_CHAR_CAP]
        if (folder / ".git").exists():
            break
    return ""


def apply_small_model_profile(capsule: str, goal: str, model: Optional[str],
                              catalog: Optional[List[Tuple[str, str]]] = None,
                              session_cwd: Optional[str] = None) -> Tuple[str, Dict[str, object]]:
    """Insert project brief + skill pointers and enforce the small-model cap. Large models pass through unchanged."""
    if not capsule or not is_small_model(model):
        return capsule, {"small_model": False}
    pointers = rank_skill_pointers(goal, catalog if catalog is not None else load_skill_catalog())
    brief = load_small_brief(session_cwd)
    block = (f"  [PROJECT BRIEF — CONTEXT_SMALL.md]\n{brief.strip()}\n" if brief else "") + render_skill_pointers(pointers)
    closing = "</ONA_CONTEXT>"
    body = capsule
    if closing in body:
        head, tail = body.rsplit(closing, 1)
        body_cap = SMALL_CAPSULE_CHAR_CAP - len(block) - len(closing) - len(tail) - 20
        if len(head) > body_cap:
            head = head[:max(body_cap, 0)].rsplit("\n", 1)[0] + "\n  [...small-model cap]\n"
        body = head + block + closing + tail
    else:
        body = body[:SMALL_CAPSULE_CHAR_CAP]
    return body, {"small_model": True, "skill_pointers": [name for name, _ in pointers], "capsule_chars": len(body)}
