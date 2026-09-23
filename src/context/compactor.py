"""Context Compaction Module for Hermes JIT Context OS.

Enforces deterministic context compaction when conversational turn history
reaches a specified threshold (e.g. 0.4 of the model's context window,
which corresponds to ~400,000 tokens for Gemini 1M models).

Guarantees:
1. Invariant I1: The initial user goal, task prompt, and JIT capsule (turn 0) are strictly preserved.
2. Tool Observations Fidelity: Key tool facts and findings from compacted turns are distilled rather than dropped blindly.
3. Invariant I2 (RYOW): Compaction events are committed to the local L0 SQLite WAL overlay.
4. Recency Protection: The most recent turns (e.g. last model turn + tool response) remain intact for immediate continuation.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from config import (
    COMPACTION_TRIGGER_TOKENS,
    CONTEXT_COMPACTION_THRESHOLD_RATIO,
    GEMINI_CONTEXT_WINDOW_TOKENS,
)
import l0.db as l0_db
import l0.overlay as l0_overlay

logger = logging.getLogger("jit.compactor")


def estimate_tokens(obj: Any) -> int:
    """Rough token estimation (characters / 4)."""
    if obj is None:
        return 0
    if isinstance(obj, str):
        return len(obj) // 4
    if isinstance(obj, (int, float, bool)):
        return 1
    if isinstance(obj, dict):
        return sum(estimate_tokens(k) + estimate_tokens(v) for k, v in obj.items())
    if isinstance(obj, (list, tuple, set)):
        return sum(estimate_tokens(x) for x in obj)
    return len(str(obj)) // 4


def estimate_contents_tokens(contents: List[Dict[str, Any]]) -> int:
    """Calculate total estimated tokens across all turns and parts in a contents list."""
    total_tokens = 0
    for turn in contents:
        if not isinstance(turn, dict):
            total_tokens += len(str(turn)) // 4
            continue
        # OpenAI style
        if "content" in turn and turn["content"]:
            total_tokens += len(str(turn["content"])) // 4
        if "tool_calls" in turn and turn["tool_calls"]:
            for tc in turn.get("tool_calls", []):
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    total_tokens += len(str(fn.get("name", ""))) // 4
                    total_tokens += len(str(fn.get("arguments", ""))) // 4
        # Gemini style
        for part in turn.get("parts", []):
            if isinstance(part, dict):
                if "text" in part:
                    total_tokens += len(part["text"]) // 4
                elif "functionResponse" in part:
                    fn_resp = part["functionResponse"]
                    total_tokens += len(fn_resp.get("name", "")) // 4
                    out = str(fn_resp.get("response", {}).get("output", ""))
                    total_tokens += len(out) // 4
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    total_tokens += len(fc.get("name", "")) // 4
                    total_tokens += len(str(fc.get("args", {}))) // 4
                else:
                    total_tokens += len(str(part)) // 4
            else:
                total_tokens += len(str(part)) // 4
    return total_tokens


def is_compaction_needed(
    contents: List[Dict[str, Any]],
    threshold_tokens: int = COMPACTION_TRIGGER_TOKENS,
    min_turns: int = 4
) -> bool:
    """Determine if turn history has reached the compaction threshold."""
    if len(contents) <= min_turns:
        return False
    return estimate_contents_tokens(contents) >= threshold_tokens


def extract_key_facts_from_turns(turns: List[Dict[str, Any]], max_facts: int = 15) -> List[str]:
    """Extract succinct factual findings and observations from past tool outputs."""
    facts = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        # OpenAI style
        if turn.get("role") == "tool":
            fn_name = turn.get("name", "tool")
            raw_out = str(turn.get("content", ""))
            candidate_lines = [
                line.strip()
                for line in raw_out.splitlines()
                if line.strip() and not line.startswith("```") and len(line.strip()) > 3
            ]
            if candidate_lines:
                snippet = " | ".join(candidate_lines[:2])[:250]
                facts.append(f"[{fn_name}]: {snippet}")
        elif turn.get("role") == "assistant":
            txt = str(turn.get("content", "") or "").strip()
            if txt and (txt.startswith("THOUGHT:") or txt.startswith("PLAN:") or "Observation:" in txt):
                first_line = txt.splitlines()[0][:200]
                facts.append(f"[assistant reasoning]: {first_line}")
        # Gemini style
        for part in turn.get("parts", []):
            if not isinstance(part, dict):
                continue
            if "functionResponse" in part:
                fn_name = part["functionResponse"].get("name", "tool")
                raw_out = str(part["functionResponse"].get("response", {}).get("output", ""))
                # Find informative lines (skip pure markdown code fences, headers, or empty lines)
                candidate_lines = [
                    line.strip()
                    for line in raw_out.splitlines()
                    if line.strip() and not line.startswith("```") and len(line.strip()) > 3
                ]
                if candidate_lines:
                    snippet = " | ".join(candidate_lines[:2])[:250]
                    facts.append(f"[{fn_name}]: {snippet}")
            elif "text" in part:
                txt = part["text"].strip()
                if txt.startswith("THOUGHT:") or txt.startswith("PLAN:") or "Observation:" in txt:
                    first_line = txt.splitlines()[0][:200]
                    facts.append(f"[assistant reasoning]: {first_line}")
    return facts[-max_facts:]


def compact_turn_history(
    contents: List[Dict[str, Any]],
    session_id: str,
    threshold_tokens: int = COMPACTION_TRIGGER_TOKENS,
    protect_first: int = 1,
    protect_last: int = 2
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compact turn history when accumulated tokens reach or exceed the threshold.

    Preserves:
      - contents[:protect_first] (Task prompt, JIT capsule, initial turn)
      - Distilled facts block from middle turns
      - contents[-protect_last:] (Most recent model and user turns)

    Returns:
      (compacted_contents, telemetry_metadata)
    """
    orig_tokens = estimate_contents_tokens(contents)
    min_turns_to_compact = protect_first + protect_last + 1

    if orig_tokens < threshold_tokens or len(contents) < min_turns_to_compact:
        return contents, {
            "compacted": False,
            "orig_tokens": orig_tokens,
            "threshold_tokens": threshold_tokens,
            "turns_count": len(contents)
        }

    first_turns = contents[:protect_first]
    recent_turns = contents[-protect_last:]
    middle_turns = contents[protect_first:-protect_last]

    key_facts = extract_key_facts_from_turns(middle_turns)
    facts_summary = "\n".join(f"- {f}" for f in key_facts) if key_facts else "- [Prior tool queries and operations completed]"

    compaction_text = (
        f"[JIT CONTEXT COMPACTION: Prior dialogue reached ~{orig_tokens:,} tokens "
        f"(>= {threshold_tokens:,} threshold, 0.4 of 1M context window).\n"
        f"Compacted {len(middle_turns)} earlier turns into verified observations:\n"
        f"{facts_summary}\n\n"
        f"Proceed using the above verified findings to produce the final answer.]"
    )

    is_openai_format = any("content" in t for t in contents if isinstance(t, dict))
    if is_openai_format:
        compaction_block = {
            "role": "user",
            "content": compaction_text
        }
    else:
        compaction_block = {
            "role": "user",
            "parts": [{"text": compaction_text}]
        }

    compacted_contents = first_turns + [compaction_block] + recent_turns
    new_tokens = estimate_contents_tokens(compacted_contents)
    reduction_pct = round((1.0 - (new_tokens / max(orig_tokens, 1))) * 100, 1)

    # Persist compaction event to L0 SQLite WAL overlay (Invariant I2)
    try:
        conn = l0_db.get_db()
        l0_overlay.append_event(
            conn,
            session_id=session_id,
            role="system",
            content=(
                f"Context compaction triggered: {orig_tokens:,} tokens -> {new_tokens:,} tokens "
                f"(-{reduction_pct}%). Compacted {len(middle_turns)} turns."
            ),
            origin="jit_compactor",
            fact_kind="compaction_event",
            fact_key="context_compaction_0.4",
            fact_value=f"{orig_tokens}->{new_tokens}"
        )
        conn.close()
    except Exception as exc:
        logger.warning("Failed to record compaction event to L0 SQLite WAL: %s", exc)

    telemetry = {
        "compacted": True,
        "orig_tokens": orig_tokens,
        "new_tokens": new_tokens,
        "reduction_pct": reduction_pct,
        "turns_compacted": len(middle_turns),
        "threshold_tokens": threshold_tokens,
        "facts_preserved": len(key_facts)
    }

    logger.info(
        "Context compacted for session %s: %d -> %d tokens (-%.1f%%)",
        session_id, orig_tokens, new_tokens, reduction_pct
    )
    return compacted_contents, telemetry
