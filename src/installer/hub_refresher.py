"""Project Hub refresher as a macOS launchd agent: write the plist and a runtime snapshot, never load it here.

`jit install` keeps the plist and snapshot current; loading is an explicit step (`jit hub install-service --load`).
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from installer.common import (
    DRY,
    FAIL,
    OK,
    SKIP,
    Result,
    backup,
    create_snapshot,
    home,
    prune_snapshots,
    relink,
)

HOST = "hub-refresher"
LABEL = "io.theones.jit-hub-refresher"
PLIST_NAME = f"{LABEL}.plist"
LOG_NAME = "jit-hub-refresher.log"
REFRESH_INTERVAL_S = 60
THROTTLE_INTERVAL_S = 30
MIN_PYTHON_MINOR = 11
HOMEBREW_BIN_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
PYTHON_NAME_RE = re.compile(r"^python3\.(\d+)$")
SNAPSHOT_PREFIX = "src"
CURRENT_LINK_NAME = "current"
ENTRY_MODULE = "init"
LAUNCHCTL_TIMEOUT_S = 15


def launch_agents_dir() -> Path:
    return home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return launch_agents_dir() / PLIST_NAME


def log_path() -> Path:
    return home() / "Library" / "Logs" / LOG_NAME


def runtime_dir() -> Path:
    return home() / ".hermes" / "state" / "jit-hub" / "runtime"


def runtime_link() -> Path:
    return runtime_dir() / CURRENT_LINK_NAME


def detect() -> bool:
    return sys.platform == "darwin" and (home() / "Library").is_dir()


def find_python() -> Optional[Path]:
    """Oldest Homebrew python3.N with N >= 11 (the version the gate tests), by its stable bin path."""
    found: List[Tuple[int, int, Path]] = []
    for order, bin_dir in enumerate(HOMEBREW_BIN_DIRS):
        if not bin_dir.is_dir():
            continue
        for candidate in bin_dir.iterdir():
            match = PYTHON_NAME_RE.match(candidate.name)
            if match and int(match.group(1)) >= MIN_PYTHON_MINOR and os.access(candidate, os.X_OK):
                found.append((int(match.group(1)), order, candidate))
    return min(found)[2] if found else None


def build_plist(python: Path, working_dir: Path) -> dict:
    """launchd job: `python -m init hub refresh --interval 60` from the runtime snapshot."""
    path_dirs = [str(d) for d in HOMEBREW_BIN_DIRS] + list(SYSTEM_PATH)
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", ENTRY_MODULE, "hub", "refresh", "--interval", str(REFRESH_INTERVAL_S)],
        "WorkingDirectory": str(working_dir),
        "EnvironmentVariables": {"PATH": ":".join(path_dirs), "PYTHONDONTWRITEBYTECODE": "1"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": THROTTLE_INTERVAL_S,
        "ProcessType": "Background",
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }


def write_plist(data: dict) -> bool:
    """Write the plist atomically; returns False when the file already had this content."""
    target = plist_path()
    payload = plistlib.dumps(data, sort_keys=False)
    if target.is_file() and target.read_bytes() == payload:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    backup(target)
    tmp = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    os.replace(tmp, target)
    return True


def domain() -> str:
    return f"gui/{os.getuid()}"


def load_command() -> List[str]:
    return ["launchctl", "bootstrap", domain(), str(plist_path())]


def unload_command() -> List[str]:
    return ["launchctl", "bootout", f"{domain()}/{LABEL}"]


def _launchctl(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=LAUNCHCTL_TIMEOUT_S)


def is_loaded() -> bool:
    return _launchctl(["launchctl", "print", f"{domain()}/{LABEL}"]).returncode == 0


def load() -> Tuple[bool, str]:
    """Bootstrap the agent; a loaded copy is booted out first so the new plist takes effect."""
    if is_loaded():
        out = _launchctl(unload_command())
        if out.returncode != 0:
            return False, f"bootout exit {out.returncode}: {(out.stderr or out.stdout).strip()}"
    out = _launchctl(load_command())
    if out.returncode != 0:
        return False, f"bootstrap exit {out.returncode}: {(out.stderr or out.stdout).strip()}"
    return True, f"loaded {LABEL} in {domain()}"


def install(dry_run: bool = False) -> Result:
    if not detect():
        return Result(HOST, SKIP, "not macOS or ~/Library missing")
    python = find_python()
    if python is None:
        dirs = ", ".join(str(d) for d in HOMEBREW_BIN_DIRS)
        return Result(HOST, FAIL, f"no Homebrew python3.{MIN_PYTHON_MINOR}+ in {dirs}")
    if dry_run:
        return Result(HOST, DRY, f"would snapshot src to {runtime_dir()} and write {plist_path()} ({python})")
    target = create_snapshot(runtime_dir(), SNAPSHOT_PREFIX)
    relink(runtime_link(), target)
    prune_snapshots(runtime_dir(), SNAPSHOT_PREFIX, keep=target)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    changed = write_plist(build_plist(python, runtime_link()))
    state = "written" if changed else "unchanged"
    return Result(HOST, OK, f"plist {state}, runtime -> {target.name}, not loaded (load: {' '.join(load_command())})")


def uninstall(dry_run: bool = False) -> Result:
    if not detect() or not plist_path().exists():
        return Result(HOST, SKIP, "no refresher plist")
    if is_loaded():
        return Result(HOST, FAIL, f"agent is loaded; unload first: {' '.join(unload_command())}")
    if dry_run:
        return Result(HOST, DRY, f"would remove {plist_path()}")
    backup(plist_path())
    plist_path().unlink()
    return Result(HOST, OK, "plist removed (backup kept, runtime snapshots kept)")
