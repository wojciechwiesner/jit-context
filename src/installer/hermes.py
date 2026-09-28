"""Hermes host: deploy an immutable src snapshot and point ~/.hermes/plugins/ona-context at it."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from installer.common import DRY, FAIL, OK, SKIP, SRC_DIR, Result, git_head, home, timestamp

HOST = "hermes"
PLUGIN_NAME = "ona-context"
SNAPSHOT_IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "*.egg-info")
# Runtime guards against tool-output bloat; same values the original install.sh applied.
RUNTIME_GUARDS = (
    ("tool_output.max_bytes", "4000"),
    ("tool_output.max_lines", "80"),
    ("file_read_max_chars", "15000"),
    ("compression.protect_last_n", "6"),
    ("compression.proactive_prune_min_result_chars", "1500"),
)
HERMES_TIMEOUT_S = 60


def hermes_dir() -> Path:
    return home() / ".hermes"


def detect() -> bool:
    return hermes_dir().is_dir()


def _hermes(*args: str) -> bool:
    if not shutil.which("hermes"):
        return False
    try:
        proc = subprocess.run(["hermes", *args], capture_output=True, timeout=HERMES_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _snapshot() -> Path:
    releases = hermes_dir() / "plugin-releases"
    target = releases / f"{PLUGIN_NAME}-{git_head()}"
    if target.exists():
        return target
    tmp = releases / f".{target.name}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(SRC_DIR, tmp, ignore=SNAPSHOT_IGNORE)
    (tmp / "DEPLOYED_FROM.txt").write_text(f"{git_head()} {timestamp()}\n")
    os.replace(tmp, target)
    return target


def _relink(link: Path, target: Path) -> None:
    """Swap the plugin link atomically; a real directory is moved aside, never deleted."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() and not link.is_symlink():
        link.rename(link.with_name(f"{link.name}.bak.{timestamp()}"))
    tmp_link = link.with_name(f".{link.name}.tmp")
    tmp_link.unlink(missing_ok=True)
    tmp_link.symlink_to(target)
    os.replace(tmp_link, link)


def install(dry_run: bool = False, restart: bool = True) -> Result:
    if not detect():
        return Result(HOST, SKIP, "~/.hermes not found")
    if not (SRC_DIR / "plugin.yaml").exists():
        return Result(HOST, FAIL, f"plugin.yaml missing in {SRC_DIR}")
    link = hermes_dir() / "plugins" / PLUGIN_NAME
    if dry_run:
        return Result(HOST, DRY, f"would link {link} -> plugin-releases/{PLUGIN_NAME}-{git_head()}")
    (hermes_dir() / "state" / PLUGIN_NAME).mkdir(parents=True, exist_ok=True)
    target = _snapshot()
    _relink(link, target)
    if not shutil.which("hermes"):
        return Result(HOST, OK, f"plugin -> {target.name}; hermes CLI not on PATH, guards skipped, restart Hermes")
    guards = sum(_hermes("config", "set", key, value) for key, value in RUNTIME_GUARDS)
    restarted = restart and _hermes("gateway", "restart")
    note = "gateway restarted" if restarted else "restart the Hermes gateway to load it"
    return Result(HOST, OK, f"plugin -> {target.name}, {guards}/{len(RUNTIME_GUARDS)} guards set, {note}")


def uninstall(dry_run: bool = False) -> Result:
    link = hermes_dir() / "plugins" / PLUGIN_NAME
    if not link.is_symlink():
        return Result(HOST, SKIP, "no ona-context plugin link")
    if dry_run:
        return Result(HOST, DRY, f"would remove link {link} (snapshots kept)")
    link.unlink()
    return Result(HOST, OK, "plugin link removed (snapshots kept in plugin-releases)")
