"""Claude Code host: copy JIT hooks into ~/.claude/hooks and register them in settings.json."""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

from installer.common import DRY, FAIL, INTEGRATIONS_DIR, OK, SKIP, Result, backup, home, read_json, write_json_atomic

HOST = "claude-code"
HOOKS_SRC = INTEGRATIONS_DIR / "claude-code" / "hooks"
HOOK_FILES = (
    "jit-context-hook.py",
    "jit-compact-hook.py",
    "jit-spillover-hook.py",
    "jit_compact_extract.py",
    "jit_spill_select.py",
)
SPILL_MATCHER = "mcp__.*|WebFetch|WebSearch|Grep|Glob|Agent|Task"

# (event, matcher, script, timeout, status message)
REGISTRATIONS = (
    ("SessionStart", None, "jit-context-hook.py", 10, "JIT context (JEV)"),
    ("UserPromptSubmit", None, "jit-context-hook.py", 10, "JIT context (JEV)"),
    ("SessionStart", "compact", "jit-compact-hook.py", 10, None),
    ("PreCompact", None, "jit-compact-hook.py", 30, "JIT compact: extracting essentials"),
    ("PostCompact", None, "jit-compact-hook.py", 10, None),
    ("PostToolUse", SPILL_MATCHER, "jit-spillover-hook.py", 40, None),
)


def claude_dir() -> Path:
    return home() / ".claude"


def detect() -> bool:
    return claude_dir().is_dir()


def _is_registered(groups: list, matcher: str | None, script: str) -> bool:
    for group in groups:
        if group.get("matcher") != matcher:
            continue
        if any(script in h.get("command", "") for h in group.get("hooks", [])):
            return True
    return False


def merge_settings(settings: dict, hooks_dir: Path, python: str) -> int:
    """Add missing JIT hook entries in place. Existing entries (any python path) are kept."""
    added = 0
    all_hooks = settings.setdefault("hooks", {})
    for event, matcher, script, timeout, status in REGISTRATIONS:
        groups = all_hooks.setdefault(event, [])
        if _is_registered(groups, matcher, script):
            continue
        hook = {"type": "command", "command": f"{python} -W ignore {hooks_dir / script}", "timeout": timeout}
        if status:
            hook["statusMessage"] = status
        group = {"hooks": [hook]}
        if matcher is not None:
            group = {"matcher": matcher, **group}
        groups.append(group)
        added += 1
    return added


def remove_settings(settings: dict) -> int:
    removed = 0
    for event, groups in list(settings.get("hooks", {}).items()):
        for group in groups:
            before = len(group.get("hooks", []))
            group["hooks"] = [h for h in group.get("hooks", []) if not any(s in h.get("command", "") for s in HOOK_FILES)]
            removed += before - len(group["hooks"])
        settings["hooks"][event] = [g for g in groups if g.get("hooks")]
    return removed


def _copy_hooks(hooks_dir: Path) -> int:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    changed = 0
    for name in HOOK_FILES:
        src, dst = HOOKS_SRC / name, hooks_dir / name
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        backup(dst)
        shutil.copy2(src, dst)
        changed += 1
    return changed


def install(dry_run: bool = False) -> Result:
    if not detect():
        return Result(HOST, SKIP, "~/.claude not found")
    if not HOOKS_SRC.is_dir():
        return Result(HOST, FAIL, f"hooks missing in {HOOKS_SRC} (needs a source checkout)")
    hooks_dir = claude_dir() / "hooks"
    settings_path = claude_dir() / "settings.json"
    settings = read_json(settings_path)
    added = merge_settings(settings, hooks_dir, sys.executable)
    if dry_run:
        return Result(HOST, DRY, f"would copy {len(HOOK_FILES)} hooks, add {added} settings entries")
    copied = _copy_hooks(hooks_dir)
    if added:
        backup(settings_path)
        write_json_atomic(settings_path, settings)
    return Result(HOST, OK, f"{copied} hooks updated, {added} settings entries added (restart Claude Code)")


def uninstall(dry_run: bool = False) -> Result:
    if not detect():
        return Result(HOST, SKIP, "~/.claude not found")
    settings_path = claude_dir() / "settings.json"
    settings = read_json(settings_path)
    removed = remove_settings(settings)
    if dry_run:
        return Result(HOST, DRY, f"would remove {removed} settings entries and hook files")
    if removed:
        backup(settings_path)
        write_json_atomic(settings_path, settings)
    for name in HOOK_FILES:
        (claude_dir() / "hooks" / name).unlink(missing_ok=True)
    return Result(HOST, OK, f"{removed} settings entries removed")
