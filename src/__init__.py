"""Hermes JIT Context OS plugin registration."""

import sys
from pathlib import Path

# The existing Context OS modules use absolute intra-plugin imports
# (``from l0...``).  Hermes loads directory plugins as packages, so expose
# this trusted plugin root while importing its legacy module tree.
_PLUGIN_ROOT = str(Path(__file__).resolve().parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from .hooks import (
    api_request_error,
    post_api_request,
    post_llm,
    post_tool_call,
    pre_api_request,
    pre_llm,
    session_start,
)


def _hook_callback(handler, *, aliases=None):
    """Adapt Hermes keyword hook payloads to the plugin's context mapping."""
    aliases = aliases or {}

    def callback(**kwargs):
        context = dict(kwargs)
        for target, source in aliases.items():
            if target not in context and source in context:
                context[target] = context[source]
        return handler(context)

    callback.__name__ = handler.__name__
    return callback


def register(ctx):
    """Register Context OS lifecycle hooks with Hermes' native plugin API."""
    ctx.register_hook("pre_llm_call", _hook_callback(pre_llm))
    ctx.register_hook(
        "post_llm_call",
        _hook_callback(post_llm, aliases={"assistant_message": "assistant_response"}),
    )
    ctx.register_hook("pre_api_request", _hook_callback(pre_api_request))
    ctx.register_hook("post_api_request", _hook_callback(post_api_request))
    ctx.register_hook("api_request_error", _hook_callback(api_request_error))
    ctx.register_hook(
        "post_tool_call",
        _hook_callback(post_tool_call, aliases={"tool_result": "result"}),
    )
    ctx.register_hook("on_session_start", _hook_callback(session_start))

    # Register CLI Slash Command /jit
    def _jit_cmd_handler(raw_args: str = "") -> str:
        import os, json, time
        arg = (raw_args or "").strip().lower()
        if arg in ["on", "active", "enable"]:
            os.environ["ONA_CONTEXT_MODE"] = "active"
            try:
                p = "/tmp/hermes-jit-live.json"
                d = {"mode": "active", "ts": time.time()}
                if os.path.exists(p):
                    with open(p) as f: d = json.load(f)
                    d["mode"] = "active"
                    d["ts"] = time.time()
                with open(p, "w") as f: json.dump(d, f)
            except Exception: pass
            return "⚡ [JIT Context OS] Tryb: ACTIVE (kapsuła JIT jest wstrzykiwana do promptu)."

        if arg in ["off", "shadow", "disable"]:
            os.environ["ONA_CONTEXT_MODE"] = "shadow"
            try:
                p = "/tmp/hermes-jit-live.json"
                d = {"mode": "shadow", "ts": time.time()}
                if os.path.exists(p):
                    with open(p) as f: d = json.load(f)
                    d["mode"] = "shadow"
                    d["ts"] = time.time()
                with open(p, "w") as f: json.dump(d, f)
            except Exception: pass
            return "🛡️ [JIT Context OS] Tryb: SHADOW (pasywny pomiar telemetryczny, brak modyfikacji promptu)."

        if arg == "doctor":
            from .health.autocheck import get_health_report
            rep = get_health_report()
            return f"🩺 [JIT Doctor]\nStatus: {rep.get('status')}\nL0 WAL: {rep.get('l0', {}).get('wal')}\nInwarianty: {rep.get('invariants')}"

        if arg in ["ui", "web", "dashboard"]:
            return "🌐 [JIT Context Observatory WebUI]\nURL: http://127.0.0.1:8765/\nDziała na żywo."

        mode = os.environ.get("ONA_CONTEXT_MODE", "active")
        return (
            f"⚡ [HERMES JIT CONTEXT OS]\n"
            f"• Tryb: {mode.upper()}\n"
            f"• WebUI: http://127.0.0.1:8765/\n"
            f"• Pasek CLI: aktywny (⚡ JIT)\n"
            f"• Opcje: /jit on | /jit off | /jit doctor | /jit ui"
        )

    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "jit",
            _jit_cmd_handler,
            description="Włącz/wyłącz lub sprawdź status JIT Context OS",
            args_hint="[on|off|doctor|ui]"
        )
