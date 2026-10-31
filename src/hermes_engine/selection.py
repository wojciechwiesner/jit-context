"""Pure wire-message selection for the JIT context engine.

Hermes keeps the full transcript in the session; this module only decides what a
single API request carries. It never mutates its input.

Rules (in order):
1. The system message, every user message and every assistant text stay verbatim.
2. Tool results inside the last ``keep_recent_turns`` user turns stay verbatim.
3. Older tool results longer than ``min_prune_chars`` become a one-line pointer
   with the tool name, size and the first line, so the model can re-run the tool.
4. Assistant tool calls are never removed, so every tool result keeps its call
   (providers reject orphaned tool messages).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

POINTER_PREFIX = "[JIT: earlier tool output elided"


@dataclass(frozen=True)
class SelectionStats:
    """What one selection did; surfaced in logs and tests."""

    messages: int
    pruned_results: int
    chars_before: int
    chars_after: int

    @property
    def chars_saved(self) -> int:
        return self.chars_before - self.chars_after


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(part for part in parts if part)
    return ""


def _message_chars(message: dict[str, Any]) -> int:
    return len(_content_text(message))


def recent_turn_start(messages: list[dict[str, Any]], keep_recent_turns: int) -> int:
    """Index of the first message of the oldest protected user turn."""
    if keep_recent_turns <= 0:
        return len(messages)
    user_indexes = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if len(user_indexes) <= keep_recent_turns:
        return 0
    return user_indexes[-keep_recent_turns]


def _tool_name_by_call_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            call_id = call.get("id")
            if call_id:
                names[call_id] = function.get("name") or "tool"
    return names


def _pointer(message: dict[str, Any], tool_name: str) -> str:
    text = _content_text(message)
    first_line = text.strip().splitlines()[0][:160] if text.strip() else ""
    return (
        f"{POINTER_PREFIX}: {tool_name}, {len(text)} chars. "
        f"First line: {first_line!r}. Re-run the tool if you need the full output.]"
    )


def select_wire_messages(
    messages: list[dict[str, Any]],
    *,
    keep_recent_turns: int = 2,
    min_prune_chars: int = 1200,
) -> tuple[list[dict[str, Any]], SelectionStats]:
    """Return the messages to send plus stats; the input list is not modified."""
    protected_from = recent_turn_start(messages, keep_recent_turns)
    tool_names = _tool_name_by_call_id(messages)
    selected: list[dict[str, Any]] = []
    pruned = 0
    for index, message in enumerate(messages):
        is_old_tool_result = message.get("role") == "tool" and index < protected_from
        if is_old_tool_result and _message_chars(message) > min_prune_chars:
            tool_name = tool_names.get(message.get("tool_call_id") or "", message.get("name") or "tool")
            replacement = dict(message)
            replacement["content"] = _pointer(message, tool_name)
            selected.append(replacement)
            pruned += 1
        else:
            selected.append(message)
    stats = SelectionStats(
        messages=len(messages),
        pruned_results=pruned,
        chars_before=sum(_message_chars(m) for m in messages),
        chars_after=sum(_message_chars(m) for m in selected),
    )
    assert stats.chars_after <= stats.chars_before, "selection must never grow the request"
    return selected, stats
