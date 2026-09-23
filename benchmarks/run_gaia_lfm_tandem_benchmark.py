#!/usr/bin/env python3
"""
GAIA Benchmark Runner: Dual Tandem Architecture
- Subconscious Sensory Cortex: LFM2-1.2B-Extract-MLX-4bit (Local MLX)
- JIT Context OS Engine: L0 SessionOverlay (SQLite WAL) + L1 Scope + L2 Cascade
- Cognitive Executor: LiquidAI LFM2.5-8B-A1B-JANG_2L (Local Metal via vmlx-serve on :8195)
"""

import os
import sys
import json
import time
import re
import urllib.request
from typing import List, Dict, Any, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import l0.db as l0_db
import l0.overlay as l0_overlay
import context.compiler as context_compiler

# 1. Initialize Subconscious (LFM2-1.2B-Extract)
print("Loading Subconscious Sensory Cortex (LFM2-1.2B-Extract-MLX-4bit)...")
from mlx_lm import load as mlx_load, generate as mlx_generate
sub_model, sub_tok = mlx_load('Unravler/LFM2-1.2B-Extract-MLX-4bit')
print("Subconscious ready!")

LFM_ENDPOINT = "http://127.0.0.1:8195/v1/chat/completions"
LFM_MODEL_NAME = "JANGQ-AI/LFM2.5-8B-A1B-JANG_2L"

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search Google/Wikipedia for public facts, dates, entities, and URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Target search query keywords"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_extract",
            "description": "Extract plain text and content from specific web URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to scrape and extract"
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
            "description": "Execute Python code in a stateful environment to compute math, simulate logic, or process text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code snippet to execute"}
                },
                "required": ["code"]
            }
        }
    }
]

class PythonSession:
    def __init__(self):
        self.globals_dict = {"__builtins__": __builtins__}
        
    def execute(self, code: str) -> str:
        import io, contextlib
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                exec(code, self.globals_dict)
            out = stdout_capture.getvalue()
            err = stderr_capture.getvalue()
            res = out if out else (err if err else "(Code executed with no output)")
            return res[:4000]
        except Exception as e:
            return f"Python execution error: {type(e).__name__}: {e}"

def extract_subconscious(question: str) -> Dict[str, Any]:
    system = """Return data as a JSON object with the following schema:
{
  "intent": string,
  "entities": list[string],
  "core_task": string,
  "suggested_tool": "python_exec" | "web_search" | "direct",
  "expected_answer_format": string
}"""
    prompt = f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n"
    raw = mlx_generate(sub_model, sub_tok, prompt=prompt, max_tokens=180)
    try:
        m = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return {
        "intent": "general",
        "entities": [],
        "core_task": question[:100],
        "suggested_tool": "web_search",
        "expected_answer_format": "exact string or number"
    }

