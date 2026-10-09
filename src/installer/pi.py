"""Pi coding agent host: jit-context extension (capsule injection + tools) and Hermes skills."""

from __future__ import annotations

import shutil
from pathlib import Path

from installer.common import DRY, INTEGRATIONS_DIR, OK, SKIP, Result, backup, home, read_json, write_json_atomic

HOST = "pi"
EXTENSION_SRC = INTEGRATIONS_DIR / "pi" / "jit-context.ts"
EXTENSION_NAME = "jit-context.ts"


def agent_dir() -> Path:
    return home() / ".pi" / "agent"


def hermes_skills_dir() -> Path:
    return home() / ".hermes" / "skills"


def detect() -> bool:
    return agent_dir().is_dir() or shutil.which("pi") is not None


def _add_skills_path(settings: dict) -> bool:
    skills = settings.get("skills")
    skills = skills if isinstance(skills, list) else []
    path = str(hermes_skills_dir())
    if path in skills or not hermes_skills_dir().is_dir():
        return False
    settings["skills"] = [*skills, path]
    return True


def install(dry_run: bool = False) -> Result:
    if not detect():
        return Result(HOST, SKIP, "Pi not found")
    if dry_run:
        return Result(HOST, DRY, f"would copy extension to {agent_dir() / 'extensions' / EXTENSION_NAME} and add Hermes skills")
    target = agent_dir() / "extensions" / EXTENSION_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXTENSION_SRC, target)
    settings_path = agent_dir() / "settings.json"
    settings = read_json(settings_path)
    skills_added = _add_skills_path(settings)
    if skills_added:
        backup(settings_path)
        write_json_atomic(settings_path, settings)
    return Result(HOST, OK, f"extension -> {target}; Hermes skills {'added' if skills_added else 'already set'} (restart Pi)")


def uninstall(dry_run: bool = False) -> Result:
    target = agent_dir() / "extensions" / EXTENSION_NAME
    settings_path = agent_dir() / "settings.json"
    settings = read_json(settings_path)
    skills = settings.get("skills") if isinstance(settings.get("skills"), list) else []
    path = str(hermes_skills_dir())
    if not target.exists() and path not in skills:
        return Result(HOST, SKIP, "extension not installed")
    if dry_run:
        return Result(HOST, DRY, "would remove extension and Hermes skills path")
    target.unlink(missing_ok=True)
    if path in skills:
        backup(settings_path)
        settings["skills"] = [s for s in skills if s != path]
        write_json_atomic(settings_path, settings)
    return Result(HOST, OK, "extension and Hermes skills path removed")
