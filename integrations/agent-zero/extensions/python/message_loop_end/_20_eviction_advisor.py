"""Slot 4 wiring: post-turn budget check -> advice rows (message_loop_end). I6 silent."""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter
from jev_bridge.advice import write_eviction_advice


def _jev_db_path() -> str:
    return os.path.join(_ROOT, "data", "jev_bridge.db")


class EvictionAdvisorExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            get_runtime = load_runtime_getter()
            if get_runtime is None:
                return
            runtime = get_runtime()
            max_tok = int(cfg.get("max_capsule_tokens", 1500))
            pct = float(cfg.get("jev_eviction_budget_pct", 0.9))
            write_eviction_advice(runtime, _jev_db_path(), max_tok, pct)
        except Exception:
            return  # I6
