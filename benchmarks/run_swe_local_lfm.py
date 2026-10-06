#!/usr/bin/env python3
"""
Benchmark: LiquidAI LFM 2.5 (2.6B-64k) on SWE-Bench Tasks:
1. bez_jit (Raw Baseline - Discovery & Read loops)
2. jit_bez_jev (JIT Capsule with Heuristic Token Ranking)
3. jit_z_jev (JIT Capsule with Live JEV Probabilistic Ranking)
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path("/Users/wojciechwiesner/Projects/active/jit-context")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from benchmarks.run_swe_10_battle import TASKS, setup_task_repo, build_jit_capsule, verify_baseline_failure

MODEL_NAME = "lfm2.5:2.6b-64k"

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
                "properties": {}
            }
        }
    }
]

def call_lfm(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "tools": TOOLS,
        "temperature": 0.0
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"\n[OLLAMA HTTP ERROR {e.code}]: {err_body}")
        raise
    lat = time.time() - t0
    
    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})
    usage = data.get("usage", {})
    
    return {
        "message": msg,
        "content": msg.get("content", ""),
        "thinking": msg.get("reasoning", ""),
        "tool_calls": msg.get("tool_calls", []),
        "latency_s": lat,
        "eval_count": usage.get("completion_tokens", 0),
        "prompt_eval_count": usage.get("prompt_tokens", 0)
    }

def run_agentic_task_lfm(task: Dict[str, Any], mode: str, max_turns: int = 7) -> Dict[str, Any]:
    task_dir = Path(f"/tmp/swe_lfm_{task['id']}_{mode}")
    setup_task_repo(task_dir, task)

    # 1. Baseline verification: tests must fail initially
    baseline_fails = verify_baseline_failure(task_dir, task["test_file"])
    if not baseline_fails:
        return {"error": "Baseline failed to reproduce failure", "passed": False}

    # 2. Context setup based on mode
    evidence = {}
    if mode == "bez_jit":
        initial_user_msg = (
            f"Problem Statement:\n{task['title']}\n{task['description']}\n\n"
            "You are an autonomous SWE agent. Fix the bug by inspecting the repository, finding the target file, "
            "applying a patch, and running tests. Use the provided tools."
        )
    elif mode == "jit_bez_jev":
        capsule, evidence = build_jit_capsule(task_dir, task, use_jev=False)
        initial_user_msg = (
            f"{capsule}\n\n"
            f"Problem Statement:\n{task['title']}\n{task['description']}\n\n"
            "You are an autonomous SWE agent. Fix the bug. The JIT Context Capsule above identifies the target file "
            "and relevant AST working set. Apply a surgical patch and verify with run_tests."
        )
    elif mode == "jit_z_jev":
        capsule, evidence = build_jit_capsule(task_dir, task, use_jev=True)
        initial_user_msg = (
            f"{capsule}\n\n"
            f"Problem Statement:\n{task['title']}\n{task['description']}\n\n"
            "You are an autonomous SWE agent. Fix the bug. The JIT Context Capsule above provides JEV-ranked AST working set. "
            "Apply a surgical patch and verify with run_tests."
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")

    messages = [{"role": "user", "content": initial_user_msg}]

    turns_taken = 0
    total_tokens = 0
    total_prompt_tokens = 0
    discovery_ops = 0
    patches_applied = 0
    passed = False
    start_time = time.time()
    turn_log = []

    for turn in range(1, max_turns + 1):
        turns_taken = turn
        resp = call_lfm(messages)
        total_tokens += resp["eval_count"]
        total_prompt_tokens += resp["prompt_eval_count"]
        
        msg = resp["message"]
        tool_calls = resp["tool_calls"]
        
        # Check if model invoked tool calls
        if not tool_calls:
            # Fallback: check text for JSON tool call or direct patch
            raw_text = resp["content"]
            m_json = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if m_json:
                try:
                    parsed = json.loads(m_json.group(0))
                    tool_calls = [{"function": {"name": parsed.get("tool"), "arguments": parsed}}]
                except Exception:
                    pass
        
        if not tool_calls:
            # No tool call; prompt user continuation
            messages.append({"role": "assistant", "content": resp["content"] or "I will now proceed."})
            messages.append({"role": "user", "content": "Please invoke a tool: search_files, read_file, patch, or run_tests."})
            turn_log.append({"turn": turn, "action": "no_tool_call", "raw": resp["content"][:200]})
            continue

        # Append assistant message with tool calls
        messages.append(msg)

        # Process all tool calls in this turn
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            tool_output = ""
            action_desc = f"{tool_name}({args})"

            if tool_name == "search_files":
                discovery_ops += 1
                pattern = args.get("pattern", "")
                matches = []
                for p in task_dir.rglob("*.py"):
                    if "test" in p.name:
                        continue
                    try:
                        for idx, line in enumerate(p.read_text().splitlines(), 1):
                            if pattern.lower() in line.lower():
                                rel_p = p.relative_to(task_dir)
                                matches.append(f"{rel_p}:{idx}: {line.strip()[:80]}")
                    except Exception:
                        pass
                tool_output = "\n".join(matches[:15]) if matches else f"No matches found for pattern '{pattern}'."

            elif tool_name == "read_file":
                discovery_ops += 1
                rel_path = args.get("path", "")
                target_p = task_dir / rel_path
                if not rel_path or not target_p.exists() or target_p.is_dir():
                    tool_output = f"Error: Path '{rel_path}' is invalid or does not exist."
                else:
                    lines = target_p.read_text().splitlines()
                    off = max(1, args.get("offset", 1))
                    lim = args.get("limit", 40)
                    slice_lines = lines[off - 1 : off - 1 + lim]
                    tool_output = "\n".join(f"{off + idx:3d}| {l}" for idx, l in enumerate(slice_lines))

            elif tool_name == "patch":
                rel_path = args.get("path", "")
                target_p = task_dir / rel_path
                if not rel_path or not target_p.exists() or target_p.is_dir():
                    tool_output = f"Error: Path '{rel_path}' is invalid or does not exist."
                else:
                    old_s = args.get("old_string", "")
                    new_s = args.get("new_string", "")
                    content = target_p.read_text()
                    if old_s not in content:
                        tool_output = f"Error: old_string not found in file '{rel_path}'. Verify exact whitespace."
                    else:
                        new_content = content.replace(old_s, new_s, 1)
                        target_p.write_text(new_content)
                        patches_applied += 1
                        tool_output = f"Success: Patch applied cleanly to '{rel_path}'."

            elif tool_name == "run_tests":
                # Run pytest
                import subprocess
                cmd = ["python3", "-m", "pytest", task["test_file"]]
                proc = subprocess.run(cmd, cwd=task_dir, capture_output=True, text=True, timeout=30)
                if proc.returncode == 0:
                    passed = True
                    tool_output = "PASS: All tests in suite passed with exit code 0!"
                else:
                    tool_output = f"FAIL: Tests failed with exit code {proc.returncode}.\n{proc.stdout[-500:]}\n{proc.stderr[-500:]}"

            else:
                tool_output = f"Unknown tool '{tool_name}'."

            turn_log.append({
                "turn": turn,
                "action": action_desc,
                "tool_output": tool_output[:300]
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "content": tool_output
            })

        if passed:
            break

    wall_time = round(time.time() - start_time, 2)
    return {
        "task_id": task["id"],
        "mode": mode,
        "passed": passed,
        "wall_time_s": wall_time,
        "turns": turns_taken,
        "tokens": total_tokens,
        "prompt_tokens": total_prompt_tokens,
        "discovery_ops": discovery_ops,
        "patches_applied": patches_applied,
        "evidence": evidence,
        "turn_log": turn_log
    }

def main():
    print(f"=== SOTA Local Benchmark: {MODEL_NAME} on Apple Silicon Metal ===")
    print("Testing 3 Modes: [bez_jit, jit_bez_jev, jit_z_jev]\n")

    # Run on the first 2 tasks for fast, concrete empirical results
    eval_tasks = TASKS[:2]
    modes = ["bez_jit", "jit_bez_jev", "jit_z_jev"]
    
    all_results = {m: [] for m in modes}

    for task in eval_tasks:
        print(f"\n--- Task: {task['id']} ---")
        for m in modes:
            print(f"  Running mode: {m:12s} ...", end="", flush=True)
            res = run_agentic_task_lfm(task, mode=m, max_turns=7)
            all_results[m].append(res)
            
            icon = "✅ PASS" if res["passed"] else "❌ FAIL"
            print(f" -> {icon} | {res['wall_time_s']}s | turns: {res['turns']} | tok: {res['tokens']} | disc_ops: {res['discovery_ops']}")

    # Summary
    print("\n=== BENCHMARK SUMMARY ===")
    summary = {}
    for m in modes:
        res_list = all_results[m]
        passed_count = sum(1 for r in res_list if r["passed"])
        pass_rate = f"{passed_count}/{len(res_list)} ({passed_count/len(res_list)*100:.0f}%)"
        total_time = round(sum(r["wall_time_s"] for r in res_list), 1)
        avg_turns = round(sum(r["turns"] for r in res_list) / len(res_list), 1)
        total_tokens = sum(r["tokens"] for r in res_list)
        total_disc = sum(r["discovery_ops"] for r in res_list)

        summary[m] = {
            "passed": passed_count,
            "pass_rate": pass_rate,
            "total_time_s": total_time,
            "avg_turns": avg_turns,
            "total_tokens": total_tokens,
            "discovery_ops": total_disc
        }
        print(f"Mode: {m:12s} | Pass: {pass_rate} | Time: {total_time}s | Avg Turns: {avg_turns} | Tokens: {total_tokens} | Disc Ops: {total_disc}")

    out_file = Path("/tmp/swe_local_lfm_results.json")
    out_file.write_text(json.dumps({"summary": summary, "details": all_results}, indent=2))
    print(f"\n[Artifact saved to: {out_file}]")

if __name__ == "__main__":
    main()
