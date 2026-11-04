"""Claude Code transcripts: <projects dir>/<encoded-cwd>/*.jsonl (+ <session>/subagents/*.jsonl).

Each file is read from the last remembered byte offset; only complete lines are consumed. One API response is
written as several lines that repeat the same usage (one per content block), so assistant usage is counted once
per (message.id, requestId). A file that shrank or was replaced is dropped and re-read from the start.
A turn is a user line typed by a person: not meta, not a sidechain, not only tool results.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from hub import usage_store as store

SOURCE = "claude"
TRANSCRIPT_GLOBS = ("*/*.jsonl", "*/*/subagents/*.jsonl")
ENCODE_PATTERN = re.compile(r"[^a-zA-Z0-9]")
LINE_MARKERS = (b'"usage"', b'"type":"user"')
USAGE_MAP = (
    ("input_tokens", "input_tokens"),
    ("output_tokens", "output_tokens"),
    ("cache_read_input_tokens", "cache_read_tokens"),
    ("cache_creation_input_tokens", "cache_write_tokens"),
)


def encode_path(path: str) -> str:
    """Directory name Claude Code uses for a cwd (every non-alphanumeric character becomes '-')."""
    return ENCODE_PATTERN.sub("-", path)


def decode_dir(name: str, known_paths: Iterable[str]) -> Optional[str]:
    """The known path whose encoding equals `name`; None when no known path matches (no guessing)."""
    for path in known_paths:
        if encode_path(path) == name:
            return path
    return None


def local_day(timestamp: object) -> Optional[str]:
    """Local calendar day of an ISO-8601 timestamp (Claude Code writes UTC with a Z suffix)."""
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone().date().isoformat()


def _is_human_turn(entry: dict) -> bool:
    if entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(block, dict) and block.get("type") != "tool_result" for block in content)
    return False


def _usage_delta(entry: dict) -> Optional[Tuple[str, Dict[str, int]]]:
    """(message key, counters) for an assistant line with usage, else None."""
    message = entry.get("message") or {}
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    key = f"{message.get('id') or entry.get('uuid')}:{entry.get('requestId') or ''}"
    delta = {target: int(usage.get(name) or 0) for name, target in USAGE_MAP}
    delta["api_calls"] = 1
    return key, delta


def _apply_line(conn: sqlite3.Connection, unit: str, entry: dict, fallback: Dict[str, Optional[str]]) -> int:
    """Store one parsed line; returns 1 when it added counters."""
    day = local_day(entry.get("timestamp"))
    if day is None:
        return 0
    identity = {"session_id": entry.get("sessionId") or fallback["session_id"],
                "path": entry.get("cwd") or fallback["path"], "scope": None}
    if entry.get("type") == "assistant":
        parsed = _usage_delta(entry)
        if parsed is None or not store.mark_seen(conn, parsed[0], unit):
            return 0
        store.add_to_day(conn, SOURCE, unit, day, identity, parsed[1])
        return 1
    if entry.get("type") == "user" and _is_human_turn(entry):
        store.add_to_day(conn, SOURCE, unit, day, identity, {"turns": 1})
        return 1
    return 0


def _read_new_lines(path: Path, offset: int) -> Tuple[List[bytes], int]:
    """Complete lines after `offset` and the offset just past the last complete line."""
    with open(path, "rb") as handle:
        handle.seek(offset)
        data = handle.read()
    end = data.rfind(b"\n")
    if end < 0:
        return [], offset
    return data[: end + 1].splitlines(), offset + end + 1


def _ingest_file(conn: sqlite3.Connection, root: Path, path: Path, known_paths: List[str]) -> int:
    unit = str(path.relative_to(root))
    stat = path.stat()
    state = store.get_reader_state(conn, SOURCE, unit)
    if store.unchanged(state, stat.st_size, stat.st_mtime, stat.st_ino):
        return 0
    offset = state["position"] if state is not None else 0
    if state is not None and (state["inode"] != stat.st_ino or stat.st_size < offset):
        store.drop_unit(conn, SOURCE, unit)
        offset = 0
    lines, new_offset = _read_new_lines(path, offset)
    project_dir = Path(unit).parts[0]
    session_dir = path.parent.parent.name if path.parent.name == "subagents" else path.stem
    fallback = {"session_id": session_dir, "path": decode_dir(project_dir, known_paths) or project_dir}
    added = 0
    for raw in lines:
        if not any(marker in raw for marker in LINE_MARKERS):
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict):
            added += _apply_line(conn, unit, entry, fallback)
    store.set_reader_state(conn, SOURCE, unit, new_offset, stat.st_size, stat.st_mtime, stat.st_ino)
    return added


def collect(conn: sqlite3.Connection, root: Path, known_paths: List[str]) -> Tuple[int, List[str]]:
    """Ingest new transcript lines under `root`. Returns (counted lines, per-file errors)."""
    if not root.is_dir():
        return 0, []
    added, errors = 0, []
    files = sorted({p for pattern in TRANSCRIPT_GLOBS for p in root.glob(pattern) if p.is_file()})
    for path in files:
        try:
            with conn:
                added += _ingest_file(conn, root, path, known_paths)
        except (OSError, sqlite3.Error, UnicodeError) as exc:
            errors.append(f"{path}: {exc}")
    return added, errors
