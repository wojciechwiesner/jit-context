"""Slot 5 wiring: prefetch Jev scores off the hot path.

message_loop_start fires AFTER the capsule was compiled for this iteration,
so prefetched scores serve the NEXT iteration (tool rounds) and later turns
via TTL cache. Daemon thread; I6 silent on every failure.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter


def _query_from_loop_data(ld) -> str:
    """Same extraction contract as _10_shadow_judge: LoopData object or dict."""
    um = getattr(ld, "user_message", None)
    if isinstance(um, dict):
        c = um.get("content")
        if isinstance(c, str) and c.strip():
            return c
    if isinstance(um, str) and um.strip():
        return um
    hist = ld.get("history") if isinstance(ld, dict) else getattr(ld, "history_output", None)
    for m in reversed(list(hist or [])):
        if isinstance(m, dict) and not m.get("ai"):
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                return c
    return ""


class JevPrefetchExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            query = _query_from_loop_data(kwargs.get("loop_data"))
            if not query:
                return
            from jev_bridge._10_shared import RECENT_QUERY
            RECENT_QUERY.update(query)
            scorer = None
            try:
                from jev_bridge.jev_remote import get_shared_scorer
                scorer = get_shared_scorer(cfg)
            except Exception:
                return  # I6
            if scorer is None:
                return  # remote disabled or no key
            facts = []
            try:
                get_runtime = load_runtime_getter()
                if get_runtime is not None:
                    facts = get_runtime().get_hot_facts() or []
            except Exception:
                facts = []
            if facts:
                scorer.prefetch_async(RECENT_QUERY.text, facts)
        except Exception:
            return  # I6
