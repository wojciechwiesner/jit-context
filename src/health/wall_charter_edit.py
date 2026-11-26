"""Operator Wall: owner edits of a charter (answers to questions, type/goal/success/cadence, audience)."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from health import wall_charters, wall_readers
from health.wall_charters import CharterError

MAX_TEXT = 600
TYPES = ("client-delivery", "product", "platform", "experiment", "dormant")
CADENCES = ("daily", "weekly", "monthly", "none")
PERSON_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
TRACKED_FIELDS = ("type", "goal", "success")  # the first edit of any of these keeps `draft_original`


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise CharterError(f"{label}: oczekiwany tekst")
    if len(value) > MAX_TEXT:
        raise CharterError(f"{label}: maksymalnie {MAX_TEXT} znaków")
    return value.strip()


def _clean_fields(fields: Any) -> dict[str, str]:
    if not isinstance(fields, dict):
        raise CharterError("fields: oczekiwany obiekt")
    unknown = set(fields) - {"type", "goal", "success", "cadence"}
    if unknown:
        raise CharterError(f"fields: nieznane pola {', '.join(sorted(map(str, unknown)))[:100]}")
    clean = {key: _text(value, key) for key, value in fields.items()}
    if "type" in clean and clean["type"] not in TYPES:
        raise CharterError(f"type: dozwolone {', '.join(TYPES)}")
    if "cadence" in clean and clean["cadence"] not in CADENCES:
        raise CharterError(f"cadence: dozwolone {', '.join(CADENCES)}")
    return clean


def _clean_audience(audience: Any) -> list[str]:
    if not isinstance(audience, list):
        raise CharterError("audience: oczekiwana lista")
    for name in audience:
        if not isinstance(name, str) or not (name == wall_charters.OWNER_AUDIENCE or PERSON_RE.match(name)):
            raise CharterError(f"audience: zła nazwa {str(name)[:40]!r} (małe litery, cyfry, _ i -, 2-32 znaki)")
    return list(dict.fromkeys([wall_charters.OWNER_AUDIENCE, *audience]))


def _clean_answers(answers: Any, charter: dict[str, Any]) -> dict[str, str]:
    if not isinstance(answers, list):
        raise CharterError("answers: oczekiwana lista")
    known = {q for q in charter.get("questions") or [] if isinstance(q, str)}
    clean: dict[str, str] = {}
    for item in answers:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise CharterError("answers: oczekiwane obiekty {question, answer}")
        if item["question"] not in known:
            raise CharterError(f"answers: nieznane pytanie {item['question'][:60]!r}")
        clean[item["question"]] = _text(item.get("answer", ""), "answer")
    return clean


def _merge_answers(charter: dict[str, Any], new: dict[str, str], stamp: str) -> None:
    kept = {a["question"]: a for a in charter.get("answers") or [] if isinstance(a, dict) and "question" in a}
    for question, answer in new.items():
        old = kept.get(question)
        if not answer:
            kept.pop(question, None)
        elif old is None or old.get("answer") != answer:
            kept[question] = {"question": question, "answer": answer, "answered_at": stamp}
    charter["answers"] = list(kept.values())


def update(request: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """Validate the whole request, then write one charter atomically. Status is never changed here."""
    slug = request.get("slug")
    charters = wall_charters.load_all()
    if not isinstance(slug, str) or not wall_charters.SLUG_RE.match(slug) or slug not in charters:
        raise CharterError("nieznany charter", 404)
    charter = dict(charters[slug])
    fields = _clean_fields(request.get("fields") or {})
    audience = _clean_audience(request["audience"]) if "audience" in request else None
    answers = _clean_answers(request.get("answers") or [], charter)

    stamp = datetime.fromtimestamp(now or time.time(), timezone.utc).isoformat(timespec="seconds")
    if any(key in fields and fields[key] != charter.get(key) for key in TRACKED_FIELDS):
        charter.setdefault("draft_original", {key: charter.get(key) for key in TRACKED_FIELDS})
    charter.update(fields)
    if audience is not None:
        charter["audience"] = audience
    _merge_answers(charter, answers, stamp)
    charter["edited_at"] = stamp
    wall_charters._write_atomic(wall_readers.charters_dir() / f"{slug}.json", charter)
    return {"saved": slug, "edited_at": stamp, "status": charter.get("status")}
