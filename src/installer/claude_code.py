"""Claude Code host: copy JIT hooks into ~/.claude/hooks and register them in settings.json."""

from __future__ import annotations

import filecmp
import os
import shutil
import sys
from pathlib import Path

from installer.common import (
    DRY,
    FAIL,
    INTEGRATIONS_DIR,
    OK,
    SKIP,
    Result,
    backup,
    create_snapshot,
    home,
    prune_snapshots,
    read_json,
    relink,
    remove_tree,
    write_json_atomic,
)

HOST = "claude-code"
HOOKS_SRC = INTEGRATIONS_DIR / "claude-code" / "hooks"
HOOK_FILES = (
    "jit-context-hook.py",
    "jit-compact-hook.py",
    "jit-spillover-hook.py",
    "jit_compact_extract.py",
    "jit_spill_select.py",
    "jit_src_path.py",
)
# Must match RUNTIME_DIR_NAME / CURRENT_LINK_NAME in hooks/jit_src_path.py.
RUNTIME_DIR_NAME = "jit-context-runtime"
CURRENT_LINK_NAME = "current"
SNAPSHOT_PREFIX = "src"
LIVE_MODE_ENV = "JIT_DEV_LIVE"
SPILL_MATCHER = "mcp__.*|WebFetch|WebSearch|Grep|Glob|Agent|Task|ListMcpResourcesTool|ReadMcpResourceTool|ReadMcpResourceDirTool"

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


def runtime_dir() -> Path:
    return claude_dir() / RUNTIME_DIR_NAME


def detect() -> bool:
    return claude_dir().is_dir()


def live_mode() -> bool:
    return os.environ.get(LIVE_MODE_ENV) == "1"


def deploy_runtime() -> str:
    """Point hooks at a fresh read-only src snapshot, or at the live checkout in live mode."""
    link = runtime_dir() / CURRENT_LINK_NAME
    if live_mode():
        if link.is_symlink():
            link.unlink()
        return f"{LIVE_MODE_ENV}=1: hooks import the live ~/.jit-context/src"
    target = create_snapshot(runtime_dir(), SNAPSHOT_PREFIX)
    relink(link, target)
    pruned = prune_snapshots(runtime_dir(), SNAPSHOT_PREFIX, keep=target)
    return f"runtime -> {target.name} ({pruned} old pruned)"


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
        mode = "live src" if live_mode() else "a new runtime snapshot"
        return Result(HOST, DRY, f"would copy {len(HOOK_FILES)} hooks, add {added} settings entries, use {mode}")
    copied = _copy_hooks(hooks_dir)
    runtime = deploy_runtime()
    if added:
        backup(settings_path)
        write_json_atomic(settings_path, settings)
    return Result(HOST, OK, f"{copied} hooks updated, {added} settings entries added, {runtime} (restart Claude Code)")


def uninstall(dry_run: bool = False) -> Result:
    if not detect():
        return Result(HOST, SKIP, "~/.claude not found")
    settings_path = claude_dir() / "settings.json"
    settings = read_json(settings_path)
    removed = remove_settings(settings)
    if dry_run:
        return Result(HOST, DRY, f"would remove {removed} settings entries, hook files and {runtime_dir()}")
    if removed:
        backup(settings_path)
        write_json_atomic(settings_path, settings)
    for name in HOOK_FILES:
        (claude_dir() / "hooks" / name).unlink(missing_ok=True)
    remove_tree(runtime_dir())
    return Result(HOST, OK, f"{removed} settings entries removed")
