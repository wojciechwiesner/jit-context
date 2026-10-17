"""Read status from this configured state directory, never global legacy temp files."""

import json
from pathlib import Path
from typing import Any, Dict

STATUS_FIELDS = (
    "session_id", "scope", "confidence", "complexity", "mode", "budget_chars",
    "capsule_chars", "capsule_tokens_est", "updated_at", "ts", "savings_status",
)


def latest_session_payload(sessions_dir: Path) -> Dict[str, Any]:
    try:
        paths = sorted(sessions_dir.glob("*/*/session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return {}
    for path in paths[:20]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("session_id"):
                return {key: data[key] for key in STATUS_FIELDS if key in data}
        except (OSError, ValueError):
            continue
    return {}
