"""`jit init --profile small`: compact project brief for local 2-9B models.

Writes two files into <project>/.planning/:
- CONTEXT_SMALL.md  <= SMALL_BRIEF_CHAR_CAP chars: stack, verify command, entry files,
  top-level layout, current focus from STATE.md, and the hard rules a small worker needs.
- jit.json          machine-readable profile: target model, capsule cap, toolsets.
The JIT hook injects CONTEXT_SMALL.md (via project summary) instead of the full dossier
for small models, so the worker starts with the facts, not a haystack.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

SMALL_BRIEF_CHAR_CAP = 2000
DEFAULT_SMALL_MODEL = "lfm2.5:2.6b-64k"
SMALL_TOOLSETS = ["file", "terminal", "mcp-mem-agent", "mcp-jit-context"]
IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".planning"}
HARD_RULES = (
    "Read a file before editing it; edit with patch, never rewrite whole files.",
    "Prove every claim with a command result (test, curl, exit code).",
    "Never touch .env or secrets; no destructive git commands.",
)


def detect_verify_command(root: Path) -> str:
    """Same detection order as the JIT compiler dev runtime."""
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").is_dir():
        return "python3 -m pytest -q"
    if (root / "package.json").exists():
        return "npm test"
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "go.mod").exists():
        return "go test ./..."
    return "(none detected)"


def top_level_layout(root: Path, limit: int = 12) -> List[str]:
    entries = sorted(p for p in root.iterdir() if not p.name.startswith(".") and _plain_name(p.name))
    dirs = [f"{p.name}/" for p in entries if p.is_dir() and p.name not in IGNORED_DIRS]
    files = [p.name for p in entries if p.is_file()]
    return (dirs + files)[:limit]


def _plain_name(name: str) -> bool:
    """Skip junk entries (stray pasted scripts saved as file names, control chars, very long names)."""
    return len(name) <= 60 and re.fullmatch(r"[\w.@+-]+", name) is not None


def current_focus(root: Path, max_lines: int = 6) -> List[str]:
    """Body of the focus section in .planning/STATE.md (Current focus / Current position / Active goal)."""
    state_file = root / ".planning" / "STATE.md"
    if not state_file.exists():
        return []
    text = state_file.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^#+\s*(?:Current (?:focus|position)|Active goal)[^\n]*\n(.*?)(?=^#+\s|\Z)", text, re.M | re.S | re.I)
    body = match.group(1) if match else text
    lines = [line.strip() for line in body.splitlines()
             if line.strip() and not line.lstrip().startswith(("#", "<!--"))]
    return lines[:max_lines]


def build_small_brief(root: Path, stack: Dict[str, Any], goal: str | None) -> str:
    languages = ", ".join(stack.get("languages", [])) or "unknown"
    frameworks = ", ".join(stack.get("frameworks", [])) or "none"
    entry = ", ".join(stack.get("entrypoints", [])[:5]) or "see layout"
    sections = [
        f"# {root.name} — small-model brief",
        f"Goal: {goal or 'see STATE.md'}",
        f"Stack: {languages} | Frameworks: {frameworks}",
        f"Verify: `{detect_verify_command(root)}`",
        f"Entry: {entry}",
        "Layout: " + " ".join(top_level_layout(root)),
    ]
    focus = current_focus(root)
    if focus:
        sections.append("Focus (STATE.md):\n" + "\n".join(f"- {line[:140]}" for line in focus))
    sections.append("Rules:\n" + "\n".join(f"- {rule}" for rule in HARD_RULES))
    brief = "\n".join(sections) + "\n"
    if len(brief) > SMALL_BRIEF_CHAR_CAP:
        brief = brief[:SMALL_BRIEF_CHAR_CAP - 20].rsplit("\n", 1)[0] + "\n[...capped]\n"
    return brief


def write_small_profile(root: Path, stack: Dict[str, Any], goal: str | None, model: str = DEFAULT_SMALL_MODEL) -> Dict[str, str]:
    planning = root / ".planning"
    planning.mkdir(parents=True, exist_ok=True)
    brief_file = planning / "CONTEXT_SMALL.md"
    brief_file.write_text(build_small_brief(root, stack, goal), encoding="utf-8")
    profile_file = planning / "jit.json"
    existing = json.loads(profile_file.read_text(encoding="utf-8")) if profile_file.exists() else {}
    existing["small"] = {
        "model": model,
        "hermes_profile": "small",
        "capsule_char_cap": 4800,
        "brief": "CONTEXT_SMALL.md",
        "toolsets": SMALL_TOOLSETS,
    }
    profile_file.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {"brief": str(brief_file), "profile": str(profile_file), "brief_chars": str(brief_file.stat().st_size)}
