"""Per project chat history of the hub: <hub dir>/chats/<slug>.jsonl, one JSON record per line, append only.

Records: {"ts", "role": "user" | "assistant" | "error", "content", ...extra}. Unreadable lines are skipped and
counted, never repaired or invented.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Dict, List

import config

CHATS_DIR_NAME = "chats"
DEFAULT_HISTORY_LIMIT = 200
SAFE_NAME_RE = re.compile(r"[^a-z0-9_-]+")

_WRITE_LOCK = threading.Lock()


def chats_dir() -> Path:
    return config.hub_dir() / CHATS_DIR_NAME


def history_path(slug: str) -> Path:
    """Registry slugs are already safe; the filter keeps a hand-edited registry from escaping the dir."""
    return chats_dir() / f"{SAFE_NAME_RE.sub('-', slug.lower()).strip('-') or 'project'}.jsonl"


def append(slug: str, records: List[dict]) -> None:
    path = history_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(dict({"ts": time.time()}, **record), ensure_ascii=False, default=str) + "\n"
                    for record in records)
    with _WRITE_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(lines)


def load(slug: str, limit: int = DEFAULT_HISTORY_LIMIT) -> Dict[str, object]:
    """The last `limit` records plus the number of unreadable lines."""
    path = history_path(slug)
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return {"slug": slug, "path": str(path), "messages": [], "skipped_lines": 0}
    messages, skipped = [], 0
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(record, dict):
            messages.append(record)
        else:
            skipped += 1
    return {"slug": slug, "path": str(path), "messages": messages[-limit:], "skipped_lines": skipped}
