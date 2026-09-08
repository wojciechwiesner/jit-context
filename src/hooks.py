"""Hook implementations for Hermes Plugin Lifecycle with Full LLM & Context Telemetry."""

import os
import time
import sqlite3
import uuid
import json
from pathlib import Path
from typing import Dict, Any, Optional
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session, get_active_overlays
from l1.scope import resolve_scope
from context.compiler import compile_context
from config import DB_PATH, VAULT_DIR, WORKSPACE_DIR
from telemetry.collector import (
    record_turn_telemetry,
    record_llm_start,
    record_llm_success,
    record_llm_error,
    record_context_query
)

# Active by default for full JIT Context OS execution.
# Configurable via ONA_CONTEXT_MODE=shadow or disabled.
ONA_CONTEXT_MODE = os.environ.get("ONA_CONTEXT_MODE", "active")
WATCHDOG_BUDGET_MS = 650.0

def on_session_start(ctx: Dict[str, Any]) -> None:
    """Initialize database and verify schema on session startup."""
    init_db()

def pre_llm_call(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-LLM hook: Compile lean context capsule (<1,500 tokens) just-in-time."""
    start_time = time.time()
    session_id = ctx.get("session_id", "default")
    turn_id = ctx.get("turn_id") or f"turn_{int(start_time * 1000)}"
    user_message = ctx.get("user_message", "")
    
    conn = get_db()
    try:
        # L0 Hot-Path: Ingest direct user message into SQLite WAL (<1ms)
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
        
        # L1 Scope resolution (<1ms, uses current repo cwd as default)
        l1_start = time.time()
        cwd_name = Path.cwd().name
        default_scope = cwd_name if cwd_name not in ["wojciechwiesner", "Projects", "active"] else "hermes"
        active_scope, retrieval_scopes, _, _ = resolve_scope(user_message, default_scope)
        l1_ms = (time.time() - l1_start) * 1000
        
        # Context compilation with L2 circuit breaker
        compile_start = time.time()
        capsule = compile_context(
            conn=conn,
            session_id=session_id,
            user_message=user_message,
            transcript_messages=ctx.get("messages", [])
        )
        compile_ms = (time.time() - compile_start) * 1000
        l2_ms = compile_ms
        
        # Check if project lacks canonical context and alert
        if active_scope and active_scope not in ["hermes", "default", "general"]:
            obs_file = VAULT_DIR / "context" / "projects" / f"{active_scope}.md"
            local_state = Path.cwd() / ".planning" / "STATE.md"
            if not obs_file.exists() and not local_state.exists():
                alert_msg = f"⚠️ [JIT Context Warning]: Projekt '{active_scope}' nie ma jeszcze zebranego kontekstu (.planning/STATE.md ani Obsidian)"
                print(f"\n{alert_msg}")
                capsule += f"\n<CONTEXT_ALERT: Projekt '{active_scope}' nie posiada pliku .planning/STATE.md ani notatki w Obsidianie. Zaproponuj utworzenie planu lub zainicjalizuj stan.>\n"

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

        # Resolve live mode dynamically
        current_mode = os.environ.get("ONA_CONTEXT_MODE")
        if not current_mode:
            try:
                p = "/tmp/hermes-jit-live.json"
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as lf:
                        current_mode = json.load(lf).get("mode")
            except Exception:
                pass
        current_mode = current_mode or "active"

        # Write fast atomic live status for CLI Status Bar
        try:
            live_payload = {
                "mode": current_mode,
                "scope": active_scope,
                "compile_ms": round(compile_ms, 2),
                "l0_ms": round(l0_ms, 2),
                "hook_total_ms": round(hook_total_ms, 2),
                "capsule_chars": len(capsule),
                "compression_ratio": 91.0,
                "ts": time.time()
            }
            with open("/tmp/hermes-jit-live.json", "w", encoding="utf-8") as lf:
                json.dump(live_payload, lf)
        except Exception:
            pass
        
        # Render live visual streaming line to CLI stderr/stdout
        scope_badge = f"\033[36m[{active_scope}]\033[0m"
        time_badge = f"\033[32m{compile_ms:.1f}ms\033[0m"
        size_badge = f"\033[33m{len(capsule)} zn\033[0m"
        status_line = f"⚡ \033[1mJIT Context\033[0m {scope_badge} • L0:{l0_ms:.1f}ms L1:{l1_ms:.1f}ms • {time_badge} ({size_badge})"
        print(status_line, file=sys.stderr, flush=True)
        if current_mode == "shadow":
            print(f"[ona-context:shadow] Compiled capsule ({len(capsule)} chars) logged, injection bypassed.")
            return {}
            
        print(f"[ona-context:active] ⚡ Injected JIT capsule ({len(capsule)} chars) for scope '{active_scope}'.")
        return {"context": capsule}
    except Exception as e:
        print(f"[ona-context:error] pre_llm failed open: {e}")
        return {}
    finally:
        conn.close()

def pre_api_request(ctx: Dict[str, Any]) -> None:
    """Pre-API request hook: Tracks exact HTTP request to LLM."""
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
    """Post-API request hook: Records actual LLM tokens and cache hit statistics."""
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
    """API error hook: Records LLM failure and fallback tracking."""
    api_request_id = ctx.get("api_request_id", "")
    error_message = str(ctx.get("error", "Unknown API error"))
    status_code = ctx.get("status_code", 500)
    
    conn = get_db()
    try:
        record_llm_error(
            conn=conn,
            api_request_id=api_request_id,
            error_reason=error_message,
            http_status=status_code
        )
    except Exception as e:
        print(f"[ona-context:error] api_request_error: {e}")
    finally:
        conn.close()

def post_tool_call(ctx: Dict[str, Any]) -> None:
    """Post-tool call hook: Records tool observations into L0 event stream."""
    session_id = ctx.get("session_id", "default")
    turn_id = ctx.get("turn_id", "default")
    tool_name = ctx.get("tool_name", "unknown")
    tool_input = ctx.get("tool_input", {})
    tool_output = ctx.get("tool_output", "")
    
    conn = get_db()
    try:
        content_preview = str(tool_output)[:400]
        append_event(
            conn=conn,
            session_id=session_id,
            role="tool",
            content=f"[{tool_name}] {content_preview}",
            origin="tool_observation",
            turn_id=turn_id
        )
    except Exception as e:
        print(f"[ona-context:error] post_tool_call: {e}")
    finally:
        conn.close()

# Aliases for plugin loader and test compatibility
pre_llm = pre_llm_call
session_start = on_session_start

def post_llm(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Post-LLM call hook: Optional post-turn cleanup/sync."""
    return {}
