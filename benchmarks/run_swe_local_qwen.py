#!/usr/bin/env python3
"""
Empirical SWE Agent Benchmark on Local Modified Model:
  Model: qwen3.8:jit (Ollama @ 127.0.0.1:11434)
  Modes:
    1. BEZ JIT (Raw baseline without capsule)
    2. Z JIT Context OS (AST working set + JEV/JIT guidance)

Verification:
  - Physical pytest execution on disk (exit code == 0).
  - Multi-turn autonomous tool loop: search_files, read_file, patch, run_tests, done.
  - Zero fake/cheating: genuine model generations and physical file modifications.
"""

import os
import sys
import json
import time
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from benchmarks.run_swe_10_battle import TASKS, setup_task_repo, build_jit_capsule, verify_baseline_failure

BENCH_TMP = Path("/tmp/swe_local_qwen_comparison")
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "qwen3.8:jit"

# Select 5 representative tasks covering django, flask, requests, sympy
SWE_5_TASKS = [
    TASKS[0],  # django__django-11099
    TASKS[3],  # django__django-15400
    TASKS[5],  # pallets__flask-4045
    TASKS[6],  # requests__requests-2148
    TASKS[9],  # sympy__sympy-18057
]


def call_local_qwen(messages: List[Dict[str, str]], timeout: int = 60) -> Optional[Dict[str, Any]]:
    """Calls local qwen3.8:jit via Ollama API."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 1024,
        }
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
    return None


def run_agentic_task_qwen(task: Dict[str, Any], mode: str, max_turns: int = 7) -> Dict[str, Any]:
    task_dir = BENCH_TMP / mode / task["id"]
    setup_task_repo(task_dir, task)

    # 1. Hard Baseline Verification
    if not verify_baseline_failure(task_dir, task["test_file"]):
        return {
            "task_id": task["id"],
            "mode": mode,
            "status": "INVALID_BASELINE",
            "passed": False,
            "turns": 0,
            "wall_time_s": 0.0,
            "tokens": 0,
            "discovery_ops": 0,
            "error": "Baseline test passed before fix"
        }

    sys_instructions = """You are an autonomous SWE agent solving a software bug in this repository.
You have the following tools available:
1. {"tool": "search_files", "pattern": "string"} -> searches files in repository
2. {"tool": "read_file", "path": "relative/path.py", "offset": 1, "limit": 50} -> reads file with line numbers
3. {"tool": "patch", "path": "relative/path.py", "old_string": "exact code", "new_string": "replacement"} -> surgical patch
4. {"tool": "run_tests"} -> executes pytest on the repository test suite
5. {"tool": "done", "summary": "explanation"} -> finishes the task

Rules:
- NEVER call done before running run_tests and verifying that all tests pass.
- Fix all issues mentioned in the problem statement.
- Respond ONLY with a single valid JSON object corresponding to your tool call."""

    if mode == "bez_jit":
        initial_user_msg = f"""Problem Statement:
{task['title']}
{task['description']}

Solve this bug in the repository. Start by investigating or modifying the relevant files."""
    elif mode == "jit_bez_jev":
        capsule = build_jit_capsule(task_dir, task, use_jev=False)
        initial_user_msg = f"""{capsule}

Problem Statement:
{task['title']}
{task['description']}

Solve this bug using the surgical patch tool. The target file and working set are provided in the capsule above."""
    elif mode == "jit_z_jev":
        capsule = build_jit_capsule(task_dir, task, use_jev=True)
        initial_user_msg = f"""{capsule}

Problem Statement:
{task['title']}
{task['description']}

