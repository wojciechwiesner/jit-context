"""Slot 30: per-turn autochecker (monologue_end).

After every turn / monologue it audits the chain:
  project goal -> user prompt -> spec -> capsule -> output
and evaluates harness efficiency (tool errors, duplicate calls, re-reads, turn length).

Findings are appended to <data dir>/audits/<context id>.jsonl and merged
into <data dir>/audits/mods.json + jitjevmods.md.

Deterministic only: no LLM call, no network.
I6-hardened: never raises into Agent Zero, silent degradation on failure.
Disabled switch: env JIT_A0_TURN_AUDIT=0.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from helpers.extension import Extension
except ImportError:
    class Extension(object):  # type: ignore
        def __init__(self, agent=None, **kw):
            self.agent = agent

try:
    from helpers import plugins
except ImportError:
    plugins = None  # type: ignore

try:
    from usr.plugins.jit_context.helpers import turn_audit_rules, jitjevmods
except Exception:
    try:
        from helpers import turn_audit_rules, jitjevmods
    except Exception:
        import importlib.util

        def _import_helper(mod_name: str, file_name: str):
            for base in (
                os.environ.get("JIT_CONTEXT_PLUGIN_DIR") or "",
                "/a0/usr/plugins/jit_context",
                _ROOT,
            ):
                if not base:
                    continue
                p = os.path.join(base, "helpers", file_name)
                if os.path.isfile(p):
                    spec = importlib.util.spec_from_file_location(mod_name, p)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        return mod
            return None

        turn_audit_rules = _import_helper("turn_audit_rules", "turn_audit_rules.py")
        jitjevmods = _import_helper("jitjevmods", "jitjevmods.py")

logger = logging.getLogger("jit_turn_audit")


def _persist(audit_dir: Path, context_id: str, report: Dict[str, Any]) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = audit_dir / f"{context_id}.jsonl"
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")

    findings = report.get("findings", [])
    if findings and jitjevmods:
        source = {
            "context_id": context_id,
            "session": context_id,
            "turn": str(report.get("turn", "")),
        }
        jitjevmods.record_mods(
            findings,
            source=source,
            mods_json=audit_dir / "mods.json",
            mods_md=audit_dir / "jitjevmods.md",
        )


class JITTurnAuditExtension(Extension):
    async def execute(self, **kwargs):
        try:
            # 1. Check disabled switch (env var or plugin config)
            if os.environ.get("JIT_A0_TURN_AUDIT", "1") == "0":
                return

            if plugins and self.agent:
                try:
                    cfg = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
                    if cfg.get("mode") == "disabled" or cfg.get("turn_audit_enabled", True) is False:
                        return
                except Exception:
                    pass

            if not turn_audit_rules:
                return

            loop_data = kwargs.get("loop_data")

            # 2. Identify context / session id
            ctx = getattr(self.agent, "context", None) if self.agent else None
            cid = getattr(ctx, "id", None)
            if not cid and isinstance(loop_data, dict):
                cid = loop_data.get("session_id") or loop_data.get("context_id")
            if not cid and loop_data is not None:
                cid = getattr(loop_data, "session_id", None) or getattr(loop_data, "context_id", None)
            context_id = str(cid or "default")

            # 3. Collect history items from agent.history or loop_data
            history_items: list = []
            if self.agent is not None:
                hist_obj = getattr(self.agent, "history", None)
                if hist_obj is not None:
                    if hasattr(hist_obj, "output") and callable(hist_obj.output):
                        try:
                            out = hist_obj.output()
                            if out:
                                history_items = list(out)
                        except Exception:
                            pass
                    if not history_items:
                        current = getattr(hist_obj, "current", None)
                        if current and hasattr(current, "messages"):
                            try:
                                msgs = getattr(current, "messages", None)
                                if isinstance(msgs, (list, tuple)):
                                    history_items = list(msgs)
                            except Exception:
                                pass

            if not history_items:
                if isinstance(loop_data, dict):
                    history_items = list(loop_data.get("history") or loop_data.get("history_output") or [])
                elif loop_data is not None:
                    ho = getattr(loop_data, "history_output", None)
                    if ho:
                        history_items = list(ho)

            # 4. Extract user message (prompt)
            prompt = ""
            um = getattr(loop_data, "user_message", None) if loop_data is not None else None
            if um is None and self.agent is not None:
                um = getattr(self.agent, "last_user_message", None)

            if um is not None:
                if isinstance(um, dict):
                    c = um.get("content")
                    if isinstance(c, str):
                        prompt = c
                elif hasattr(um, "content"):
                    c = getattr(um, "content")
                    if isinstance(c, str):
                        prompt = c

            if not prompt and history_items:
                for m in reversed(history_items):
                    is_ai = getattr(m, "ai", None) if not isinstance(m, dict) else m.get("ai")
                    role = getattr(m, "role", None) if not isinstance(m, dict) else m.get("role")
                    content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
                    if is_ai is False or role == "user":
                        if isinstance(content, str) and content.strip():
                            if not re.match(r"^\s*(\[OUT-OF-BAND|\[IMPORTANT:|<system-reminder>|\[ASYNC)", content):
                                prompt = content
                                break

            # 5. Extract final response (output)
            output = ""
            if loop_data is not None:
                lr = getattr(loop_data, "last_response", None)
                if isinstance(lr, str) and lr.strip():
                    output = lr

            if not output and history_items:
                for m in reversed(history_items):
                    is_ai = getattr(m, "ai", None) if not isinstance(m, dict) else m.get("ai")
                    role = getattr(m, "role", None) if not isinstance(m, dict) else m.get("role")
                    content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
                    if is_ai is True or role == "assistant":
                        if isinstance(content, str) and content.strip():
                            output = content
                            break

            # 6. Extract tool calls
            tools: list[Dict[str, Any]] = []
            if isinstance(loop_data, dict) and ("tools" in loop_data or "tool_calls" in loop_data):
                raw_tools = loop_data.get("tools") or loop_data.get("tool_calls") or []
                for t in raw_tools:
                    if isinstance(t, dict):
                        name = str(t.get("name") or t.get("tool_name") or "")
                        args = t.get("args") if "args" in t else t.get("tool_args", {})
                        res = str(t.get("result") or t.get("tool_result") or "")
                        err = bool(t.get("error") or turn_audit_rules.is_error(res))
                        tools.append({
                            "name": name,
                            "args": args if isinstance(args, dict) else {},
                            "result": res,
                            "error": err,
                        })

            if not tools and history_items:
                pending_calls: list[Dict[str, Any]] = []
                for m in history_items:
                    is_ai = getattr(m, "ai", None) if not isinstance(m, dict) else m.get("ai")
                    role = getattr(m, "role", None) if not isinstance(m, dict) else m.get("role")
                    content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
                    metadata = getattr(m, "metadata", None) if not isinstance(m, dict) else m.get("metadata")

                    if is_ai is True or role == "assistant":
                        # Check LiteLLM function calls in metadata
                        if isinstance(metadata, dict):
                            responses_data = metadata.get("responses") or {}
                            for item in responses_data.get("output_items", []):
                                if isinstance(item, dict) and item.get("type") == "function_call":
                                    data = item.get("data", {})
                                    pending_calls.append({
                                        "name": data.get("name", ""),
                                        "args": data.get("arguments", {}),
                                        "call_id": data.get("call_id") or data.get("id"),
                                    })
                        # Check tool_calls field (Hermes format)
                        tcs = getattr(m, "tool_calls", None) if not isinstance(m, dict) else m.get("tool_calls")
                        if isinstance(tcs, list):
                            for tc in tcs:
                                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                                name = fn.get("name", "")
                                raw_args = fn.get("arguments", {})
                                if isinstance(raw_args, str):
                                    try:
                                        args = json.loads(raw_args)
                                    except Exception:
                                        args = {"_raw": raw_args}
                                else:
                                    args = raw_args or {}
                                pending_calls.append({
                                    "name": name,
                                    "args": args,
                                    "call_id": tc.get("id"),
                                })
                        # Check JSON in content
                        if isinstance(content, str):
                            try:
                                parsed = json.loads(content)
                                if isinstance(parsed, dict) and ("tool_name" in parsed or "tool" in parsed):
                                    name = parsed.get("tool_name") or parsed.get("tool")
                                    args = parsed.get("tool_args") or parsed.get("arguments") or parsed.get("args") or {}
                                    pending_calls.append({"name": name, "args": args if isinstance(args, dict) else {}})
                            except Exception:
                                pass

                    is_tool = role == "tool" or (is_ai is False and isinstance(content, dict) and ("tool_name" in content or "tool_result" in content))
                    if is_tool:
                        if isinstance(content, dict):
                            name = content.get("tool_name") or content.get("name") or ""
                            res = content.get("tool_result") or content.get("result") or ""
                            args = content.get("tool_args") or content.get("args") or {}
                            if not args and pending_calls:
                                idx = next((i for i, c in enumerate(pending_calls) if c.get("name") == name), 0)
                                popped = pending_calls.pop(idx)
                                args = popped.get("args", {})
                                if not name:
                                    name = popped.get("name", "")
                            err = bool(content.get("error") or turn_audit_rules.is_error(str(res)))
                            tools.append({
                                "name": name,
                                "args": args if isinstance(args, dict) else {},
                                "result": str(res),
                                "error": err,
                            })
                        elif role == "tool" or pending_calls:
                            call_id = getattr(m, "tool_call_id", None) if not isinstance(m, dict) else m.get("tool_call_id")
                            popped = None
                            if call_id:
                                popped = next((c for c in pending_calls if c.get("call_id") == call_id), None)
                                if popped:
                                    pending_calls.remove(popped)
                            if popped is None and pending_calls:
                                popped = pending_calls.pop(0)
                            name = popped.get("name", "unknown") if popped else "unknown"
                            args = popped.get("args", {}) if popped else {}
                            res = str(content)
                            err = turn_audit_rules.is_error(res) or bool(getattr(m, "error", False) if not isinstance(m, dict) else m.get("error", False))
                            tools.append({
                                "name": name,
                                "args": args if isinstance(args, dict) else {},
                                "result": res,
                                "error": err,
                            })

                for p in pending_calls:
                    res = str(p.get("result", ""))
                    err = bool(p.get("error") or turn_audit_rules.is_error(res))
                    tools.append({
                        "name": p.get("name", ""),
                        "args": p.get("args", {}),
                        "result": res,
                        "error": err,
                    })

            # 7. Extract capsule
            capsule = None
            if loop_data is not None:
                system_prompts = getattr(loop_data, "system", None)
                if isinstance(system_prompts, list):
                    for part in system_prompts:
                        if isinstance(part, str) and ("<jit_capsule>" in part or "<ONA_CONTEXT" in part):
                            capsule = part
                            break

            if capsule is None and self.agent is not None:
                try:
                    from usr.plugins.jit_context.helpers.runtime import get_runtime
                    rt = get_runtime()
                    capsule = rt.compile_capsule(agent=self.agent)
                except Exception:
                    try:
                        from helpers.runtime import get_runtime
                        rt = get_runtime()
                        capsule = rt.compile_capsule(agent=self.agent)
                    except Exception:
                        capsule = None

            # 8. Extract duration
            duration_s = 0.0
            if loop_data is not None:
                d = getattr(loop_data, "duration_s", None)
                if d is not None:
                    try:
                        duration_s = float(d)
                    except Exception:
                        pass
            if duration_s == 0.0 and isinstance(loop_data, dict):
                duration_s = float(loop_data.get("duration_s") or loop_data.get("duration") or 0.0)

            # 9. Build record and run audit
            turn_id = f"turn_{int(time.time() * 1000)}"
            record = {
                "session_id": context_id,
                "context_id": context_id,
                "turn_id": turn_id,
                "prompt": prompt,
                "output": output,
                "tools": tools,
                "capsule": capsule,
                "duration_s": duration_s,
            }
            report = turn_audit_rules.audit_turn(record)

            # 10. Persist audit line and update ledger off the event loop
            audit_dir_env = os.environ.get("JIT_AUDIT_DIR")
            if audit_dir_env:
                audit_dir = Path(audit_dir_env)
            else:
                data_dir_env = os.environ.get("JIT_CONTEXT_DATA_DIR")
                if data_dir_env:
                    audit_dir = Path(data_dir_env) / "audits"
                else:
                    plugin_dir = os.environ.get("JIT_CONTEXT_PLUGIN_DIR") or _ROOT
                    audit_dir = Path(plugin_dir) / "data" / "audits"

            await asyncio.to_thread(_persist, audit_dir, context_id, report)

        except Exception as e:
            logger.warning("Turn audit failed: %s", e)
            return
