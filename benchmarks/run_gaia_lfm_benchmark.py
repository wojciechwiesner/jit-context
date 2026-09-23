#!/usr/bin/env python3
"""
GAIA Benchmark Runner for Local LiquidAI LFM 2.5 (JANGQ-AI/LFM2.5-8B-A1B-JANG_2L via vmlx-serve)
Integrated with Hermes JIT Context OS (L0 SessionOverlay, L1 Scope, L2 Distillation) & Hermes Tools.
"""

import os
import sys
import time
import json
import re
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Tuple, Optional

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import l0.db as l0_db
import l0.overlay as l0_overlay
import context.compiler as context_compiler
from benchmarks.run_gaia_jit_benchmark import (
    PythonSession,
    tool_web_search,
    tool_web_extract,
    score_gaia_answer
)

LFM_ENDPOINT = os.environ.get("LFM_ENDPOINT", "http://127.0.0.1:8195/v1/chat/completions")
MODEL_NAME = "JANGQ-AI/LFM2.5-8B-A1B-JANG_2L"

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for keywords using multiple search engines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string (simple keywords work best)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_extract",
            "description": "Extract readable text and markdown from web URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of HTTP/HTTPS URLs to fetch"
                    }
                },
                "required": ["urls"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": "Execute Python code in a stateful interpreter to compute math, simulate algorithms, or parse data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source code"}
                },
                "required": ["code"]
            }
        }
    }
]

