"""Loop Guard After Hook (tool_execute_after).

Records tool output novelty and streak progress in the per-agent LoopGuard instance.
When the guard fires (repeat detected or stall streak reached), appends a steering
nudge line to response.message.
"""

import os
import sys
from typing import Any, Dict, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension

try:  # Agent Zero: /a0/helpers is the framework namespace, the plugin lives under usr.plugins
    from usr.plugins.jit_context.helpers.loop_guard import LoopGuard, NUDGE, FORCE_ANSWER
except ImportError:  # repo tests stub `helpers` onto the plugin directory
    from helpers.loop_guard import LoopGuard, NUDGE, FORCE_ANSWER

GUARD_DATA_KEY = "jit_loop_guard"
LAST_CALL_DATA_KEY = "jit_loop_guard_last_call"
PENDING_NUDGE_DATA_KEY = "jit_loop_guard_pending_nudge"


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


class JitLoopGuardAfterExtension(Extension):
    """Observes tool output novelty and appends loop-guard nudges to response.message."""

    async def execute(
        self,
        response: Any = None,
        tool_name: str = "",
        tool_args: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        if not self.agent:
            return

        if not _is_enabled(self.agent):
            return

        guard: Optional[LoopGuard] = _get_agent_data(self.agent, GUARD_DATA_KEY)
        if guard is None:
            return

        call_info = _get_agent_data(self.agent, LAST_CALL_DATA_KEY) or {}
        repeat = call_info.get("repeat")
        turn = call_info.get("turn") or 1
        effective_tool = tool_name or call_info.get("tool_name", "unknown")
        pending_nudge = _get_agent_data(self.agent, PENDING_NUDGE_DATA_KEY)

        # Extract output text from response
        output_str = ""
        if hasattr(response, "message"):
            output_str = str(response.message or "")
        elif isinstance(response, dict) and "message" in response:
            output_str = str(response.get("message") or "")

        guard.observe_output(
            turn=turn,
            tool=effective_tool,
            output=output_str,
            repeat=repeat,
        )

        verdict = guard.after_turn(turn)

        nudges = []
        if pending_nudge:
            nudges.append(pending_nudge)
        if verdict.action in (NUDGE, FORCE_ANSWER) and verdict.message:
            nudges.append(f"[LOOP GUARD] {verdict.message}")

        if nudges and response is not None:
            nudge_text = "\n".join(nudges)
            if isinstance(response, dict):
                current_msg = response.get("message") or ""
                response["message"] = f"{current_msg}\n{nudge_text}" if current_msg else nudge_text
            elif hasattr(response, "message"):
                current_msg = getattr(response, "message", "") or ""
                setattr(response, "message", f"{current_msg}\n{nudge_text}" if current_msg else nudge_text)

        # Clear pending call state
        _set_agent_data(self.agent, LAST_CALL_DATA_KEY, None)
        _set_agent_data(self.agent, PENDING_NUDGE_DATA_KEY, None)
