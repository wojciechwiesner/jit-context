"""Open blockers in STATE.md, in the three shapes projects use.

1. Open checklist items (`- [ ] ...`) under a heading that mentions "bloker"/"blocker", or tagged `[bloker]`
   anywhere (same rule as the cockpit's collect.js).
2. Table rows under such a heading (the sota-starter template: | ID | Blocker | Impact | Owner | Status |); a row
   counts unless its blocker cell is empty or its status says it is closed.
3. Plain bullets under such a heading, except placeholders like "brak" or "none".
"""

from __future__ import annotations

import re
from typing import List, Optional

HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")
BLOCKER_WORD_RE = re.compile(r"bloker|blocker", re.I)
BLOCKER_TAG_RE = re.compile(r"\[(bloker|blocker)\]", re.I)
OPEN_ITEM_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$")
DONE_ITEM_RE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")
PLACEHOLDER_RE = re.compile(r"^\(?(brak|none|n/?a|-|—|–)\)?\.?$", re.I)
CLOSED_STATUS_RE = re.compile(r"done|resolved|closed|fixed|zamkni|rozwiązan|naprawion|zrobion|\bok\b", re.I)
HEADER_CELLS = frozenset(("blocker", "bloker", "blokery", "blockers"))
STATUS_COLUMN_MIN_CELLS = 5


def _table_blocker(line: str) -> Optional[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if all(not cell or SEPARATOR_CELL_RE.match(cell) for cell in cells):
        return None
    if any(cell.lower() in HEADER_CELLS for cell in cells):
        return None
    text = cells[1] if len(cells) >= 2 else cells[0]
    if not text or PLACEHOLDER_RE.match(text):
        return None
    if len(cells) >= STATUS_COLUMN_MIN_CELLS and CLOSED_STATUS_RE.search(cells[-1]):
        return None
    return f"{cells[0]}: {text}" if len(cells) >= 2 and cells[0] else text


def _section_blocker(line: str) -> Optional[str]:
    """A blocker from a line inside a blocker section that is not a checklist item."""
    if line.lstrip().startswith("|"):
        return _table_blocker(line)
    bullet = BULLET_RE.match(line)
    if bullet and not PLACEHOLDER_RE.match(bullet.group(1)) and "~~" not in bullet.group(1):
        return bullet.group(1)
    return None


def open_blockers(state_md: str) -> List[str]:
    """Texts of the open blockers, in file order."""
    found: List[str] = []
    in_section = False
    for line in state_md.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            in_section = bool(BLOCKER_WORD_RE.search(heading.group(1)))
            continue
        if DONE_ITEM_RE.match(line):
            continue
        item = OPEN_ITEM_RE.match(line)
        if item:
            if in_section or BLOCKER_TAG_RE.search(item.group(1)):
                found.append(item.group(1))
            continue
        if in_section:
            blocker = _section_blocker(line)
            if blocker:
                found.append(blocker)
    return found