def call_lfm(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 800
    }
    if tools:
        payload["tools"] = tools
        
    req = urllib.request.Request(
        LFM_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

def run_task_lfm(task: Dict[str, Any], max_turns: int = 10) -> Dict[str, Any]:
    task_id = task["task_id"]
    question = task["Question"]
    gt = task["Final answer"]
    level = task["Level"]
    
    conn = l0_db.get_db()
    session_id = f"gaia_lfm_{task_id[:8]}"
    l0_overlay.ensure_session(conn, session_id)
    py_sess = PythonSession()
    
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert autonomous reasoning assistant equipped with real tools.\n"
                "Ground all facts in tool evidence (search, fetch, python execution).\n"
                "Never guess arithmetic or complex logic — write and run python code to verify.\n"
                "Once you have the verified answer, conclude immediately with: FINAL ANSWER: <exact_answer>"
            )
        },
        {"role": "user", "content": question}
    ]
    
    turn = 0
    final_answer = None
    tool_calls_count = 0
    start_time = time.time()
    
    print(f"\n=======================================================")
    print(f"LFM TASK [{level}]: {task_id[:8]}")
    print(f"Q: {question[:140]}...")
    print(f"GT: {gt}")
    print(f"=======================================================")
    
    while turn < max_turns:
        turn += 1
        
        # JIT Context Compilation
        capsule = context_compiler.compile_context(
            conn=conn,
            session_id=session_id,
            user_message=question
        )
        
        messages[0]["content"] = (
            f"{capsule}\n\n"
            "You are an expert autonomous reasoning assistant equipped with real tools.\n"
            "Ground all facts in tool evidence (search, fetch, python execution).\n"
            "Never guess arithmetic or complex logic — write and run python code to verify.\n"
            "Once you have the verified answer, conclude immediately with: FINAL ANSWER: <exact_answer>"
        )
        
        if turn == max_turns and len(messages) > 2:
            messages.append({
                "role": "user",
                "content": "You have reached the final step budget. Synthesize all findings into the final answer. Format: FINAL ANSWER: <answer>"
            })
            
        try:
            resp_data = call_lfm(messages, tools=OPENAI_TOOLS if turn < max_turns else None)
        except Exception as e:
            print(f"  [Turn {turn}] LFM API Error: {e}")
            break
            
        choice = resp_data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls")
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        
        if reasoning:
            print(f"  [Turn {turn}] Thinking: {reasoning[:120]}...")
            
        if tool_calls:
            tool_calls_count += len(tool_calls)
            messages.append(msg)
            
            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name")
                raw_args = tc.get("function", {}).get("arguments", "{}")
                tc_id = tc.get("id", f"call_{turn}")
                
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
                    
                print(f"  [Turn {turn}] Tool Call: {fn_name}({list(args.keys())})")
                
                if fn_name == "web_search":
                    q_term = args.get("query", "")
                    tool_output = tool_web_search(q_term)
                elif fn_name == "web_extract":
                    urls = args.get("urls", [])
                    if isinstance(urls, str):
                        urls = [urls]
                    tool_output = tool_web_extract(urls)
                elif fn_name == "python_exec":
                    code_to_run = args.get("code", "")
                    tool_output = py_sess.execute(code_to_run)
                else:
                    tool_output = f"Unknown tool: {fn_name}"
                    
                print(f"    -> Output ({len(tool_output)} chars): {tool_output[:120]}...")
                
                # Record in L0 SQLite WAL
                l0_overlay.append_event(
                    conn=conn,
                    session_id=session_id,
                    role="tool",
                    content=f"{fn_name}: {tool_output[:1000]}",
                    origin="gaia_tool"
                )
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "content": tool_output
                })
        else:
            # Text response
            if "FINAL ANSWER:" in content:
                final_answer = content.split("FINAL ANSWER:")[-1].strip()
                break
            elif "\\boxed{" in content:
                m = re.search(r'\\boxed\{([^}]+)\}', content)
                if m:
                    final_answer = m.group(1).strip()
                    break
            elif content.strip():
                lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
                final_answer = lines[-1]
                break
            else:
                # If only reasoning was returned, check reasoning for final answer
                if "\\boxed{" in reasoning:
                    m = re.search(r'\\boxed\{([^}]+)\}', reasoning)
                    if m:
                        final_answer = m.group(1).strip()
                        break
                        
    # Clean final answer
    if final_answer:
        final_answer = re.sub(r'^(is|the answer is|answer:)\s*', '', final_answer, flags=re.IGNORECASE)
        final_answer = final_answer.replace('*', '').replace('`', '').strip()
        
    duration = time.time() - start_time
    is_match, reason = score_gaia_answer(final_answer, gt)
    
    print(f"--> RESULT LFM: {'[PASS]' if is_match else '[FAIL]'}")
    print(f"    Model Answer: {final_answer}")
    print(f"    Ground Truth: {gt}")
    print(f"    Reason: {reason} | Turns: {turn} | Tools: {tool_calls_count} | Time: {duration:.1f}s")
    
    return {
        "task_id": task_id,
        "level": level,
        "question": question,
        "ground_truth": gt,
        "model_answer": final_answer,
        "is_match": is_match,
        "reason": reason,
        "turns": turn,
        "tool_calls": tool_calls_count,
        "duration_s": duration
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run GAIA Benchmark with Local LFM 2.5 JANG_2L + JIT")
    parser.add_argument("--num", type=int, default=53, help="Number of tasks to evaluate")
    parser.add_argument("--level", type=str, default="1", help="GAIA Level (1, 2, 3 or all)")
    parser.add_argument("--output", type=str, default="/tmp/gaia_jit_eval_lvl1_lfm25.json", help="Output path")
    args = parser.parse_args()
    
    val_json_path = "/tmp/gaia/validation_metadata.json"
    if not os.path.exists(val_json_path):
        print(f"ERROR: {val_json_path} does not exist.", file=sys.stderr)
        sys.exit(1)
        
    with open(val_json_path) as f:
        tasks = json.load(f)
        
    if args.level != "all":
        tasks = [t for t in tasks if str(t.get("Level")) == args.level]
        
    selected_tasks = tasks[:args.num]
    print(f"Starting LFM2.5 JANG_2L GAIA Benchmark Evaluation: {len(selected_tasks)} tasks (Level {args.level})")
    
    results = []
    passed = 0
    
    for i, t in enumerate(selected_tasks, 1):
        print(f"\n[{i}/{len(selected_tasks)}]")
        res = run_task_lfm(t)
        results.append(res)
        if res["is_match"]:
            passed += 1
            
        with open(args.output, "w") as f:
            json.dump({
                "model": MODEL_NAME,
                "runtime": "Apple Silicon Metal via vmlx-serve (JANG 2.4-bit mixed)",
                "harness": "Hermes JIT Context OS (L0/L1/L2)",
                "total": len(results),
                "passed": passed,
                "accuracy": round((passed / len(results)) * 100, 2),
                "tasks": results
            }, f, indent=2)
            
    print("\n=======================================================")
    print(f"FINAL LFM BENCHMARK SUMMARY")
    print(f"Evaluated: {len(results)}")
    print(f"Passed: {passed} ({passed / len(results) * 100:.1f}%)")
    print(f"Saved to: {args.output}")
    print("=======================================================")

if __name__ == "__main__":
    main()
