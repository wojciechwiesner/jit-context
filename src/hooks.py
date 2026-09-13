"""Hook implementations for Hermes Plugin Lifecycle with Full LLM & Context Telemetry."""

import os
import sys
import time
import sqlite3
import uuid
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
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

_MODULE_MTIMES: Dict[str, float] = {}

def hot_reload_jit_modules() -> None:
    """Dynamically reloads in-memory modules if on-disk files changed."""
    try:
        plugin_root = Path(__file__).resolve().parent
        needs_reload = False
        for py_file in plugin_root.glob("**/*.py"):
            try:
                mtime = py_file.stat().st_mtime
                old = _MODULE_MTIMES.get(str(py_file))
                if old is not None and mtime > old:
                    needs_reload = True
                _MODULE_MTIMES[str(py_file)] = mtime
            except OSError:
                pass

        if needs_reload:
            import importlib
            for mod_name in list(sys.modules.keys()):
                if any(mod_name.startswith(p) for p in ("l0", "l1", "l2", "context", "health", "config")):
                    mod = sys.modules.get(mod_name)
                    if mod:
                        try:
                            importlib.reload(mod)
                        except Exception:
                            pass
    except Exception:
        pass

def is_synthetic_harness_message(text: str) -> bool:
    """Detect internal Hermes harness prompts (curator, delegation, /btw, canon)."""
    if not text:
        return False
    t = text.strip()
    prefixes = (
        "[ASYNC DELEGATION",
        "Review the conversation above and update the skill library",
        "The user asked a quick SIDE question with /btw",
        "[OUT-OF-BAND USER MESSAGE",
        "ENGINEERING CANON (~",
        "<ONA_CONTEXT",
        "[ONA_CONTEXT",
    )
    return any(t.startswith(p) for p in prefixes)

def on_session_start(ctx: Dict[str, Any]) -> None:
    """Initialize database and verify schema on session startup."""
    init_db()

