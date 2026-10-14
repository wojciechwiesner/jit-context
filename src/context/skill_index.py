"""Index of local agent skills (SKILL.md files) for per-project skill selection.

Reads only the YAML frontmatter (name, description, metadata.hermes.tags) with a
minimal parser, so no PyYAML dependency is needed. Parsed entries are cached
in-process by (path, mtime).
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_SKILLS_ROOT = Path.home() / ".hermes" / "skills"
SKILL_FILENAME = "SKILL.md"
EXCLUDED_PATH_MARKERS = ("/.archive", "/.hub")
FRONTMATTER_FENCE = "---"
MAX_FRONTMATTER_LINES = 80
BLOCK_SCALAR_MARKERS = ("|", ">", "|-", ">-", "|+", ">+")


@dataclass(frozen=True)
class SkillEntry:
    name: str
    description: str
    tags: Tuple[str, ...]
    path: Path

    @property
    def directory(self) -> Path:
        return self.path.parent


_CACHE: Dict[Tuple[str, float], Optional[SkillEntry]] = {}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _split_inline_list(value: str) -> List[str]:
    inner = value.strip().strip("[]")
    return [_unquote(part) for part in inner.split(",") if part.strip()]


def _extract_frontmatter(text: str) -> List[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return []
    block: List[str] = []
    for line in lines[1:MAX_FRONTMATTER_LINES]:
        if line.strip() == FRONTMATTER_FENCE:
            return block
        block.append(line)
    return []


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _read_scalar(block: List[str], index: int) -> str:
    """Read the value of `key: value` at block[index], including block scalars."""
    value = block[index].split(":", 1)[1].strip()
    if value not in BLOCK_SCALAR_MARKERS:
        return _unquote(value)
    base_indent = _indent(block[index])
    parts: List[str] = []
    for line in block[index + 1:]:
        if line.strip() and _indent(line) <= base_indent:
            break
        parts.append(line.strip())
    return " ".join(part for part in parts if part)


def _read_tags(block: List[str], index: int) -> List[str]:
    """Read tags given inline (`tags: [a, b]`) or as a block list."""
    value = block[index].split(":", 1)[1].strip()
    if value:
        return _split_inline_list(value)
    tags: List[str] = []
    for line in block[index + 1:]:
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        tags.append(_unquote(stripped[2:]))
    return tags


def parse_skill_text(text: str, path: Path) -> Optional[SkillEntry]:
    block = _extract_frontmatter(text)
    name, description, tags = "", "", []
    for index, line in enumerate(block):
        key = line.strip().split(":", 1)[0]
        if key == "name" and not name and _indent(line) == 0:
            name = _read_scalar(block, index)
        elif key == "description" and not description and _indent(line) == 0:
            description = _read_scalar(block, index)
        elif key == "tags" and not tags:
            tags = _read_tags(block, index)
    if not name:
        return None
    return SkillEntry(name=name, description=description, tags=tuple(tags), path=path)


def _is_excluded(path: Path, root: Path) -> bool:
    relative = "/" + path.relative_to(root).as_posix()
    if any(marker in relative for marker in EXCLUDED_PATH_MARKERS):
        return True
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _load_entry(path: Path) -> Optional[SkillEntry]:
    key = (str(path), path.stat().st_mtime)
    if key not in _CACHE:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        _CACHE[key] = parse_skill_text(text, path)
    return _CACHE[key]


def _iter_skill_files(root: Path) -> List[Path]:
    """All SKILL.md files under root, following symlinked skill dirs (Path.rglob does not)."""
    found = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=True):
        if SKILL_FILENAME in filenames:
            found.append(Path(dirpath) / SKILL_FILENAME)
    return sorted(found)


def scan_skills(root: Path = DEFAULT_SKILLS_ROOT) -> List[SkillEntry]:
    """Return all skills under root, sorted by name (first path wins on duplicates)."""
    if not root.is_dir():
        return []
    by_name: Dict[str, SkillEntry] = {}
    for path in _iter_skill_files(root):
        if _is_excluded(path, root):
            continue
        entry = _load_entry(path)
        if entry and entry.name not in by_name:
            by_name[entry.name] = entry
    return sorted(by_name.values(), key=lambda skill: skill.name)


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens of length >= 2 (shared by the selector)."""
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) >= 2]
