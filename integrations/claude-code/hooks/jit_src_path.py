"""Resolve which JIT `src/` the Claude Code hooks import.

Order:
1. $JIT_SRC                      explicit override
2. $JIT_DEV_LIVE=1               live dev checkout (~/.jit-context/src)
3. ../jit-context-runtime/current  immutable snapshot deployed by `jit install`
4. ~/.jit-context/src            fallback for installs that predate snapshots
"""
from __future__ import annotations

import os

LIVE_SRC = "~/.jit-context/src"
RUNTIME_DIR_NAME = "jit-context-runtime"
CURRENT_LINK_NAME = "current"
HOOK_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_jit_src() -> str:
    explicit = os.environ.get("JIT_SRC")
    if explicit:
        return os.path.expanduser(explicit)
    if os.environ.get("JIT_DEV_LIVE") == "1":
        return os.path.expanduser(LIVE_SRC)
    current = os.path.join(os.path.dirname(HOOK_DIR), RUNTIME_DIR_NAME, CURRENT_LINK_NAME)
    if os.path.isdir(current):
        # Pin the real path so one hook run never mixes two snapshots mid-redeploy.
        return os.path.realpath(current)
    return os.path.expanduser(LIVE_SRC)
