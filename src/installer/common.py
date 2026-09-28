"""Shared helpers for host installers: paths, backups, atomic JSON writes, results."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
INTEGRATIONS_DIR = REPO_ROOT / "integrations"

OK = "OK"
SKIP = "SKIP"
FAIL = "FAIL"
DRY = "DRY-RUN"


@dataclass
class Result:
    host: str
    status: str
    detail: str


def home() -> Path:
    # Path.home() honours $HOME, which keeps tests and --home overrides simple.
    return Path(os.environ.get("JIT_INSTALL_HOME") or Path.home())


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> Path | None:
    """Copy a file or directory next to itself with a timestamp suffix."""
    if not path.exists() and not path.is_symlink():
        return None
    target = path.with_name(f"{path.name}.bak.{timestamp()}")
    if path.is_dir() and not path.is_symlink():
        shutil.copytree(path, target, symlinks=True)
    else:
        shutil.copy2(path, target, follow_symlinks=False)
    return target


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def git_head() -> str:
    head = REPO_ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            return (REPO_ROOT / ".git" / ref[5:]).read_text().strip()[:7]
        return ref[:7]
    except OSError:
        return "local"
