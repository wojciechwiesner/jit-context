"""Local store of provisioned Feedby widget keys: <hub_dir>/feedby/keys.json, chmod 600.

One entry per Feedby slug: {slug, project_id, key, key_hash, repo, created_at}. The key is public
(it ships in page HTML) but is kept out of chat output and git; this file is the operator's copy.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import config

STORE_DIR_NAME = "feedby"
STORE_FILE_NAME = "keys.json"
FILE_MODE = 0o600


def store_path() -> Path:
    return config.hub_dir() / STORE_DIR_NAME / STORE_FILE_NAME


def load() -> Dict[str, Dict[str, Any]]:
    path = store_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def get(slug: str) -> Optional[Dict[str, Any]]:
    return load().get(slug)


def save_entry(slug: str, entry: Dict[str, Any]) -> None:
    data = load()
    data[slug] = {**entry, "slug": slug, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, FILE_MODE)
    tmp.replace(path)
    os.chmod(path, FILE_MODE)
