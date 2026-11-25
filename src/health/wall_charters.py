"""Operator Wall: project charters (read + approve). One JSON file per project slug."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from health import wall_readers

SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
OWNER_AUDIENCE = "me"


class CharterError(ValueError):
    """Invalid approve request; `code` is the HTTP status to answer with."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def load_all() -> dict[str, dict[str, Any]]:
    """slug -> charter dict. Unreadable files are skipped; a missing directory is an error (source down)."""
    root = wall_readers.charters_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"brak katalogu {root}")
    charters: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and SLUG_RE.match(path.stem):
            charters[path.stem] = data
    return charters


def summary(charter: dict[str, Any] | None) -> dict[str, Any] | None:
    if charter is None:
        return None
    return {"status": charter.get("status"), "type": charter.get("type"), "goal": charter.get("goal"),
            "audience": charter.get("audience") or [], "cadence": charter.get("cadence")}


def counts(charters: dict[str, dict[str, Any]]) -> dict[str, int]:
    values = [c.get("status") for c in charters.values()]
    return {"draft": values.count("draft"), "approved": values.count("approved")}


def drafts(charters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"slug": slug, **c} for slug, c in charters.items() if c.get("status") == "draft"]


def _allowed_audience(charter: dict[str, Any]) -> set[str]:
    candidates = charter.get("audience_candidates") or []
    return {OWNER_AUDIENCE, *(str(c.get("who")) for c in candidates if isinstance(c, dict) and c.get("who"))}


def _validate(slugs: Any, audience: Any, charters: dict[str, dict[str, Any]]) -> list[str]:
    if not isinstance(slugs, list) or not slugs or not all(isinstance(s, str) for s in slugs):
        raise CharterError("slugs: oczekiwana niepusta lista")
    if not isinstance(audience, dict):
        raise CharterError("audience: oczekiwany obiekt slug -> lista")
    unknown = [s for s in slugs if not SLUG_RE.match(s) or s not in charters]
    if unknown:
        raise CharterError(f"nieznane chartery: {', '.join(unknown)[:200]}", 404)
    for slug, chosen in audience.items():
        if slug not in slugs:
            raise CharterError(f"audience dla {slug!r} spoza listy slugs")
        if not isinstance(chosen, list) or not set(chosen) <= _allowed_audience(charters[slug]):
            raise CharterError(f"audience dla {slug!r}: dozwolone tylko kandydaci chartera i 'me'")
    return list(dict.fromkeys(slugs))


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def approve(slugs: Any, audience: Any, now: float | None = None) -> dict[str, Any]:
    """Mark drafts approved with the chosen audience. Validates the whole batch before writing anything."""
    charters = load_all()
    wanted = _validate(slugs, audience, charters)
    stamp = datetime.fromtimestamp(now or time.time(), timezone.utc).isoformat(timespec="seconds")
    approved, skipped = [], []
    for slug in wanted:
        charter = dict(charters[slug])
        if charter.get("status") != "draft":
            skipped.append({"slug": slug, "reason": f"status {charter.get('status')!r}, nie draft"})
            continue
        charter.update(status="approved", approved_at=stamp)
        if slug in audience:
            charter["audience"] = list(dict.fromkeys(audience[slug]))
        _write_atomic(wall_readers.charters_dir() / f"{slug}.json", charter)
        approved.append(slug)
    return {"approved": approved, "skipped": skipped}
