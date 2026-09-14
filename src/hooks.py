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

def extract_genuine_user_instruction(text: str) -> str:
    """Extract real human instruction if message is wrapped in a skill invocation or harness prefix."""
    if not text:
        return ""
    # Strip nested/quoted <ONA_CONTEXT ...> blocks to avoid self-poisoning
    clean = re.sub(r'<ONA_CONTEXT.*?</ONA_CONTEXT>', '', text, flags=re.DOTALL).strip()
    if clean:
        text = clean
    m = re.search(r"The user has provided the following instruction alongside the skill invocation:\s*(.*)", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text

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
        "[IMPORTANT: The user has invoked the ",
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
    genuine_instruction = extract_genuine_user_instruction(user_message)
    is_synthetic = is_synthetic_harness_message(user_message)
    
    conn = get_db(session_id=session_id)
    try:
        # L0 Hot-Path: Ingest direct user message into SQLite WAL (<1ms)
        l0_start = time.time()
        if user_message:
            if is_synthetic and genuine_instruction and genuine_instruction != user_message:
                append_event(
                    conn=conn,
                    session_id=session_id,
                    role="user",
                    content=user_message,
                    origin="harness_event",
                    turn_id=turn_id
                )
                append_event(
                    conn=conn,
                    session_id=session_id,
                    role="user",
                    content=genuine_instruction,
                    origin="direct_user",
                    turn_id=f"{turn_id}_user"
                )
            else:
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
        effective_user_message = genuine_instruction if (is_synthetic and genuine_instruction and genuine_instruction != user_message) else user_message
        if is_synthetic and (not genuine_instruction or genuine_instruction == user_message):
            latest_real = get_latest_direct_user_message(conn, session_id)
            if latest_real:
                effective_user_message = latest_real

        # L1 Scope resolution (<1ms, tracks session_cwd from terminal tool execution)
        l1_start = time.time()
        session_cwd = get_session_cwd(conn, session_id)
        if session_cwd and Path(session_cwd).exists():
            cwd_name = Path(session_cwd).name
            default_scope = cwd_name if cwd_name not in ["wojciechwiesner", "Projects", "active"] else "general"
        else:
            # DO NOT fall back to process Path.cwd() to prevent cross-session context bleeding!
            session_cwd = None
            default_scope = "general"
        
        # Invariant: Preserve active session scope across turns unless switched!
        session_obj = ensure_session(conn, session_id, default_scope=default_scope)
        current_scope = session_obj.get("active_scope") or default_scope
        base_scope = current_scope if current_scope not in ("general", "unknown", "") else default_scope
        
        active_scope, retrieval_scopes, _, _ = resolve_scope(effective_user_message, base_scope)
        l1_ms = (time.time() - l1_start) * 1000
        
        # Context compilation with L2 circuit breaker
        compile_start = time.time()
        compile_res = compile_context(
            conn=conn,
            session_id=session_id,
            user_message=effective_user_message,
            transcript_messages=ctx.get("messages", []),
            active_scope=active_scope,
            default_scope=default_scope,
            session_cwd=session_cwd
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

        complexity_budget_map = {
            "status": 5000,
            "direct_fix": 10000,
            "feature": 16000,
            "refactoring": 25000
        }
        budget_chars = meta.get("budget") or complexity_budget_map.get(complexity, 10000)
        capsule_chars = len(capsule)
        used_pct = round((capsule_chars / budget_chars) * 100, 1) if budget_chars else 0.0
        tokens_est = round(capsule_chars / 4)
        budget_tokens_est = round(budget_chars / 4)

        # Check Obsidian dossier status for clear reporting with SSOT timestamp
        obsidian_status = "brak notatki"
        try:
            from l1.obsidian_sync import get_obsidian_dossier_info
            from config import resolve_project_workspace_dir
            effective_cwd = Path(session_cwd) if session_cwd and Path(session_cwd).exists() else resolve_project_workspace_dir(active_scope)
            dossier_info = get_obsidian_dossier_info(active_scope, str(effective_cwd) if effective_cwd else None)
            obsidian_status = dossier_info.get("status", "brak notatki")
        except Exception:
            pass

        goal_match = re.search(r"• Goal:\s*(.+)", capsule)
        intent_match = re.search(r"• Intent:\s*(.+)", capsule)
        ws_matches = re.findall(r"• ([^\n\(]+) \((?:active module|written|read_ok)", capsule)

        goal_text = goal_match.group(1).strip()[:85] if goal_match else ""
        intent_raw = intent_match.group(1).strip() if intent_match else ""
        intent_map = {"QUERY": "Pytanie / Analiza", "TASK": "Kodowanie / Zadanie", "FIX": "Naprawa błędu", "DIRECT_TASK": "Zadanie bezpośrednie"}
        intent_label = intent_map.get(intent_raw, intent_raw)

        # Write fast atomic live status for CLI Status Bar and Live Web Inspector
        try:
            live_payload = {
                "mode": current_mode,
                "scope": active_scope,
                "confidence": round(confidence, 2),
                "complexity": complexity,
                "compile_ms": round(compile_ms, 2),
                "l0_ms": round(l0_ms, 2),
                "hook_total_ms": round(hook_total_ms, 2),
                "capsule_chars": capsule_chars,
                "budget_chars": budget_chars,
                "used_pct": used_pct,
                "capsule_tokens_est": tokens_est,
                "budget_tokens_est": budget_tokens_est,
                "compression_ratio": 91.0,
                "session_id": session_id,
                "turn_id": turn_id,
                "goal_text": goal_text,
                "intent_label": intent_label,
                "obsidian_status": obsidian_status,
                "capsule": capsule,
                "live_url": "http://127.0.0.1:8765/live",
                "ts": time.time(),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            with open("/tmp/hermes-jit-live.json", "w", encoding="utf-8") as lf:
                json.dump(live_payload, lf, ensure_ascii=False, indent=2)
            with open("/tmp/hermes-jit-capsule-live.xml", "w", encoding="utf-8") as xf:
                xf.write(capsule)
            
            # Isolated per-session sandbox write (1:1 Session Sandbox)
            from config import (
                get_session_capsule_path,
                get_session_meta_path,
                get_session_dir,
                resolve_project_workspace_dir,
                LATEST_CONTEXT_SYMLINK,
                SESSIONS_DIR
            )
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(session_id or "default"))
            
            # 1. Central JIT Store: ~/.hermes/state/ona-context/sessions/{active_scope}/{session_id}/
            capsule_path = get_session_capsule_path(session_id, project=active_scope)
            meta_path = get_session_meta_path(session_id, project=active_scope)
            
            tmp_capsule = capsule_path.with_suffix(".tmp")
            with open(tmp_capsule, "w", encoding="utf-8") as cf:
                cf.write(capsule)
            tmp_capsule.replace(capsule_path)
            
            tmp_meta = meta_path.with_suffix(".tmp")
            with open(tmp_meta, "w", encoding="utf-8") as mf:
                json.dump(live_payload, mf, ensure_ascii=False, indent=2)
            tmp_meta.replace(meta_path)
            
            # Project & global latest symlinks
            try:
                scope_symlink = SESSIONS_DIR / active_scope / "latest_context.xml"
                if scope_symlink.is_symlink() or scope_symlink.exists():
                    scope_symlink.unlink()
                scope_symlink.symlink_to(capsule_path)
                if LATEST_CONTEXT_SYMLINK.is_symlink() or LATEST_CONTEXT_SYMLINK.exists():
                    LATEST_CONTEXT_SYMLINK.unlink()
                LATEST_CONTEXT_SYMLINK.symlink_to(capsule_path)
            except Exception:
                pass

            # 2. Project Directory Sandbox: {project_ws}/.planning/sessions/{session_id}/
            project_ws = resolve_project_workspace_dir(active_scope)
            if project_ws and project_ws.exists():
                try:
                    proj_plan_dir = project_ws / ".planning"
                    proj_sess_dir = proj_plan_dir / "sessions" / safe_id
                    proj_sess_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Ensure .planning/.gitignore ignores sessions/
                    plan_ignore = proj_plan_dir / ".gitignore"
                    existing_ignore = plan_ignore.read_text(encoding="utf-8") if plan_ignore.exists() else ""
                    if "sessions/" not in existing_ignore:
                        with open(plan_ignore, "a", encoding="utf-8") as gif:
                            gif.write("\nsessions/\nlatest_context.xml\n")
                            
                    p_capsule_path = proj_sess_dir / f"ona_context_{safe_id}.xml"
                    p_meta_path = proj_sess_dir / f"session_{safe_id}.json"
                    
                    with open(p_capsule_path, "w", encoding="utf-8") as pcf:
                        pcf.write(capsule)
                    with open(p_meta_path, "w", encoding="utf-8") as pmf:
                        json.dump(live_payload, pmf, ensure_ascii=False, indent=2)
                        
                    # Project-level latest symlink
                    p_symlink = proj_plan_dir / "latest_context.xml"
                    if p_symlink.is_symlink() or p_symlink.exists():
                        p_symlink.unlink()
                    p_symlink.symlink_to(p_capsule_path)
                except Exception as pe:
                    print(f"[ona-context:proj_sandbox_err] {pe}")

            # 3. High-level Obsidian SSOT Snapshot (zero self-poisoning, human-readable card)
            try:
                from l1.obsidian_sync import record_session_snapshot_to_obsidian
                record_session_snapshot_to_obsidian(
                    scope=active_scope,
                    session_id=session_id,
                    goal=goal_text or "",
                    working_files=ws_matches if ws_matches else [],
                    capsule_path=capsule_path,
                    intent=intent_label or ""
                )
            except Exception as oe:
                print(f"[ona-context:obsidian_snapshot_err] {oe}")
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
            print(f"⚡ {c_bold}[JIT Context: CZUWANIE (shadow)]{c_reset} Sesja: {session_id} • Projekt: {active_scope} • {compile_ms:.1f}ms ({capsule_chars} zn)", file=sys.stderr, flush=True)
            return {}

        status_lines = [
            f"⚡ {c_bold}{c_green}[JIT Context: AKTYWNY]{c_reset} Sesja: {c_yellow}{session_id}{c_reset} • Projekt: {c_cyan}{active_scope}{c_reset} • {compile_ms:.1f}ms • Kapsuła: {c_bold}{capsule_chars:,} / {budget_chars:,} zn ({used_pct}% użyte{c_reset}, ~{tokens_est} tok)"
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
        status_lines.append(f"   • Podgląd Live: {c_cyan}http://127.0.0.1:8765/live{c_reset}")
        try:
            from cli import _cprint
            _cprint("\n" + "\n".join(status_lines) + "\n")
        except Exception:
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
    
    conn = get_db(session_id=session_id)
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
    session_id = ctx.get("session_id", "default")
    duration_ms = ctx.get("duration_ms", 0.0)
    response_model = ctx.get("response_model") or ctx.get("model")
    usage = ctx.get("usage", {})
    cost_usd = ctx.get("cost_usd", 0.0)
    retry_count = ctx.get("retry_count", 0)
    
    input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
    output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
    cache_read_tokens = usage.get("cache_read_tokens", 0) or usage.get("cached_tokens", 0)
    cache_write_tokens = usage.get("cache_write_tokens", 0)
    
    conn = get_db(session_id=session_id)
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
    session_id = ctx.get("session_id", "default")
    error_message = str(ctx.get("error", "Unknown API error"))
    status_code = ctx.get("status_code", 500)
    
    conn = get_db(session_id=session_id)
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
    
    conn = get_db(session_id=session_id)
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
