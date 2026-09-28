"""Agent Zero host: copy the plugin into usr/plugins/jit_context (local checkout or Docker)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from installer.common import DRY, FAIL, INTEGRATIONS_DIR, OK, SKIP, Result, home, timestamp

HOST = "agent-zero"
PLUGIN_NAME = "jit_context"  # must match `name` in plugin.yaml
PLUGIN_SRC = INTEGRATIONS_DIR / "agent-zero"
COPY_IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "data")
CONTAINER_ROOT = "/a0"
IMAGE_MARKERS = ("agent-zero", "agent0ai")
DOCKER_TIMEOUT_S = 60


def _is_a0_root(path: Path) -> bool:
    # Only plugin-capable releases ship the built-in plugin installer.
    return (path / "plugins" / "_plugin_installer").is_dir() and (path / "usr").is_dir()


def find_local_roots() -> list[Path]:
    if os.environ.get("A0_DIR"):
        root = Path(os.environ["A0_DIR"]).expanduser()
        return [root] if _is_a0_root(root) else []
    candidates = [home() / "agent-zero", *home().glob("Projects/*/agent-zero"), *home().glob("Projects/*/*/agent-zero")]
    return [c.resolve() for c in candidates if _is_a0_root(c)]


def find_containers() -> list[str]:
    if not shutil.which("docker"):
        return []
    try:
        proc = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.Image}}"],
                              capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = [line.split(" ", 1) for line in proc.stdout.splitlines() if " " in line]
    return [name for name, image in rows if any(m in image for m in IMAGE_MARKERS)]


def install_local(root: Path) -> Path:
    """Replace the plugin code, keeping the plugin's data/ directory (API keys, caches)."""
    target = root / "usr" / "plugins" / PLUGIN_NAME
    staging = target.with_name(f".{PLUGIN_NAME}.tmp.{timestamp()}")
    shutil.copytree(PLUGIN_SRC, staging, ignore=COPY_IGNORE)
    if (target / "data").is_dir():
        shutil.move(str(target / "data"), str(staging / "data"))
    (staging / "data").mkdir(exist_ok=True)  # what hooks.install() does inside Agent Zero
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)
    return target


def install_container(name: str) -> None:
    dest = f"{CONTAINER_ROOT}/usr/plugins/{PLUGIN_NAME}"
    subprocess.run(["docker", "exec", name, "mkdir", "-p", f"{dest}/data"], check=True,
                   capture_output=True, timeout=DOCKER_TIMEOUT_S)
    subprocess.run(["docker", "cp", f"{PLUGIN_SRC}/.", f"{name}:{dest}"], check=True,
                   capture_output=True, timeout=DOCKER_TIMEOUT_S)


def install(dry_run: bool = False) -> Result:
    roots, containers = find_local_roots(), find_containers()
    if not roots and not containers:
        return Result(HOST, SKIP, "no Agent Zero checkout or container (set A0_DIR to point at one)")
    if not (PLUGIN_SRC / "plugin.yaml").exists():
        return Result(HOST, FAIL, f"plugin missing in {PLUGIN_SRC}")
    places = [str(r) for r in roots] + [f"docker:{c}" for c in containers]
    if dry_run:
        return Result(HOST, DRY, "would install into " + ", ".join(places))
    try:
        for root in roots:
            install_local(root)
        for name in containers:
            install_container(name)
    except (OSError, subprocess.SubprocessError) as exc:
        return Result(HOST, FAIL, f"{type(exc).__name__}: {exc}")
    return Result(HOST, OK, "installed into " + ", ".join(places) + " (restart Agent Zero)")


def uninstall(dry_run: bool = False) -> Result:
    targets = [r / "usr" / "plugins" / PLUGIN_NAME for r in find_local_roots()]
    targets = [t for t in targets if t.exists()]
    if not targets:
        return Result(HOST, SKIP, "plugin not installed locally (containers: remove via the Agent Zero UI)")
    if dry_run:
        return Result(HOST, DRY, "would remove " + ", ".join(map(str, targets)))
    for target in targets:
        shutil.rmtree(target)
    return Result(HOST, OK, "removed " + ", ".join(map(str, targets)))
