"""
JIT-Context Local Edge Worker:
Autonomous bugfixing and code repair using local edge models (LFM 2.5 2.6B / Qwen)
powered by JIT Context Capsule and on-device tool loop (Metal M2 Pro / Apple Silicon).
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search file contents by keyword or regex across the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search term or regex"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read lines from a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "offset": {"type": "integer", "description": "Start line (1-based)"},
                    "limit": {"type": "integer", "description": "Number of lines to read"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patch",
            "description": "Apply a surgical search-and-replace edit to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "old_string": {"type": "string", "description": "Exact text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the test suite to verify whether the fix works",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Optional specific test command"}
                }
            }
        }
    }
]

def build_workspace_capsule(workspace_dir: Path, goal: str, use_jev: bool = False) -> Tuple[str, Dict[str, Any]]:
    """Builds a lightweight JIT context capsule for a workspace and goal."""
    candidates = []
    q_tokens = set(w.lower() for w in goal.split() if len(w) > 2)
    
    ignore_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".planning", ".hermes", "dist", "build"}
    for p in workspace_dir.rglob("*"):
        if p.is_file() and not any(part in ignore_dirs for part in p.parts):
            if p.suffix in {".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go"}:
                try:
                    rel_p = str(p.relative_to(workspace_dir))
                    content = p.read_text(errors="ignore")[:350].replace("\n", " ")
                    score = sum(1 for tok in q_tokens if tok in rel_p.lower() or tok in content.lower())
                    candidates.append({"key": rel_p, "value": f"{rel_p}: {content}", "score": score, "path": p})
                except Exception:
                    pass

    candidates.sort(key=lambda x: -x["score"])
    top_candidates = candidates[:8]

    jev_scores: Dict[str, float] = {}
    if use_jev and top_candidates:
        try:
            from cognitive.jev_engine import get_jev_scorer
            scorer = get_jev_scorer()
            jev_input = [{"key": c["key"], "value": c["value"]} for c in top_candidates]
            res = scorer.score_remote_detailed(goal, jev_input)
            if res.get("remote_call_success"):
                jev_scores = res.get("scores", {})
                top_candidates.sort(key=lambda x: -jev_scores.get(x["key"], 0.0))
        except Exception:
            pass

    top_file = top_candidates[0]["key"] if top_candidates else ""
    top_path = workspace_dir / top_file if top_file else None
    working_set_lines = ""
    if top_path and top_path.exists():
        try:
            lines = top_path.read_text().splitlines()[:60]
            working_set_lines = "\n".join(f"{i+1:3d}| {l}" for i, l in enumerate(lines))
        except Exception:
            pass

    pointers = []
    for c in top_candidates[:4]:
        p_str = f"@file:{c['key']}"
        if c['key'] in jev_scores:
            p_str += f" (p={jev_scores[c['key']]:.2f})"
        pointers.append(p_str)

    capsule = f"""<ONA_CONTEXT scope="workspace" epoch="1" confidence="1.00" complexity="feature">
  [DEV RUNTIME & AST WORKING SET]
    • Target Candidate: {top_file or 'None'}
    • Candidate Ranking: {', '.join(pointers)}
    • Working Set (Top Candidate Lines):
{working_set_lines}
  [ACTIVE INVARIANTS]
    • ZERO FAKE: Every code change must be verified directly via test execution.
    • RETURN FORMAT: Invoke tools (search_files, read_file, patch, run_tests) to solve the task.
