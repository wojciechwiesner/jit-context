#!/usr/bin/env python3
"""Claude Code PostToolUse hook: JIT spillover for large tool outputs.

Walks the tool response, and every string field longer than LEAF_MIN_CHARS is
passed through the JIT Context OS pipeline (~/.jit-context/src/l0/tool_buffer.py):
full raw text -> /tmp/jit_tools/, deterministic clean, and if still too big the most
relevant chunks for the user's last prompt are kept verbatim (JEV ranking with a
token-overlap fallback, see jit_spill_select.py); omitted chunks are listed by label.
The field is replaced by the processed text plus a pointer to the raw file, and the
whole response is returned as `updatedToolOutput` so its shape stays intact.

Read is not matched (editing needs exact text); Bash is not matched (bashOutputMaxChars
spills it natively with a pointer to the full file). Image blocks are skipped.
Toggles: JIT_SPILL_HOOK=0 disables; JIT_SPILL_DISTILL=1 enables the LLM stage (off by
default: it added ~16s per call and grew a JSON result 7.8k -> 10.2k chars in testing).
Fail-open: any error -> no output, exit 0, Claude sees the original result.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time

try:  # immutable runtime snapshot unless JIT_SRC / JIT_DEV_LIVE=1 say otherwise
    from jit_src_path import resolve_jit_src
    JIT_SRC = resolve_jit_src()
except ImportError:
    JIT_SRC = os.path.expanduser(os.environ.get("JIT_SRC", "~/.jit-context/src"))
LOG_PATH = os.path.expanduser("~/.claude/logs/jit-spillover-hook.log")
LEAF_MIN_CHARS = int(os.environ.get("JIT_SPILL_MIN_CHARS", "6000"))
TARGET_CHARS = int(os.environ.get("JIT_SPILL_TARGET_CHARS", "4000"))
IMAGE_TYPES = {"image", "document"}


def _log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def _head_tail(text: str, limit: int) -> str:
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} chars omitted ...]\n{text[-half:]}"


def _spill_leaf(text: str, ctx: dict, stats: dict) -> str:
    from l0 import tool_buffer
    import jit_spill_select

    tool_name, session_id = ctx["tool"], ctx["session"]
    if os.environ.get("JIT_SPILL_DISTILL", "0") in ("1", "on", "true"):
        body, path = tool_buffer.process_tool_output(
            tool_name, text, user_intent=ctx["query"],
            threshold_chars=TARGET_CHARS, session_id=session_id,
        )
        # LLM distill can echo and grow structured JSON; never return more than the budget.
        if len(body) > TARGET_CHARS:
            body = _head_tail(body, TARGET_CHARS)
        stats["method"] = "distill"
    else:
        path = tool_buffer.spill_to_tmp(tool_name, text, session_id=session_id)
        body = tool_buffer.deterministic_clean(text, tool_name=tool_name)
        if len(body) > TARGET_CHARS:
            body, info = jit_spill_select.select(body, ctx["query"], TARGET_CHARS)
            stats["method"] = f"{info['method']} kept={info['kept']}/{info['total']}"
    return f"{body}\n\n[JIT spillover: {len(text)} chars -> full raw output at {path}]"


def _rewrite(node, ctx: dict, stats: dict):
    """Return a copy of node with oversized string leaves spilled; shape preserved."""
    if isinstance(node, str):
        if len(node) < LEAF_MIN_CHARS:
            return node
        stats["spilled"] += 1
        stats["chars_in"] += len(node)
        new = _spill_leaf(node, ctx, stats)
        stats["chars_out"] += len(new)
        return new
    if isinstance(node, list):
        return [_rewrite(item, ctx, stats) for item in node]
    if isinstance(node, dict):
        if node.get("type") in IMAGE_TYPES:
            return node
        return {key: _rewrite(value, ctx, stats) for key, value in node.items()}
    return node


def main() -> int:
    if os.environ.get("JIT_SPILL_HOOK", "1") in ("0", "off", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("hook_event_name") != "PostToolUse":
        return 0

    tool = str(payload.get("tool_name") or "tool")
    response = payload.get("tool_response")
    sys.path.insert(0, JIT_SRC)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import jit_spill_select

    tool_intent = f"{tool} {json.dumps(payload.get('tool_input') or {}, ensure_ascii=False)[:300]}"
    ctx = {
        "tool": tool,
        "query": jit_spill_select.last_user_prompt(payload.get("transcript_path")) or tool_intent,
        "session": "cc-" + str(payload.get("session_id") or "default"),
    }
    stats = {"spilled": 0, "chars_in": 0, "chars_out": 0, "method": "clean"}

    t0 = time.time()
    noise = io.StringIO()
    try:
        # tool_buffer may print telemetry; stdout must stay pure JSON for Claude Code.
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            new_response = _rewrite(response, ctx, stats)
    except Exception as err:
        _log(f"tool={tool} error={type(err).__name__}: {err}")
        return 0

    if stats["spilled"] == 0:
        return 0
    _log(
        f"tool={tool} session={ctx['session']} leaves={stats['spilled']} method={stats['method']} "
        f"chars {stats['chars_in']}->{stats['chars_out']} ms={(time.time() - t0) * 1000:.0f}"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": new_response,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