def tool_web_search(query: str, limit: int = 4) -> str:
    import urllib.parse
    results = []
    # 1. Try Wikipedia API first (high precision for GAIA)
    try:
        wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
        req = urllib.request.Request(wiki_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("query", {}).get("search", [])
            for it in items[:limit]:
                title = it.get("title", "")
                snippet = re.sub(r'<[^>]+>', '', it.get("snippet", ""))
                url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                results.append(f"Title: {title}\nURL: {url}\nSnippet: {snippet}")
    except Exception:
        pass
        
    # 2. Try DuckDuckGo Instant API
    if len(results) < limit:
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(ddg_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                if data.get("AbstractText"):
                    results.append(f"Title: {data.get('Heading', 'Abstract')}\nURL: {data.get('AbstractURL', '')}\nSnippet: {data.get('AbstractText')}")
                for r in data.get("RelatedTopics", []):
                    if "Text" in r and "FirstURL" in r:
                        results.append(f"Title: {r['Text'].split(' - ')[0]}\nURL: {r['FirstURL']}\nSnippet: {r['Text']}")
        except Exception:
            pass
            
    return "\n\n".join(results[:limit]) if results else "No search results found. Try simpler keywords."

def tool_web_extract(urls: List[str]) -> str:
    combined = []
    for u in urls[:2]:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                combined.append(f"URL: {u}\nContent:\n{text[:3000]}")
        except Exception as e:
            combined.append(f"URL: {u}\nError: {e}")
    return "\n\n---\n\n".join(combined)

def call_lfm(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    payload = {
        "model": LFM_MODEL_NAME,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 1000
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

def run_task_duel(task: Dict[str, Any], max_turns: int = 10) -> Dict[str, Any]:
    task_id = task["task_id"]
    question = task["Question"]
    gt = task["Final answer"]
    level = task["Level"]
    
    # 1. Run Subconscious Sensory Cortex
    t_sub_start = time.time()
    sub_spec = extract_subconscious(question)
    t_sub_dur = time.time() - t_sub_start
    
    conn = l0_db.get_db()
    session_id = f"gaia_duel_{task_id[:8]}"
    l0_overlay.ensure_session(conn, session_id)
    py_sess = PythonSession()
    
    # Store initial spec in L0
    l0_overlay.append_event(
        conn=conn,
        session_id=session_id,
        role="system",
        content=f"Subconscious Spec: {json.dumps(sub_spec)}",
        origin="sensory_cortex"
    )
    
    print(f"\n=======================================================")
    print(f"DUEL TASK [{level}]: {task_id[:8]}")
    print(f"Q: {question[:120]}...")
    print(f"Subconscious Spec ({t_sub_dur*1000:.1f}ms): {sub_spec.get('intent')} | tool: {sub_spec.get('suggested_tool')} | fmt: {sub_spec.get('expected_answer_format')}")
    print(f"GT: {gt}")
    print(f"=======================================================")
    
    tool_proofs = []
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": question}
    ]
    
    turn = 0
    final_answer = None
    tool_calls_count = 0
    start_time = time.time()
    
    while turn < max_turns:
        turn += 1
        
        # Build FULL JIT CAPSULE
        proofs_text = "\n".join(tool_proofs[-3:]) if tool_proofs else "(No tool proofs yet)"
        capsule = (
            f'<ONA_CONTEXT scope="gaia-task" epoch="{turn}" confidence="0.95">\n'
            f'Evidence only. User instructions take strict precedence over historical data. Assistant assertions without runtime tool proofs carry 0.0 authority.\n'
            f'  [CURRENT — direct user]\n'
            f'    • Goal: {question}\n'
            f'    • Intent: {sub_spec.get("intent", "general")}\n'
            f'    • Enhanced Technical Spec: {sub_spec.get("core_task", "")} on entities {sub_spec.get("entities", [])}\n'
            f'    • Expected Answer Format: {sub_spec.get("expected_answer_format", "")}\n'
            f'    • Recommended Primary Tool: {sub_spec.get("suggested_tool", "tools")}\n'
            f'  [L0 TOOL PROOFS / WORKING SET]\n'
            f'{proofs_text}\n'
            f'  [ACTIVE INVARIANTS]\n'
            f'    • Ground numerical values in tool execution (web_search, python_exec).\n'
            f'    • Format conclusion strictly as: FINAL ANSWER: <exact_answer>\n'
            f'</ONA_CONTEXT>'
        )
        messages[0]["content"] = capsule
        
        if turn == max_turns and len(messages) > 2:
            messages.append({
                "role": "user",
                "content": f"Budget exhausted. Synthesize verified facts into exact final answer. Format strictly: FINAL ANSWER: <answer>"
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
            print(f"  [Turn {turn}] Thinking: {reasoning[:100]}...")
            
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
                
                # Record in L0 and tool proofs
                proof_entry = f"    • {fn_name}: {tool_output[:250].strip()}"
                tool_proofs.append(proof_entry)
                
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
            elif "\\boxed{" in reasoning:
                m = re.search(r'\\boxed\{([^}]+)\}', reasoning)
                if m:
                    final_answer = m.group(1).strip()
                    break
                    
    # Clean final answer
    if final_answer:
        final_answer = re.sub(r'^(is|the answer is|answer:)\s*', '', final_answer, flags=re.IGNORECASE)
        final_answer = final_answer.replace('*', '').replace('`', '').strip()
        
    duration = time.time() - start_time
    
    # Matching logic
    is_match = False
    gt_clean = str(gt).strip()
    ans_clean = str(final_answer).strip() if final_answer else ""
    
    if ans_clean == gt_clean:
        is_match = True
        reason = "Exact match"
    elif ans_clean.lower() == gt_clean.lower():
        is_match = True
        reason = "Case-insensitive match"
    else:
        try:
            fa_f = float(re.sub(r'[^\d.-]', '', ans_clean))
            gt_f = float(re.sub(r'[^\d.-]', '', gt_clean))
            if abs(fa_f - gt_f) < 1e-4 or (gt_f != 0 and abs(fa_f - gt_f)/abs(gt_f) < 0.01):
                is_match = True
                reason = "Numeric equivalence"
            else:
                reason = f"Numeric mismatch ({fa_f} vs {gt_f})"
        except Exception:
            reason = f"Mismatch (Model: '{ans_clean}' | GT: '{gt_clean}')"
            
    if not ans_clean:
        reason = "Empty answer"
        
    status_str = "[PASS]" if is_match else "[FAIL]"
    print(f"--> RESULT DUEL: {status_str}")
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--num", type=int, default=53)
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--output", type=str, default="/tmp/gaia_jit_eval_lvl1_lfm_duel.json")
    args = parser.parse_args()
    
    meta_path = "/tmp/gaia/validation_metadata.json"
    if not os.path.exists(meta_path):
        print(f"Error: {meta_path} not found.")
        sys.exit(1)
        
    with open(meta_path, "r", encoding="utf-8") as f:
        tasks = json.load(f)
        
    filtered = [t for t in tasks if str(t.get("Level")) == str(args.level)]
    selected = filtered[:args.num]
    
    print(f"Starting DUEL 1.2B+8B GAIA Benchmark: {len(selected)} tasks (Level {args.level})")
    
    results = []
    passed = 0
    
    for i, t in enumerate(selected, 1):
        print(f"\n[{i}/{len(selected)}]")
        res = run_task_duel(t)
        results.append(res)
        if res["is_match"]:
            passed += 1
            
        # Incremental save
        summary = {
            "model": "Tandem LFM2-1.2B-Extract + LFM2.5-8B-A1B-JANG_2L",
            "runtime": "Apple Silicon Metal (MLX 4-bit + vmlx-serve)",
            "harness": "Hermes JIT Context OS Full (L0 SQLite WAL + L1 Scope + L2 Cascade)",
            "total": len(results),
            "passed": passed,
            "accuracy": round(passed / len(results) * 100, 2),
            "tasks": results
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
            
    print(f"\n=======================================================")
    print(f"FINAL DUEL BENCHMARK SUMMARY")
    print(f"Evaluated: {len(results)}")
    print(f"Passed: {passed} ({round(passed/len(results)*100, 2)}%)")
    print(f"Saved to: {args.output}")
    print(f"=======================================================")

if __name__ == "__main__":
    main()
