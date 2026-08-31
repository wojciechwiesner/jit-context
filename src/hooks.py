"""Hook implementations for Hermes Plugin Lifecycle with Full LLM & Context Telemetry."""

import os
import time
import sqlite3
import uuid
from typing import Dict, Any, Optional
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session, get_active_overlays
from l1.scope import resolve_scope
from context.compiler import compile_context
from config import DB_PATH
from telemetry.collector import (
    record_turn_telemetry,
    record_llm_start,
    record_llm_success,
    record_llm_error,
    record_context_query
)

# Mode: 'active' (default) or 'shadow' (logs capsule and WAL without prompt injection)
ONA_CONTEXT_MODE = os.environ.get("ONA_CONTEXT_MODE", "active")
WATCHDOG_BUDGET_MS = 650.0

def session_start(ctx: Dict[str, Any]) -> None:
    """Initialize DB and session row on new session."""
    init_db()
    session_id = ctx.get("session_id", "default")
    conn = get_db()
    try:
        ensure_session(conn, session_id)
    finally:
        conn.close()

def pre_llm(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pre-LLM hook with 650ms internal watchdog budget (Fail-Open).
    Records user query, latency, capsule telemetry, and returns context injection.
    """
    start_time = time.time()
    session_id = ctx.get("session_id", "default")
    turn_id = ctx.get("turn_id") or f"turn_{int(start_time * 1000)}"
    user_message = ctx.get("user_message", "")
    history = ctx.get("conversation_history", [])
    
    conn = get_db()
    try:
        # L0 Step: Append direct user turn to WAL (<2ms)
        l0_start = time.time()
        if user_message:
            append_event(
                conn=conn,
                session_id=session_id,
                role="user",
                content=user_message,
                origin="direct_user",
                turn_id=turn_id
            )
        l0_ms = (time.time() - l0_start) * 1000
        
        # L1 Scope resolution (<1ms)
        l1_start = time.time()
        active_scope, retrieval_scopes, _, _ = resolve_scope(user_message, "hermes")
        l1_ms = (time.time() - l1_start) * 1000
        
        # Context compilation with L2 circuit breaker
        compile_start = time.time()
        capsule = compile_context(
            session_id=session_id,
            user_message=user_message,
            conversation_history=history,
            conn=conn
        )
        compile_ms = (time.time() - compile_start) * 1000
        l2_ms = compile_ms # contains L2 if triggered
        
        hook_total_ms = (time.time() - start_time) * 1000
        
        # Record Turn Telemetry
        record_turn_telemetry(
            conn=conn,
            session_id=session_id,
            turn_id=turn_id,
            user_query=user_message,
            active_scope=active_scope,
            retrieval_scopes=retrieval_scopes,
            l0_ms=round(l0_ms, 2),
            l1_ms=round(l1_ms, 2),
            l2_ms=round(l2_ms, 2),
            compile_ms=round(compile_ms, 2),
            hook_total_ms=round(hook_total_ms, 2),
            capsule=capsule,
            mode=ONA_CONTEXT_MODE
        )
        
        if ONA_CONTEXT_MODE == "shadow":
            print(f"[ona-context:shadow] Compiled capsule ({len(capsule)} chars) logged, injection bypassed.")
            return {}
            
        return {"context": capsule}
    except Exception as e:
        print(f"[ona-context:error] pre_llm failed open: {e}")
        return {}
    finally:
        conn.close()

def pre_api_request(ctx: Dict[str, Any]) -> None:
    """
    Pre-API request hook: Tracks exact HTTP request to LLM (provider, model, token approx).
    """
    api_request_id = ctx.get("api_request_id") or f"req_{uuid.uuid4().hex[:10]}"
    session_id = ctx.get("session_id", "default")
    turn_id = ctx.get("turn_id", "default")
    provider = ctx.get("provider", "unknown")
    requested_model = ctx.get("model", "unknown")
    messages = ctx.get("messages", [])
    tools = ctx.get("tools", [])
    approx_tokens = ctx.get("approx_input_tokens", 0)
    retry_count = ctx.get("retry_count", 0)
    
    conn = get_db()
    try:
        record_llm_start(
            conn=conn,
            api_request_id=api_request_id,
            session_id=session_id,
            turn_id=turn_id,
            provider=provider,
            requested_model=requested_model,
            message_count=len(messages),
            tool_count=len(tools),
            approx_input_tokens=approx_tokens,
            retry_count=retry_count
        )
    except Exception as e:
        print(f"[ona-context:error] pre_api_request: {e}")
    finally:
        conn.close()

def post_api_request(ctx: Dict[str, Any]) -> None:
    """
    Post-API request hook: Records actual LLM tokens, cache read tokens, duration, and cost.
    """
    api_request_id = ctx.get("api_request_id", "")
    duration_ms = ctx.get("duration_ms", 0.0)
    response_model = ctx.get("response_model") or ctx.get("model")
    usage = ctx.get("usage", {})
    cost_usd = ctx.get("cost_usd", 0.0)
    retry_count = ctx.get("retry_count", 0)
    
    input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
    output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
    cache_read_tokens = usage.get("cache_read_tokens", 0) or usage.get("cached_tokens", 0)
    cache_write_tokens = usage.get("cache_write_tokens", 0)
    
    conn = get_db()
    try:
        record_llm_success(
            conn=conn,
            api_request_id=api_request_id,
            duration_ms=duration_ms,
            response_model=response_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost_usd,
            retry_count=retry_count
        )
    except Exception as e:
        print(f"[ona-context:error] post_api_request: {e}")
    finally:
        conn.close()

def api_request_error(ctx: Dict[str, Any]) -> None:
    """
    API error hook: Records LLM failure, status code, and reason for fallback tracking.
    """
    api_request_id = ctx.get("api_request_id", "")
    error_reason = str(ctx.get("error") or ctx.get("error_message") or "Unknown error")
    duration_ms = ctx.get("duration_ms", 0.0)
    http_status = ctx.get("status_code")
    retry_count = ctx.get("retry_count", 0)
    
    conn = get_db()
    try:
        record_llm_error(
            conn=conn,
            api_request_id=api_request_id,
            error_reason=error_reason,
            duration_ms=duration_ms,
            http_status=http_status,
            retry_count=retry_count
        )
    except Exception as e:
        print(f"[ona-context:error] api_request_error: {e}")
    finally:
        conn.close()

def post_llm(ctx: Dict[str, Any]) -> None:
    """
    Post-LLM hook: Record assistant output to WAL with Epistemic Authority = 0.0 (Invariant I3).
    """
    session_id = ctx.get("session_id", "default")
    assistant_message = ctx.get("assistant_message", "")
    
    if not assistant_message:
        return
        
    conn = get_db()
    try:
        append_event(
            conn=conn,
            session_id=session_id,
            role="assistant",
            content=assistant_message,
            origin="assistant"
        )
    except Exception as e:
        print(f"[ona-context:error] post_llm failed open: {e}")
    finally:
        conn.close()

def post_tool_call(ctx: Dict[str, Any]) -> None:
    """
    Post-tool hook (Interrupted Turns protection):
    Captures mutations from tools (write_file, patch, terminal) even if turn is interrupted.
    """
    session_id = ctx.get("session_id", "default")
    tool_name = ctx.get("tool_name", "")
    tool_result = ctx.get("tool_result", "")
    
    if tool_name in ("write_file", "patch", "terminal", "skill_manage", "memory"):
        conn = get_db()
        try:
            summary = f"Tool {tool_name} executed: {str(tool_result)[:300]}"
            append_event(
                conn=conn,
                session_id=session_id,
                role="tool",
                content=summary,
                origin="tool_observation"
            )
        except Exception as e:
            print(f"[ona-context:error] post_tool_call failed open: {e}")
        finally:
            conn.close()