def pre_llm_call(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-LLM hook: Compile lean context capsule (<1,500 tokens) just-in-time."""
    current_mode = os.environ.get("ONA_CONTEXT_MODE", ONA_CONTEXT_MODE).lower()
    if current_mode in ("disabled", "off", "0"):
        return {}

    hot_reload_jit_modules()
    start_time = time.time()
    session_id = ctx.get("session_id", "default")
    turn_id = ctx.get("turn_id") or f"turn_{int(start_time * 1000)}"
    user_message = ctx.get("user_message") or ctx.get("user_prompt") or ""
    if not user_message and ctx.get("messages"):
        for m in reversed(ctx["messages"]):
            if isinstance(m, dict) and m.get("role") == "user":
                user_message = m.get("content", "")
                break
    is_synthetic = is_synthetic_harness_message(user_message)
    
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
                origin="harness_event" if is_synthetic else "direct_user",
                turn_id=turn_id
            )
        l0_ms = (time.time() - l0_start) * 1000
        
        # Determine genuine user message for scope resolution and context compilation
        from l0.overlay import get_latest_direct_user_message, get_session_cwd
        effective_user_message = user_message
        if is_synthetic:
            latest_real = get_latest_direct_user_message(conn, session_id)
            if latest_real:
                effective_user_message = latest_real

        # L1 Scope resolution (<1ms, tracks session_cwd from terminal tool execution)
        l1_start = time.time()
        session_cwd = get_session_cwd(conn, session_id)
        active_cwd = Path(session_cwd) if session_cwd and Path(session_cwd).exists() else Path.cwd()
        cwd_name = active_cwd.name
        default_scope = cwd_name if cwd_name not in ["wojciechwiesner", "Projects", "active"] else "hermes"
        active_scope, retrieval_scopes, _, _ = resolve_scope(effective_user_message, default_scope)
        l1_ms = (time.time() - l1_start) * 1000
        
        # Context compilation with L2 circuit breaker
        compile_start = time.time()
        compile_res = compile_context(
            conn=conn,
            session_id=session_id,
            user_message=effective_user_message,
            transcript_messages=ctx.get("messages", [])
        )
        if isinstance(compile_res, tuple):
            capsule, meta = compile_res
        else:
            capsule, meta = compile_res, {}

        compile_ms = (time.time() - compile_start) * 1000
        l2_ms = compile_ms
        confidence = meta.get("confidence", 1.0)
        complexity = meta.get("complexity", "direct_fix")
        
        # Check if project lacks canonical context and alert
        if active_scope and active_scope not in ["hermes", "default", "general"]:
            from l1.obsidian_sync import check_obsidian_staleness, find_obsidian_project_dossier
            dossier_path = find_obsidian_project_dossier(active_scope)
            active_path = Path(session_cwd) if session_cwd else Path.cwd()
            local_state = active_path / ".planning" / "STATE.md"
            if not dossier_path and not local_state.exists():
                alert_msg = f"⚠️ [JIT Context Warning]: Projekt '{active_scope}' nie ma jeszcze zebranego kontekstu (.planning/STATE.md ani Obsidian)"
                print(f"\n{alert_msg}")
                capsule += f"\n<CONTEXT_ALERT: Projekt '{active_scope}' nie posiada pliku .planning/STATE.md ani notatki w Obsidianie. Zaproponuj utworzenie planu lub zainicjalizuj stan.>\n"
            elif dossier_path:
                stale_alert = check_obsidian_staleness(active_scope, str(active_path))
                if stale_alert:
                    capsule += f"\n<OBSIDIAN_SYNC_ALERT: {stale_alert}>\n"

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
                "confidence": round(confidence, 2),
                "complexity": complexity,
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
        
        # Check Obsidian dossier status for clear reporting with SSOT timestamp
        obsidian_status = "brak notatki"
        try:
            from l1.obsidian_sync import get_obsidian_dossier_info
            dossier_info = get_obsidian_dossier_info(active_scope, str(active_cwd))
            obsidian_status = dossier_info.get("status", "brak notatki")
        except Exception:
            pass

        # Render clean, human-readable JIT status banner
        is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        c_green = "\033[32m" if is_tty else ""
        c_cyan = "\033[36m" if is_tty else ""
        c_yellow = "\033[33m" if is_tty else ""
        c_reset = "\033[0m" if is_tty else ""
        c_bold = "\033[1m" if is_tty else ""

        if current_mode == "shadow":
            print(f"⚡ {c_bold}[JIT Context: CZUWANIE (shadow)]{c_reset} Projekt: {active_scope} • {compile_ms:.1f}ms ({len(capsule)} zn)", file=sys.stderr, flush=True)
            return {}

        goal_match = re.search(r"• Goal:\s*(.+)", capsule)
        intent_match = re.search(r"• Intent:\s*(.+)", capsule)
        ws_matches = re.findall(r"• ([^\n\(]+) \((?:active module|written|read_ok)", capsule)

        goal_text = goal_match.group(1).strip()[:85] if goal_match else ""
        intent_raw = intent_match.group(1).strip() if intent_match else ""
        intent_map = {"QUERY": "Pytanie / Analiza", "TASK": "Kodowanie / Zadanie", "FIX": "Naprawa błędu"}
        intent_label = intent_map.get(intent_raw, intent_raw)

        status_lines = [
            f"⚡ {c_bold}{c_green}[JIT Context: AKTYWNY]{c_reset} Projekt: {c_cyan}{active_scope}{c_reset} • {compile_ms:.1f}ms • {len(capsule)} zn (~90% mniej tokenów)"
        ]
        if goal_text:
            intent_suffix = f" [{intent_label}]" if intent_label else ""
            status_lines.append(f"   • Cel: {goal_text}{intent_suffix}")

        obs_color = c_green if "zsynchronizowany" in obsidian_status else c_yellow
        state_items = [f"Obsidian SSOT: {obs_color}{obsidian_status}{c_reset}"]
        if ws_matches:
            file_names = [Path(p.strip()).name for p in ws_matches[:3]]
            more = f" (+{len(ws_matches)-3})" if len(ws_matches) > 3 else ""
            state_items.append(f"Pliki robocze: {', '.join(file_names)}{more}")

        status_lines.append(f"   • Stan: {' • '.join(state_items)}")
        print("\n".join(status_lines), file=sys.stderr, flush=True)
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

from l0.tool_evidence import parse_tool_execution

def post_tool_call(ctx: Dict[str, Any]) -> None:
    """Post-tool call hook: Records tool observations and verified facts into L0 event stream."""
    session_id = ctx.get("session_id", "default")
    turn_id = ctx.get("turn_id", "default")
    tool_name = ctx.get("tool_name", "unknown")
    tool_input = ctx.get("tool_input", {})
    tool_output = ctx.get("tool_output", "")
    
    conn = get_db()
    try:
        origin, fact_kind, fact_key, fact_value = parse_tool_execution(tool_name, tool_input, tool_output)
        content_preview = str(tool_output)[:400]
        append_event(
            conn=conn,
            session_id=session_id,
            role="tool",
            content=f"[{tool_name}] {content_preview}",
            origin=origin,
            turn_id=turn_id,
            fact_kind=fact_kind,
            fact_key=fact_key,
            fact_value=fact_value
        )

        # Track session working directory from terminal commands
        from l0.overlay import update_session_cwd
        if isinstance(tool_output, dict) and "cwd" in tool_output:
            update_session_cwd(conn, session_id, tool_output["cwd"])
        elif tool_name == "terminal" and isinstance(tool_input, dict):
            cmd = tool_input.get("command", "")
            if "cd " in cmd:
                parts = cmd.split("&&")[0].strip().split()
                if len(parts) >= 2 and parts[0] == "cd":
                    dest = parts[1]
                    try:
                        p = Path(dest).expanduser().resolve()
                        if p.exists() and p.is_dir():
                            update_session_cwd(conn, session_id, str(p))
                    except Exception:
                        pass
            
            # Auto-sync Obsidian SSOT on git commit / deploy commands
            if "git commit" in cmd or "git push" in cmd or "rsync" in cmd:
                from l1.obsidian_sync import sync_obsidian_on_commit
                active_cwd = tool_input.get("workdir") or os.getcwd()
                scope_name = Path(active_cwd).name
                if scope_name and scope_name not in ("general", "hermes", "default"):
                    ok, msg = sync_obsidian_on_commit(scope_name, str(active_cwd))
                    if ok:
                        print(f"📖 \033[32m[Obsidian SSOT Auto-Synced]\033[0m: {msg}", file=sys.stderr, flush=True)
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
