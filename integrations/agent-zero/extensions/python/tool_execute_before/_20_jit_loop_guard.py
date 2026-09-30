"""Loop Guard Before Hook (tool_execute_before).

Feeds each tool call to the per-agent LoopGuard instance.
Detects exact repeats and near-repeat search queries before tool execution.

Safe Action Decision for Exact Repeats:
In Agent Zero's core runtime (agent.py:1213-1219 and agent.py:1493-1499), `tool_execute_before`
extensions are invoked immediately prior to `response = await tool.execute(**tool_args)`.
The runtime does not check or act on return values from `call_extensions_async`, meaning an
extension cannot cancel or bypass tool invocation by returning a value. Raising an exception
bubbles up to `agent.py:541` (`await self.handle_exception("message_loop", e)`), which aborts
or retries the loop destructively. Mutating `tool_args` to dummy or empty values violates tool
parameter signatures and triggers runtime `TypeError`s during `tool.execute()`.

Therefore, the safe, non-destructive policy for exact repeats is:
1. Classify the call using `LoopGuard.classify_call(tool_name, tool_args)`.
2. Record the repeat status (`exact_repeat` or `near_repeat`) and a pending nudge message in
   per-agent storage (`agent.set_data(...)`).
3. Permit the tool call to proceed normally and safely to `await tool.execute(**tool_args)`
   (justified by agent.py line 1499).
4. The companion after-hook (`tool_execute_after/_20_jit_loop_guard.py`) intercepts the completed
   response, records the novelty ratio (flagging zero progress for repeats), and appends the
   nudge banner to `response.message`.
"""

import os
import sys
from typing import Any, Dict, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension

try:  # Agent Zero: /a0/helpers is the framework namespace, the plugin lives under usr.plugins
    from usr.plugins.jit_context.helpers.loop_guard import LoopGuard
except ImportError:  # repo tests stub `helpers` onto the plugin directory
    from helpers.loop_guard import LoopGuard

GUARD_DATA_KEY = "jit_loop_guard"
LAST_CALL_DATA_KEY = "jit_loop_guard_last_call"
PENDING_NUDGE_DATA_KEY = "jit_loop_guard_pending_nudge"
CALL_COUNTER_DATA_KEY = "jit_loop_guard_call_count"


def _is_enabled(agent: Any = None) -> bool:
    env_val = os.environ.get("JIT_A0_LOOP_GUARD", "").strip().lower()
    if env_val in ("0", "false", "no", "off"):
        return False
    try:
        from helpers import plugins
        cfg = plugins.get_plugin_config("jit_context", agent=agent) or {}
        if cfg.get("loop_guard_enabled") is False or cfg.get("mode") == "disabled":
            return False
    except Exception:
        pass
    return True


def _get_agent_data(agent: Any, key: str, default: Any = None) -> Any:
    if hasattr(agent, "get_data"):
        val = agent.get_data(key)
        return val if val is not None else default
    data = getattr(agent, "data", None)
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(agent, f"_{key}", default)


def _set_agent_data(agent: Any, key: str, value: Any) -> None:
    if hasattr(agent, "set_data"):
        agent.set_data(key, value)
    elif hasattr(agent, "data") and isinstance(agent.data, dict):
        agent.data[key] = value
    else:
        setattr(agent, f"_{key}", value)


def _determine_turn(agent: Any) -> int:
    ld = getattr(agent, "loop_data", None)
    if ld is not None:
        it = getattr(ld, "iteration", None)
        if isinstance(it, int) and it >= 0:
            return it + 1
        if isinstance(ld, dict) and isinstance(ld.get("iteration"), int):
            return ld["iteration"] + 1

    count = _get_agent_data(agent, CALL_COUNTER_DATA_KEY, 0) + 1
    _set_agent_data(agent, CALL_COUNTER_DATA_KEY, count)
    return count


class JitLoopGuardBeforeExtension(Extension):
    """Intercepts tool calls before execution to classify repeat patterns."""

    async def execute(
        self,
        tool_args: Optional[Dict[str, Any]] = None,
        tool_name: str = "",
        **kwargs: Any,
    ) -> None:
        if not self.agent:
            return

        if not _is_enabled(self.agent):
            return

        guard: Optional[LoopGuard] = _get_agent_data(self.agent, GUARD_DATA_KEY)
        if guard is None:
            guard = LoopGuard()
            _set_agent_data(self.agent, GUARD_DATA_KEY, guard)

        args = tool_args if isinstance(tool_args, dict) else {}
        repeat = guard.classify_call(tool_name, args)
        turn = _determine_turn(self.agent)

        call_info = {
            "tool_name": tool_name,
            "tool_args": args,
            "repeat": repeat,
            "turn": turn,
        }
        _set_agent_data(self.agent, LAST_CALL_DATA_KEY, call_info)

        if repeat == "exact_repeat":
            pending_nudge = (
                f"[LOOP GUARD] Warning: Exact repeat of tool '{tool_name}' with identical arguments."
            )
            _set_agent_data(self.agent, PENDING_NUDGE_DATA_KEY, pending_nudge)
        else:
            _set_agent_data(self.agent, PENDING_NUDGE_DATA_KEY, None)
