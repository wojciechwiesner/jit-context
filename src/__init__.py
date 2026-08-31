"""Hermes JIT Context OS Plugin (ona-context)."""

try:
    from .hooks import (
        pre_llm,
        post_llm,
        pre_api_request,
        post_api_request,
        api_request_error,
        post_tool_call,
        session_start
    )
except ImportError:
    from hooks import (
        pre_llm,
        post_llm,
        pre_api_request,
        post_api_request,
        api_request_error,
        post_tool_call,
        session_start
    )

def register(ctx):
    """Plugin registration entry point for Hermes Agent."""
    ctx.register_hook("pre_llm_call", pre_llm)
    ctx.register_hook("post_llm_call", post_llm)
    ctx.register_hook("pre_api_request", pre_api_request)
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_hook("api_request_error", api_request_error)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("on_session_start", session_start)
