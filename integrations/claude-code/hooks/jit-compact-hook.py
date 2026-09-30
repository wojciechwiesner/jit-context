#!/usr/bin/env python3
"""Claude Code hook: JIT auto compact - keep the essentials across native compaction.

Native compaction cannot be replaced, so this wraps it:
  PreCompact   -> extract essentials from the segment being compacted (jit_compact_extract),
                  rank exchanges and evidence by relevance to the latest prompts (JEV, with a
                  token-overlap fallback), write /tmp/jit_compact/<session>/essentials.md and
                  store Bash evidence in L0 as verified_fact (so the capsule can rank it).
  PostCompact  -> save Claude Code's own summary next to it, for comparison/debugging.
  SessionStart (source=compact) -> inject essentials.md as additionalContext.
Noise (raw tool dumps, exploratory reads) is not copied: the transcript keeps it and the
essentials point to it by path and row range.
Toggle: JIT_COMPACT_HOOK=0 disables. Fail-open: any error -> no output, exit 0.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
try:  # immutable runtime snapshot unless JIT_SRC / JIT_DEV_LIVE=1 say otherwise
    from jit_src_path import resolve_jit_src
    JIT_SRC = resolve_jit_src()
except ImportError:
    JIT_SRC = os.path.expanduser(os.environ.get("JIT_SRC", "~/.jit-context/src"))
OUT_ROOT = "/tmp/jit_compact"
LOG_PATH = os.path.expanduser("~/.claude/logs/jit-compact-hook.log")
MAX_PROMPTS = 40
KEEP_LAST_EXCHANGES = 3
EXCHANGE_BUDGET = 6000
EVIDENCE_BUDGET = 1800
MAX_ERRORS = 3
FRESH_SECONDS = 3600
QUERY_PROMPTS = 3


def _log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def _session_dir(payload: dict) -> str:
    return os.path.join(OUT_ROOT, str(payload.get("session_id") or "default"))


def _rank(query: str, texts: list[str]) -> tuple[list[float], str]:
    import jit_spill_select
    if not texts:
        return [], "none"
    return jit_spill_select.score_chunks(query, texts)


def _fill(indices: list[int], texts: list[str], budget: int, forced: set[int]) -> list[int]:
    """Forced indices first, then the ranked rest while the budget allows; original order."""
    kept, used = [], 0
    for i in [*sorted(forced), *[i for i in indices if i not in forced]]:
        if i not in forced and used + len(texts[i]) > budget:
            continue
        kept.append(i)
        used += len(texts[i])
    return sorted(kept)


def build_essentials(data: dict, transcript: str, row_range: str) -> tuple[str, dict]:
    query = " | ".join(reversed(data["prompts"][-QUERY_PROMPTS:]))
    ex_texts = [f"Q: {e['prompt']}\nA: {e['answer']}" for e in data["exchanges"]]
    ex_scores, method = _rank(query, ex_texts)
    last = set(range(max(0, len(ex_texts) - KEEP_LAST_EXCHANGES), len(ex_texts)))
    ex_order = sorted(range(len(ex_texts)), key=lambda i: -ex_scores[i])
    ex_kept = _fill(ex_order, ex_texts, EXCHANGE_BUDGET, last)

    ev_texts = [f"{e['key']} => {e['value']}" for e in data["evidence"]]
    ev_scores, _ = _rank(query, ev_texts)
    ev_order = sorted(range(len(ev_texts)), key=lambda i: -ev_scores[i])
    ev_kept = _fill(ev_order, ev_texts, EVIDENCE_BUDGET, set())

    parts = [f"<JIT_COMPACT_ESSENTIALS ranked_by={method} source={transcript} rows={row_range}>",
             "Essentials kept from the compacted segment. Raw tool output and dropped exchanges "
             "remain in the transcript above (read rows on demand, do not guess).",
             "## User instructions (chronological)",
             *[f"- {p}" for p in data["prompts"][-MAX_PROMPTS:]]]
    if data["files"]:
        parts += ["## Files changed", *[f"- {f}" for f in data["files"]]]
    if ev_kept:
        parts += ["## Tool evidence (Bash, ranked)", *[f"- {ev_texts[i]}" for i in ev_kept]]
    if data["errors"]:
        parts += ["## Last tool errors", *[f"- {e}" for e in data["errors"][-MAX_ERRORS:]]]
    parts += [f"## Key exchanges ({len(ex_kept)}/{len(ex_texts)}: last {KEEP_LAST_EXCHANGES} + most relevant)",
              *[ex_texts[i] + "\n" for i in ex_kept], "</JIT_COMPACT_ESSENTIALS>"]
    stats = {"method": method, "exchanges": f"{len(ex_kept)}/{len(ex_texts)}",
             "evidence": f"{len(ev_kept)}/{len(ev_texts)}"}
    return "\n".join(parts), stats


def _store_evidence(session_id: str, evidence: list[dict]) -> int:
    """Bash evidence is runtime-verified output: record it in L0 as verified_fact."""
    from l0.db import get_db
    from l0.overlay import append_event
    conn = get_db(session_id=session_id)
    try:
        existing = {(r[0], r[1]) for r in conn.execute(
            "SELECT key, value FROM overlay WHERE session_id = ? AND kind = 'verified_fact'", (session_id,))}
        evidence = [ev for ev in evidence if (ev["key"], ev["value"]) not in existing]
        for ev in evidence:
            append_event(conn, session_id, role="tool", content=ev["value"], origin="tool_verified",
                         fact_kind="verified_fact", fact_key=ev["key"], fact_value=ev["value"])
    finally:
        conn.close()
    return len(evidence)


def on_pre_compact(payload: dict) -> None:
    import jit_compact_extract
    transcript = payload.get("transcript_path") or ""
    rows, start = jit_compact_extract.load_segment(transcript)
    data = jit_compact_extract.extract(rows)
    text, stats = build_essentials(data, transcript, f"{start}-{start + len(rows) - 1}")
    out_dir = _session_dir(payload)
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in ("essentials.md", f"essentials_{stamp}.md"):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    stored = _store_evidence("cc-" + str(payload.get("session_id") or "default"), data["evidence"])
    _log(f"PreCompact trigger={payload.get('trigger')} rows={len(rows)} chars={len(text)} "
         f"stored_facts={stored} {stats}")


def on_post_compact(payload: dict) -> None:
    out_dir = _session_dir(payload)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"native_summary_{time.strftime('%Y%m%d-%H%M%S')}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(payload.get("compact_summary") or ""))
    _log(f"PostCompact trigger={payload.get('trigger')} summary_chars={os.path.getsize(path)}")


def on_session_start(payload: dict) -> str:
    if payload.get("source") != "compact":
        return ""
    path = os.path.join(_session_dir(payload), "essentials.md")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > FRESH_SECONDS:
        _log(f"SessionStart(compact) no fresh essentials at {path}")
        return ""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    _log(f"SessionStart(compact) injected chars={len(text)}")
    return text


def main() -> int:
    if os.environ.get("JIT_COMPACT_HOOK", "1") in ("0", "off", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    sys.path.insert(0, JIT_SRC)
    sys.path.insert(0, HOOK_DIR)
    event = payload.get("hook_event_name", "")
    handlers = {"PreCompact": on_pre_compact, "PostCompact": on_post_compact,
                "SessionStart": on_session_start}
    if event not in handlers:
        return 0
    t0 = time.time()
    noise = io.StringIO()
    try:
        # jit-context prints telemetry; stdout must stay pure JSON for Claude Code.
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            context = handlers[event](payload)
    except Exception as err:
        _log(f"{event} error={type(err).__name__}: {err}")
        return 0
    _log(f"{event} done ms={(time.time() - t0) * 1000:.0f}")
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                                 "additionalContext": context}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