</ONA_CONTEXT>"""
    return capsule, {"top_file": top_file, "candidates": [c["key"] for c in top_candidates]}

def call_ollama_v1(messages: List[Dict[str, Any]], model: str) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "options": {"temperature": 0.0}
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama connection failed on http://127.0.0.1:11434: {e}. Is Ollama running?")
    lat = time.time() - t0
    
    msg = data.get("message", {})
    raw_tc = msg.get("tool_calls", [])
    normalized_tool_calls = []
    for tc in raw_tc:
        fn = tc.get("function", {})
        normalized_tool_calls.append({
            "id": tc.get("id", "call_1"),
            "function": {
                "name": fn.get("name"),
                "arguments": fn.get("arguments", {})
            }
        })
    
    return {
        "message": msg,
        "content": msg.get("content", ""),
        "thinking": msg.get("thinking", ""),
        "tool_calls": normalized_tool_calls,
        "latency_s": lat,
        "tokens": data.get("eval_count", 0)
    }

def run_local_worker(
    task: str,
    workspace_dir: Path,
    test_cmd: Optional[str] = None,
    model: str = "lfm2.5:2.6b-64k",
    use_jev: bool = False,
    max_turns: int = 6,
    verbose: bool = True
) -> Dict[str, Any]:
    """Runs autonomous agent loop using local edge model and JIT capsule."""
    workspace_dir = workspace_dir.resolve()
    capsule, evidence = build_workspace_capsule(workspace_dir, task, use_jev=use_jev)
    
    initial_prompt = (
        f"{capsule}\n\n"
        f"Problem Statement:\n{task}\n\n"
        "You are an autonomous SWE agent. Fix the bug cleanly using the provided tools. "
        "Inspect, patch, and verify with run_tests."
    )

    messages = [{"role": "user", "content": initial_prompt}]
    
    turns_taken = 0
    total_tokens = 0
    patches_applied = 0
    passed = False
    start_time = time.time()
    turn_log = []

    if verbose:
        print(f"🚀 [JIT Edge Worker] Initialized for: '{task[:60]}...'")
        print(f"🧠 [Model]: {model} (Local Metal/Ollama) | Workspace: {workspace_dir}")
        print(f"📦 [JIT Capsule Target]: {evidence.get('top_file', 'None')}")

    for turn in range(1, max_turns + 1):
        turns_taken = turn
        try:
            resp = call_ollama_v1(messages, model=model)
        except Exception as e:
            if verbose:
                print(f"❌ Error calling local model: {e}")
            return {
                "success": False,
                "error": str(e),
                "turns": turn,
                "patches_applied": patches_applied,
                "wall_time_s": round(time.time() - start_time, 2)
            }
        
        total_tokens += resp["tokens"]
        msg = resp["message"]
        tool_calls = resp["tool_calls"]

        if not tool_calls:
            if verbose:
                print(f"  [Turn {turn}] No tool call, text: {resp['content'][:120]}")
            messages.append({"role": "assistant", "content": resp["content"] or "I will continue."})
            messages.append({"role": "user", "content": "Please invoke a tool to complete the task: read_file, patch, or run_tests."})
            continue

        messages.append(msg)
        executed_tools = []

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            tool_output = ""
            action_desc = f"{name}({args})"
            if verbose:
                print(f"  ⚡ [Turn {turn}] {name}({args})")

            if name == "search_files":
                pattern = args.get("pattern", "")
                matches = []
                for p in workspace_dir.rglob("*"):
                    if p.is_file() and p.suffix in {".py", ".ts", ".js", ".json"}:
                        try:
                            for idx, line in enumerate(p.read_text().splitlines(), 1):
                                if pattern.lower() in line.lower():
                                    rel = p.relative_to(workspace_dir)
                                    matches.append(f"{rel}:{idx}: {line.strip()[:80]}")
                        except Exception:
                            pass
                tool_output = "\n".join(matches[:15]) if matches else f"No matches found for '{pattern}'."

            elif name == "read_file":
                rel_path = args.get("path", "")
                target_p = workspace_dir / rel_path
                if not target_p.exists() or target_p.is_dir():
                    tool_output = f"Error: Path '{rel_path}' does not exist."
                else:
                    lines = target_p.read_text().splitlines()
                    off = max(1, args.get("offset", 1))
                    lim = args.get("limit", 40)
                    tool_output = "\n".join(f"{off + idx:3d}| {l}" for idx, l in enumerate(lines[off-1:off-1+lim]))

            elif name == "patch":
                rel_path = args.get("path", "")
                target_p = workspace_dir / rel_path
                if not target_p.exists() or target_p.is_dir():
                    tool_output = f"Error: Path '{rel_path}' does not exist."
                else:
                    old_s = args.get("old_string", "")
                    new_s = args.get("new_string", "")
                    content = target_p.read_text()
                    if old_s not in content:
                        tool_output = f"Error: old_string not found in '{rel_path}'."
                    else:
                        target_p.write_text(content.replace(old_s, new_s, 1))
                        patches_applied += 1
                        tool_output = f"Success: Patch applied cleanly to '{rel_path}'."
                        if verbose:
                            print(f"     ✅ Patched: {rel_path}")

            elif name == "run_tests":
                # Enforce configured test_cmd so agent cannot bypass test suite
                cmd = test_cmd or args.get("cmd")
                if not cmd:
                    if (workspace_dir / "pytest.ini").exists() or (workspace_dir / "tests").exists() or any(workspace_dir.glob("test_*.py")):
                        cmd = "python3 -m pytest -q"
                    elif (workspace_dir / "package.json").exists():
                        cmd = "npm test"
                    else:
                        cmd = "pytest -q"
                
                import shlex
                try:
                    args_list = shlex.split(cmd)
                    proc = subprocess.run(args_list, shell=False, cwd=workspace_dir, capture_output=True, text=True, timeout=30)
                    if proc.returncode == 0:
                        passed = True
                        tool_output = f"PASS: Tests passed with exit code 0!\n{proc.stdout[-300:]}"
                        if verbose:
                            print(f"     🎉 TESTS PASSED: {cmd}")
                    else:
                        tool_output = f"FAIL (exit {proc.returncode}):\n{proc.stdout[-300:]}\n{proc.stderr[-300:]}"
                except Exception as ex:
                    tool_output = f"Test execution error: {ex}"

            else:
                tool_output = f"Unknown tool '{name}'."

            turn_log.append({"turn": turn, "action": action_desc, "output": tool_output[:200]})
            executed_tools.append(f"Tool Result [{name}]:\n{tool_output}")

        if executed_tools:
            messages.append({"role": "user", "content": "\n\n".join(executed_tools)})

        if passed:
            break

    wall_time = round(time.time() - start_time, 2)
    return {
        "success": passed,
        "turns": turns_taken,
        "patches_applied": patches_applied,
        "wall_time_s": wall_time,
        "tokens": total_tokens,
        "log": turn_log
    }
