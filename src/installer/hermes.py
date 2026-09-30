"""Hermes host: deploy an immutable src snapshot and point ~/.hermes/plugins/ona-context at it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from installer.common import DRY, FAIL, OK, SKIP, SRC_DIR, Result, create_snapshot, git_head, home, prune_snapshots, relink

HOST = "hermes"
PLUGIN_NAME = "ona-context"
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


def install(dry_run: bool = False, restart: bool = True) -> Result:
    if not detect():
        return Result(HOST, SKIP, "~/.hermes not found")
    if not (SRC_DIR / "plugin.yaml").exists():
        return Result(HOST, FAIL, f"plugin.yaml missing in {SRC_DIR}")
    link = hermes_dir() / "plugins" / PLUGIN_NAME
    if dry_run:
        return Result(HOST, DRY, f"would link {link} -> a new plugin-releases/{PLUGIN_NAME}-{git_head()}-* snapshot")
    (hermes_dir() / "state" / PLUGIN_NAME).mkdir(parents=True, exist_ok=True)
    releases = hermes_dir() / "plugin-releases"
    target = create_snapshot(releases, PLUGIN_NAME)
    relink(link, target)
    prune_snapshots(releases, PLUGIN_NAME, keep=target)
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
