"""Slot 2+5 wiring: hybrid reranker (Jev remote cache + deterministic tokens)
on jit_context runtime. Idempotent; I6 silent; removable (jev_bridge deleted
-> attribute never set, runtime falls back to getattr default None).
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter
from jev_bridge.hybrid import make_hybrid_reranker
from jev_bridge._10_shared import RECENT_QUERY


def _scorer_getter():
    try:
        from jev_bridge.jev_remote import get_shared_scorer
        cfg = plugins.get_plugin_config("jit_context") or {}
        return get_shared_scorer(cfg)
    except Exception:
        return None  # I6


class JevInitExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            get_runtime = load_runtime_getter()
            if get_runtime is None:
                return
            runtime = get_runtime()
            if getattr(runtime, "fact_reranker", None) is None:
                runtime.fact_reranker = make_hybrid_reranker(RECENT_QUERY, _scorer_getter)
        except Exception:
            return  # I6
