#!/usr/bin/env python3
"""Claude Code hook: inject the JIT Context OS capsule (with JEV reranking) by default.

Wired as SessionStart (startup/resume/clear/compact) and UserPromptSubmit.
Reuses the Hermes JIT runtime in ~/.jit-context/src (same L0 WAL, scope
hysteresis, Obsidian SSOT and cascade as Hermes) and emits the capsule as
hookSpecificOutput.additionalContext.

JEV: the library prefetches scores in a daemon thread and reads them from an
in-memory cache on the *next* turn. A hook is a short-lived process, so that
cache would die with it. Here the scorer is called synchronously with a hard
deadline (JIT_JEV_SYNC_TIMEOUT, default 1.5s) so JEV scores reach the capsule
on the same turn. Fail-open everywhere: any error -> no injection, exit 0.

Toggle: `jit off` / `jit on` (mode.json) or env JIT_CLAUDE_HOOK=0.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time

try:  # immutable runtime snapshot unless JIT_SRC / JIT_DEV_LIVE=1 say otherwise
    from jit_src_path import resolve_jit_src
    JIT_SRC = resolve_jit_src()
except ImportError:
    JIT_SRC = os.path.expanduser(os.environ.get("JIT_SRC", "~/.jit-context/src"))
HERMES_ENV = os.path.expanduser("~/.hermes/.env")
LOG_PATH = os.path.expanduser("~/.claude/logs/jit-context-hook.log")
MAX_CAPSULE_CHARS = int(os.environ.get("JIT_CLAUDE_MAX_CHARS", "8000"))
STATE_DIR = os.path.expanduser("~/.claude/state/jit-hook")
PROJECT_BLOCK_MARKER = "  [PROJECT CONTEXT]"
CAPSULE_END = "</ONA_CONTEXT>"
VOLATILE_SECTION_RE = r"## Ostatnia Sesja JIT\n.*?(?=\n## |\Z)"
# Harness-generated turns that arrive via UserPromptSubmit but are not typed by the user.
SYNTHETIC_PROMPT_PREFIXES = ("<task-notification>", "<agent-message", "<system-reminder>")


def _log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def _load_jev_key() -> None:
    """Load only JEV_OPENROUTER_KEY from ~/.hermes/.env (never the whole file)."""
    if os.environ.get("JEV_OPENROUTER_KEY"):
        return
    try:
        with open(HERMES_ENV, encoding="utf-8") as fh:
            for raw in fh:
                m = re.match(r"^\s*(?:export\s+)?JEV_OPENROUTER_KEY\s*=\s*['\"]?([^'\"\n#]+)", raw)
                if m:
                    os.environ["JEV_OPENROUTER_KEY"] = m.group(1).strip()
                    return
    except OSError:
        pass


def _is_synthetic_prompt(prompt: str) -> bool:
    """True for harness turns (subagent reports, task notifications) that must not count as user intent."""
    return prompt.lstrip().startswith(SYNTHETIC_PROMPT_PREFIXES)


def _dedupe_project_block(capsule: str, session_id: str, event: str) -> str:
    """Emit the [PROJECT CONTEXT] dossier only when it changed since the last injection in this session.

    SessionStart (startup/resume/clear/compact) always emits it in full, because
    earlier injections may no longer be in the model's context.
    """
    start = capsule.find(PROJECT_BLOCK_MARKER)
    end = capsule.rfind(CAPSULE_END)
    if start == -1 or end <= start:
        return capsule
    block = capsule[start:end]
    # The "last JIT session" section changes on every prompt (id, time, goal); ignore it when comparing.
    stable_block = re.sub(VOLATILE_SECTION_RE, "", block, flags=re.S)
    digest = hashlib.sha256(stable_block.encode("utf-8")).hexdigest()
    state_path = os.path.join(STATE_DIR, f"{session_id}.sha")
    try:
        with open(state_path, encoding="utf-8") as fh:
            last_digest = fh.read().strip()
    except OSError:
        last_digest = ""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            fh.write(digest)
    except OSError:
        return capsule
    if event == "SessionStart" or digest != last_digest:
        return capsule
    note = f"{PROJECT_BLOCK_MARKER} unchanged since the previous injection in this session (see earlier turn).\n"
    return capsule[:start] + note + capsule[end:]


def _make_jev_synchronous() -> None:
    """Score candidates synchronously (bounded) before reranking, skip the dead async prefetch."""
    from cognitive import jev_engine

    scorer = jev_engine.get_jev_scorer()
    scorer.timeout_s = float(os.environ.get("JIT_JEV_SYNC_TIMEOUT", "1.5"))
    original_rerank = scorer.rerank_hybrid

    def rerank_with_sync_scores(query, candidates):
        if candidates and scorer.is_available():
            t0 = time.time()
            scores = scorer.score_remote(query, candidates)
            _log(f"jev sync scored={len(scores)} ms={(time.time() - t0) * 1000:.0f}")
        return original_rerank(query, candidates)

    scorer.rerank_hybrid = rerank_with_sync_scores
    scorer.prefetch_async = lambda query, candidates: None


def _compile(session_id: str, cwd: str, prompt: str) -> str:
    sys.path.insert(0, JIT_SRC)
    import hooks as jit_hooks
    from l0.db import get_db
    from l0.overlay import ensure_session, update_session_cwd

    _make_jev_synchronous()
    jit_hooks.on_session_start({"session_id": session_id})

    if cwd and os.path.isdir(cwd):
        conn = get_db(session_id=session_id)
        try:
            ensure_session(conn, session_id, default_scope=os.path.basename(cwd.rstrip("/")))
            update_session_cwd(conn, session_id, cwd)
        finally:
            conn.close()

    result = jit_hooks.pre_llm_call({"session_id": session_id, "user_message": prompt})
    return (result or {}).get("context", "") or ""


def main() -> int:
    if os.environ.get("JIT_CLAUDE_HOOK", "1") in ("0", "off", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    event = payload.get("hook_event_name", "")
    if event not in ("SessionStart", "UserPromptSubmit"):
        return 0

    session_id = "cc-" + str(payload.get("session_id") or "default")
    cwd = payload.get("cwd") or os.getcwd()
    if event == "UserPromptSubmit":
        prompt = str(payload.get("prompt") or "")
        if _is_synthetic_prompt(prompt):
            _log(f"{event} session={session_id} skipped synthetic prompt")
            return 0
    else:
        prompt = f"Session {payload.get('source', 'startup')}: load project context for {os.path.basename(cwd.rstrip('/'))}"

    _load_jev_key()
    t0 = time.time()
    noise = io.StringIO()
    try:
        # The JIT runtime prints telemetry to stdout/stderr; Claude Code parses stdout as JSON.
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            capsule = _compile(session_id, cwd, prompt)
    except Exception as err:  # fail-open: never block the session
        _log(f"{event} session={session_id} error={type(err).__name__}: {err}")
        return 0

    elapsed = (time.time() - t0) * 1000
    _log(f"{event} session={session_id} cwd={cwd} chars={len(capsule)} ms={elapsed:.0f}")
    if not capsule:
        return 0
    capsule = _dedupe_project_block(capsule, session_id, event)
    if len(capsule) > MAX_CAPSULE_CHARS:
        capsule = capsule[:MAX_CAPSULE_CHARS] + "\n</ONA_CONTEXT>"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": capsule,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
