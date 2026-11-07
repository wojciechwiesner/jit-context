"""Which repos are "live": commits in the last N days, read from the Project Hub registry.

The rollout plan (slug / mounts / locale / prod URL per repo) is a JSON file the operator owns:
<hub_dir>/feedby/plan.json. `jit feedby inventory` lists live repos and marks the ones not yet planned.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import config
from hub import registry

LIVE_WINDOW_DAYS = 30
PLAN_FILE_NAME = "plan.json"


def plan_path() -> Path:
    return config.hub_dir() / "feedby" / PLAN_FILE_NAME


def load_plan() -> Dict[str, Dict[str, Any]]:
    path = plan_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("repos", {}) if isinstance(data, dict) else {}


def commits_since(repo: Path, days: int) -> int:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", f"--since={days}.days", "HEAD"],
        capture_output=True, text=True,
    )
    return int(proc.stdout.strip() or 0) if proc.returncode == 0 else 0


def live_repos(days: int = LIVE_WINDOW_DAYS) -> List[Dict[str, Any]]:
    rows = []
    for entry in registry.load_projects():
        repo = Path(entry.get("path", ""))
        if not repo.is_dir():
            continue
        count = commits_since(repo, days)
        if count > 0:
            rows.append({"slug": entry.get("slug", repo.name), "path": str(repo), "commits": count})
    return sorted(rows, key=lambda row: -row["commits"])