Solve this bug using the surgical patch tool. The target file and working set are provided in the capsule above."""

    messages = [
        {"role": "user", "content": f"{sys_instructions}\n\n{initial_user_msg}"}
    ]

    total_tokens = 0
    discovery_ops = 0
    task_passed = False
    last_error = None
    t0 = time.time()
    turn = 0

    for turn in range(1, max_turns + 1):
        resp_data = call_local_qwen(messages)
        if not resp_data:
            last_error = "Ollama API timeout/failure"
            break

        text = resp_data["message"]["content"]
        eval_count = resp_data.get("eval_count", 0)
        total_tokens += eval_count

        # Clean JSON from markdown fences
        clean_text = text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()
        m_json = re.search(r"\{.*\}", clean_text, re.DOTALL)
        if m_json:
            clean_text = m_json.group(0)

        try:
            tool_call = json.loads(clean_text)
        except Exception as e:
            last_error = f"JSON Parse Error: {e}"
            # Give error feedback to agent
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"Tool Result: Error parsing JSON: {e}. Output a single valid JSON object.\n\nNext tool call:"})
            continue

        tool_name = tool_call.get("tool")

        if tool_name == "search_files":
            discovery_ops += 1
            pattern = tool_call.get("pattern", "")
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
            if matches:
                tool_output = "\n".join(matches[:15])
            else:
                tool_output = f"No matches found for pattern '{pattern}'."

        elif tool_name == "read_file":
            discovery_ops += 1
            rel_path = tool_call.get("path", "")
            target_p = task_dir / rel_path
            if not rel_path or not target_p.exists() or target_p.is_dir():
                tool_output = f"Error: Path '{rel_path}' is invalid, is a directory, or does not exist."
            else:
                lines = target_p.read_text().splitlines()
                off = max(1, tool_call.get("offset", 1))
                lim = tool_call.get("limit", 40)
                slice_lines = lines[off - 1 : off - 1 + lim]
                tool_output = "\n".join(f"{off + idx:3d}| {l}" for idx, l in enumerate(slice_lines))

        elif tool_name == "patch":
            rel_path = tool_call.get("path", "")
            target_p = task_dir / rel_path
            if not rel_path or not target_p.exists() or target_p.is_dir():
                tool_output = f"Error: Path '{rel_path}' is invalid, is a directory, or does not exist."
            else:
                old_s = tool_call.get("old_string", "")
                new_s = tool_call.get("new_string", "")
                content = target_p.read_text()
                if old_s not in content:
                    tool_output = f"Error: old_string not found in file '{rel_path}'. Verify exact whitespace/indentation."
                else:
                    new_content = content.replace(old_s, new_s, 1)
                    target_p.write_text(new_content)
                    tool_output = f"Success: Patch applied cleanly to '{rel_path}'."

        elif tool_name == "run_tests":
            env = os.environ.copy()
            if not (task_dir / "_pytest").exists():
                env["PYTHONPATH"] = str(task_dir)
            cmd = ["python3", "-m", "pytest", str(task_dir / task["test_file"])]
            res = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if res.returncode == 0:
                tool_output = "Pytest: ALL TESTS PASSED (exit code 0)."
                task_passed = True
            else:
                out_summary = res.stdout[-400:] if res.stdout else res.stderr[-400:]
                tool_output = f"Pytest: TESTS FAILED (exit code {res.returncode}):\n{out_summary}"
                task_passed = False

        elif tool_name == "done":
            break

        else:
            tool_output = f"Unknown tool: {tool_name}"

        # Feed tool result back to agent
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f"Tool Result:\n{tool_output}\n\nNext tool call:"})

        if tool_name == "run_tests" and task_passed:
            break

    # Final physical verification
    env = os.environ.copy()
    if not (task_dir / "_pytest").exists():
        env["PYTHONPATH"] = str(task_dir)
    final_res = subprocess.run(["python3", "-m", "pytest", str(task_dir / task["test_file"])], env=env, capture_output=True, text=True)
    verified_pass = (final_res.returncode == 0)
    wall_time = round(time.time() - t0, 2)

    return {
        "task_id": task["id"],
        "mode": mode,
        "status": "PASS" if verified_pass else "FAIL",
        "passed": verified_pass,
        "turns": turn,
        "wall_time_s": wall_time,
        "tokens": total_tokens,
        "discovery_ops": discovery_ops,
        "error": last_error
    }


def main():
    if BENCH_TMP.exists():
        shutil.rmtree(BENCH_TMP)
    BENCH_TMP.mkdir(parents=True)

    print("=" * 70)
    print(" ⚔️  SWE AGENT BENCHMARK: LOCAL QWEN3.8:JIT (Metal M2 Pro)")
    print("=======================================================")
    print(f"• Model:               {MODEL_NAME} via Ollama (:11434)")
    print("• Architecture:        9.2B Q4_K_M (Metal Metal Shaders)")
    print("• Comparison:          Mode A (BEZ JIT) vs Mode B (Z JIT Context OS)")
    print("• Verification:        Physical pytest execution on disk (exit code == 0)")
    print("• Tasks:               5 Real SWE Python bugs with decoy files")
    print("=======================================================")

    modes = ["bez_jit", "jit_bez_jev", "jit_z_jev"]
    mode_labels = {
        "bez_jit": "1. BEZ JIT (Raw Baseline)",
        "jit_bez_jev": "2. Z JIT (BEZ JEV - Heuristic Token)",
        "jit_z_jev": "3. Z JIT + JEV (Probabilistic Engine)"
    }

    all_results = {m: [] for m in modes}

    for t_idx, task in enumerate(SWE_5_TASKS, 1):
        print(f"\n[{t_idx}/5] 🎯 TASK: {task['id']} — {task['title'][:50]}...")
        
        for m in modes:
            print(f"   ├─ Running {mode_labels[m]}...", end="", flush=True)
            res = run_agentic_task_qwen(task, mode=m, max_turns=7)
            all_results[m].append(res)
            
            icon = "✅ PASS" if res["passed"] else "❌ FAIL"
            print(f" -> {icon} | {res['wall_time_s']}s | turns: {res['turns']} | tok: {res['tokens']} | disc: {res['discovery_ops']}")

            # Save snapshot after every single run
            out_file = Path("/tmp/swe_local_qwen_results.json")
            out_file.write_text(json.dumps({"details": all_results}, indent=2))

    summary_stats = {}
    for m in modes:
        res_list = all_results[m]
        passed_count = sum(1 for r in res_list if r["passed"])
        pass_rate = f"{passed_count}/5 ({passed_count/5*100:.0f}%)"
        total_time = round(sum(r["wall_time_s"] for r in res_list), 1)
        avg_turns = round(sum(r["turns"] for r in res_list) / len(res_list), 1)
        total_tokens = sum(r["tokens"] for r in res_list)
        total_disc = sum(r["discovery_ops"] for r in res_list)

        summary_stats[m] = {
            "passed": passed_count,
            "pass_rate": pass_rate,
            "total_time_s": total_time,
            "avg_turns": avg_turns,
            "total_tokens": total_tokens,
            "discovery_ops": total_disc
        }

    out_file = Path("/tmp/swe_local_qwen_results.json")
    out_file.write_text(json.dumps({"summary": summary_stats, "details": all_results}, indent=2))
    print(f"\n[Artifact saved to: {out_file}]")


if __name__ == "__main__":
    main()
