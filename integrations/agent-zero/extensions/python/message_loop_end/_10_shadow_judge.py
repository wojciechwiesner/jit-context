"""Slot 1: post-turn shadow judge (message_loop_end). Feeds runtime.record_shadow_verdict.

v0.1.1: loop_data is a live LoopData OBJECT (user_message/history_output attrs);
dict access kept only as test fallback. I6: any failure is silence.
"""
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter, jit_db_path
from jev_bridge.judge import classify_turn
from jev_bridge.distill import distill_new_rows


_SESSION_WATERMARKS: dict = {}


def _last_user_query(ld) -> str:
    um = getattr(ld, "user_message", None)
    if isinstance(um, dict):
        c = um.get("content")
        if isinstance(c, str) and c.strip():
            return c
    hist = ld.get("history") if isinstance(ld, dict) else getattr(ld, "history_output", None)
    for m in reversed(list(hist or [])):
        if isinstance(m, dict) and not m.get("ai"):
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                return c
            if isinstance(c, dict):
                continue  # tool result / system warning, not a user prompt
    return ""


def _last_ai_response(ld) -> str:
    hist = ld.get("history") if isinstance(ld, dict) else getattr(ld, "history_output", None)
    for m in reversed(list(hist or [])):
        if isinstance(m, dict) and m.get("ai"):
            c = m.get("content")
            if isinstance(c, str):
                return c
            break
    return ""


def _session_id(ld, agent) -> str:
    ctx = getattr(agent, "context", None)
    sid = getattr(ctx, "id", None)
    if sid:
        return str(sid)
    if isinstance(ld, dict):
        return str(ld.get("session_id") or "default")
    return "default"


class ShadowJudgeExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            get_runtime = load_runtime_getter()
            if get_runtime is None:
                return
            runtime = get_runtime()

            ld = kwargs.get("loop_data")

            query = _last_user_query(ld)
            if query:
                try:
                    from jev_bridge._10_shared import RECENT_QUERY
                    RECENT_QUERY.update(query)
                except Exception:
                    pass

            response = _last_ai_response(ld)
            if not response:
                return

            facts = []
            try:
                facts = runtime.get_hot_facts() or []
            except Exception:
                facts = []

            verdict = classify_turn(facts, response)
            runtime.record_shadow_verdict(verdict)
            if cfg.get("jev_distill_enabled", True):
                try:
                    sid = _session_id(ld, self.agent)
                    since = _SESSION_WATERMARKS.get(sid, 0.0)
                    distill_new_rows(
                        runtime,
                        jit_db_path(),
                        session_id=sid,
                        since_ts=since,
                        cap=int(cfg.get("jev_distill_max_facts", 3)),
                    )
                    _SESSION_WATERMARKS[sid] = time.time()
                except Exception:
                    pass  # I6
        except Exception:
            return  # I6
