"""
RecentTurnFence Extension for Agent Zero Message Loop (v0.3).

Safely prunes multi-turn history on strict USER TURN boundaries,
preventing orphaned tool calls while archiving pruned context into the
JIT L0 SQLite WAL store (path derived from the runtime, never hardcoded).

I6-hardened: any internal failure returns silently; the loop is never blocked.
"""

import os
import sys
import importlib.util

from helpers.extension import Extension
from helpers import plugins
from agent import LoopData

_RUNTIME_MODULE = "usr.plugins.jit_context.helpers.runtime"


def _load_runtime():
    """Resolve the plugin runtime regardless of install location."""
    try:
        from usr.plugins.jit_context.helpers.runtime import get_runtime
        return get_runtime
    except Exception:
        pass
    mod = sys.modules.get(_RUNTIME_MODULE)
    if mod is not None and hasattr(mod, "get_runtime"):
        return mod.get_runtime
    here = os.path.abspath(__file__)
    plugin_root = os.path.abspath(os.path.join(os.path.dirname(here), "..", "..", ".."))
    for base in (
        os.environ.get("JIT_CONTEXT_PLUGIN_DIR") or "",
        "/a0/usr/plugins/jit_context",
        plugin_root,
    ):
        if not base:
            continue
        path = os.path.join(base, "helpers", "runtime.py")
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location(_RUNTIME_MODULE, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[_RUNTIME_MODULE] = mod
            try:
                spec.loader.exec_module(mod)
                return mod.get_runtime
            except Exception:
                sys.modules.pop(_RUNTIME_MODULE, None)
                return None
    return None


def _is_user_turn(msg: dict) -> bool:
    if msg.get("ai"):
        return False
    content = msg.get("content")
    if isinstance(content, dict):
        # Tool results or system warnings are not conversational user prompts
        if "tool_name" in content or "tool_result" in content or "system_warning" in content:
            return False
    return True


class RecentTurnFenceExtension(Extension):
    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        try:
            if not self.agent:
                return

            config = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if config.get("mode", "active") == "disabled":
                return

            fence_turns = int(config.get("recent_turn_fence", 4))
            if fence_turns <= 0:
                return

            get_runtime = _load_runtime()
            if get_runtime is None:
                return
            runtime = get_runtime()

            history_msgs = getattr(loop_data, "history_output", None)
            if not history_msgs or not isinstance(history_msgs, list):
                return

            user_indices = [i for i, m in enumerate(history_msgs) if _is_user_turn(m)]
            if len(user_indices) <= fence_turns:
                return

            boundary_idx = user_indices[-fence_turns]
            if boundary_idx <= 1:
                return

            initial_msg = history_msgs[0]
            pruned_slice = history_msgs[1:boundary_idx]
            recent_msgs = history_msgs[boundary_idx:]

            session_id = getattr(self.agent.context, "id", "default_session")
            tokens_avoided = runtime.archive_pruned_messages(session_id, pruned_slice)

            # Preserve valid pairing: root user message + recent turns on clean boundary
            loop_data.history_output = [initial_msg] + recent_msgs

            if hasattr(loop_data, "extras_temporary") and isinstance(
                loop_data.extras_temporary, dict
            ):
                loop_data.extras_temporary["jit_context_fence"] = (
                    f"{len(pruned_slice)} historical messages (~{tokens_avoided} tok) "
                    f"pruned to L0 SQLite WAL. Hot-memory: {len(recent_msgs)} messages."
                )
        except Exception:
            return  # I6: never block the loop
