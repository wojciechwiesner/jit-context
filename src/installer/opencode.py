"""OpenCode host: use the npm package when published, otherwise a locally built bundle."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from installer.common import DRY, FAIL, INTEGRATIONS_DIR, OK, SKIP, Result, backup, home, read_json, write_json_atomic

HOST = "opencode"
NPM_NAME = "opencode-plugin-jit-context"
PLUGIN_SRC = INTEGRATIONS_DIR / "opencode"
LOCAL_FILE = "jit-context.js"
SDK_PACKAGE = "@opencode-ai/plugin"
SDK_VERSION = ">=1.14.0"
CMD_TIMEOUT_S = 300


def config_dir() -> Path:
    return home() / ".config" / "opencode"


def detect() -> bool:
    return config_dir().is_dir() or shutil.which("opencode") is not None


def npm_published() -> bool:
    if not shutil.which("npm"):
        return False
    try:
        proc = subprocess.run(["npm", "view", NPM_NAME, "version"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _plugin_list(cfg: dict) -> list:
    plugins = cfg.get("plugin")
    return plugins if isinstance(plugins, list) else []


def _entry_name(entry) -> str:
    """Package name without a version pin: 'pkg@1.2' -> 'pkg', '@org/pkg@1' -> '@org/pkg'."""
    spec = str(entry[0] if isinstance(entry, list) and entry else entry)
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec


def _install_npm() -> str:
    path = config_dir() / "opencode.json"
    cfg = read_json(path)
    plugins = _plugin_list(cfg)
    (config_dir() / "plugins" / LOCAL_FILE).unlink(missing_ok=True)  # avoid loading twice
    if any(_entry_name(p) == NPM_NAME for p in plugins):
        return f"{NPM_NAME} already in opencode.json"
    backup(path)
    cfg["plugin"] = [*plugins, NPM_NAME]
    write_json_atomic(path, cfg)
    return f"added {NPM_NAME} to opencode.json"


def _build_bundle() -> Path:
    for args in (["bun", "install", "--frozen-lockfile"], ["bun", "run", "build"]):
        subprocess.run(args, cwd=PLUGIN_SRC, check=True, capture_output=True, timeout=CMD_TIMEOUT_S)
    return PLUGIN_SRC / "dist" / "index.js"


def _ensure_sdk_dependency() -> None:
    """The bundle imports the plugin SDK; OpenCode installs deps listed in its package.json."""
    pkg_path = config_dir() / "package.json"
    pkg = read_json(pkg_path)
    deps = pkg.setdefault("dependencies", {})
    if SDK_PACKAGE in deps:
        return
    backup(pkg_path)
    deps[SDK_PACKAGE] = SDK_VERSION
    write_json_atomic(pkg_path, pkg)


def _install_local() -> str:
    bundle = _build_bundle()
    target = config_dir() / "plugins" / LOCAL_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, target)
    _ensure_sdk_dependency()
    return f"npm package not published yet, local bundle -> {target}"


def install(dry_run: bool = False) -> Result:
    if not detect():
        return Result(HOST, SKIP, "OpenCode not found")
    published = npm_published()
    if not published and not shutil.which("bun"):
        return Result(HOST, SKIP, f"{NPM_NAME} not on npm yet and bun missing for a local build")
    if dry_run:
        mode = "npm package" if published else "local bundle"
        return Result(HOST, DRY, f"would install {mode}")
    try:
        detail = _install_npm() if published else _install_local()
    except (OSError, subprocess.SubprocessError) as exc:
        return Result(HOST, FAIL, f"{type(exc).__name__}: {exc}")
    return Result(HOST, OK, f"{detail} (restart OpenCode)")


def uninstall(dry_run: bool = False) -> Result:
    path = config_dir() / "opencode.json"
    local = config_dir() / "plugins" / LOCAL_FILE
    cfg = read_json(path)
    plugins = _plugin_list(cfg)
    kept = [p for p in plugins if _entry_name(p) != NPM_NAME]
    if len(kept) == len(plugins) and not local.exists():
        return Result(HOST, SKIP, "plugin not installed")
    if dry_run:
        return Result(HOST, DRY, "would remove plugin entry and local bundle")
    local.unlink(missing_ok=True)
    if len(kept) != len(plugins):
        backup(path)
        cfg["plugin"] = kept
        write_json_atomic(path, cfg)
    return Result(HOST, OK, "plugin removed")
