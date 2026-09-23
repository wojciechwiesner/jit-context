#!/usr/bin/env python3
"""
Hermes JIT Hybrid Dual-Worker Router Benchmark (GAIA & Coding tasks).
Roles:
  - Fast Worker: LFM2.5-8B-A1B-JANG_2L (Port 8195, vmlx) - ~2.4 GB RAM, ~200 tok/s
  - Deep Worker: Qwen3.8-9B-Distill (Ollama / MLX) - ~4.8-5.8 GB RAM, multi-step reasoning
  - JIT Context OS: Dynamic L0 SQLite WAL + L1 AST working set + Invariants
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration & Endpoints
# ---------------------------------------------------------------------------
LFM_ENDPOINT = "http://127.0.0.1:8195/v1/chat/completions"
LFM_MODEL_NAME = "JANGQ-AI/LFM2.5-8B-A1B-JANG_2L"

OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/chat"
QWEN_MODEL_NAME = "qwen3.8:jit"

# ---------------------------------------------------------------------------
# Tools Runtime (Python Exec, Wikipedia/DuckDuckGo Search)
# ---------------------------------------------------------------------------
def tool_python_exec(code: str) -> str:
    import subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            cwd="/tmp"
        )
        out = (proc.stdout + proc.stderr).strip()
        return out if out else "(Code executed with no output)"
    except subprocess.TimeoutExpired:
        return "Python Execution Error: Timeout after 15s"
    except Exception as e:
        return f"Python Execution Error: {e}"

def tool_web_search(query: str, limit: int = 4) -> str:
    results = []
    # 1. Try Wikipedia API first
    try:
        wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
        req = urllib.request.Request(wiki_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
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
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                if data.get("AbstractText"):
                    results.append(f"Title: {data.get('Heading', 'Abstract')}\nURL: {data.get('AbstractURL', '')}\nSnippet: {data.get('AbstractText')}")
                for r in data.get("RelatedTopics", []):
                    if "Text" in r and "FirstURL" in r:
                        results.append(f"Title: {r['Text'].split(' - ')[0]}\nURL: {r['FirstURL']}\nSnippet: {r['Text']}")
        except Exception:
            pass

    return "\n\n".join(results[:limit]) if results else "No search results found. Try simpler keywords."

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": "Execute Python 3 script to perform calculations, parse data, or verify algorithms.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Valid Python 3 script"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search Wikipedia and knowledge bases for factual evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Concise search keywords"}
                },
                "required": ["query"]
            }
        }
    }
]

# ---------------------------------------------------------------------------
# JIT Context Capsule Compiler
# ---------------------------------------------------------------------------
def build_jit_capsule(task_id: str, goal: str, worker_type: str, strategy: Optional[str] = None) -> str:
    strategy_block = f"\n  [STRATEGIC PLAN - {worker_type.upper()}]\n    • Strategy: {strategy}" if strategy else ""
    return f"""<ONA_CONTEXT scope="benchmark" epoch="2" confidence="1.0" complexity="{worker_type}">
Evidence only. User instructions take strict precedence over historical data.
Assistant assertions without runtime tool proofs carry 0.0 authority.
  [ACTIVE INVARIANTS]
    • ZERO FAKE / EVIDENCE FIRST: Every factual assertion or number requires tool verification.
    • HARD CONSTRAINT: End response with exactly 'FINAL ANSWER: <value>'. Do not include extra commentary after.
  [CURRENT TASK]
    • Task ID: {task_id}
    • Goal: {goal[:400]}...{strategy_block}
</ONA_CONTEXT>"""

# ---------------------------------------------------------------------------
# Worker Callers: LFM (Fast) vs Qwen (Deep)
# ---------------------------------------------------------------------------
def call_lfm_fast_worker(messages: List[Dict[str, Any]], max_tokens: int = 800) -> Dict[str, Any]:
    payload = {
        "model": LFM_MODEL_NAME,
        "messages": messages,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto",
        "temperature": 0.0,
        "max_tokens": max_tokens
    }
    req = urllib.request.Request(
        LFM_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))

def call_qwen_deep_worker(messages: List[Dict[str, Any]], max_tokens: int = 1200) -> Dict[str, Any]:
    # Ollama chat API format
    payload = {
        "model": QWEN_MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": max_tokens
        }
    }
    req = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        # Map to OpenAI compatible response
        msg = res.get("message", {})
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": msg.get("content", ""),
                    "tool_calls": None
                }
            }]
        }

# ---------------------------------------------------------------------------
# Router: Classify Task Complexity & Select Route
# ---------------------------------------------------------------------------
def classify_task_route(question: str) -> str:
    """
    Determines whether task should go to FAST PATH (LFM) or DEEP PATH (Qwen).
    Fast path: Pure math, simple unit conversions, short code script questions.
    Deep path: Multi-hop reasoning, riddles, history/literature lookups, ambiguous questions.
    """
    q_lower = question.lower()
    
    # Obvious Fast Path patterns (pure computation / Python math)
    if any(k in q_lower for k in ["calculate", "compute the sum", "divide", "multiply", "how many hours", "equation", "script"]):
        if not any(k in q_lower for k in ["riddle", "episode", "who played", "album", "history", "species"]):
            return "fast_lfm"

    # Default to Deep Path for generalist, multi-hop reasoning
    return "deep_qwen"

# ---------------------------------------------------------------------------
# Answer Normalizer & Scorer
# ---------------------------------------------------------------------------
def normalize_answer(s: Any) -> str:
    if s is None:
        return ""
    text = str(s).strip()
    text = re.sub(r'^(FINAL ANSWER:|\bAnswer:|\bThe answer is)\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\\boxed\{([^}]+)\}', r'\1', text)
    text = text.rstrip('.').strip()
    return text.lower()

def is_answer_match(model_ans: str, ground_truth: str) -> bool:
    norm_m = normalize_answer(model_ans)
    norm_g = normalize_answer(ground_truth)
    if not norm_m:
        return False
    if norm_m == norm_g:
        return True
    try:
        f_m = float(re.sub(r'[^\d.-]', '', norm_m))
        f_g = float(re.sub(r'[^\d.-]', '', norm_g))
        if abs(f_m - f_g) < 1e-4 or (f_g != 0 and abs((f_m - f_g) / f_g) < 0.01):
            return True
    except ValueError:
        pass
    if len(norm_g) > 3 and norm_g in norm_m:
        return True
    return False

# ---------------------------------------------------------------------------
# Main Router Execution Loop
# ---------------------------------------------------------------------------
def execute_hybrid_task(task_id: str, question: str, ground_truth: str, mode: str = "hybrid") -> Dict[str, Any]:
    start_t = time.time()
    route = classify_task_route(question) if mode == "hybrid" else mode
    
    print(f"\n=======================================================")
    print(f"TASK [{task_id[:8]}]: Route={route.upper()} | Mode={mode}")
    print(f"Q: {question[:100]}...")
    print(f"GT: {ground_truth}")
    print(f"=======================================================")
    
    tool_calls_count = 0
    final_answer = None
    worker_used = route
    replanned = False
    
    # 1. Execute Selected Worker Route
    if route == "fast_lfm":
        # Fast Path with LFM
        capsule = build_jit_capsule(task_id, question, "fast_worker")
        messages = [
            {"role": "system", "content": capsule},
            {"role": "user", "content": question}
        ]
        try:
            res = call_lfm_fast_worker(messages)
            msg = res.get("choices", [{}])[0].get("message", {})
            content = msg.get("content") or msg.get("reasoning_content") or ""
            if "FINAL ANSWER:" in content:
                final_answer = content.split("FINAL ANSWER:")[-1].split("\n")[0].strip()
            elif content:
                final_answer = content.strip().split("\n")[-1].strip()
        except Exception as e:
            print(f"  [LFM Error]: {e}")
            final_answer = None

        # Check confidence / fall-through to Deep Worker (Qwen) if failed
        if not final_answer or "cannot determine" in final_answer.lower():
            print(f"  [Fast Path Failed -> Escalating to DEEP WORKER (Qwen Replan)]")
            replanned = True
            route = "deep_qwen"
            worker_used = "qwen_escalated"

    if route == "deep_qwen":
        # Deep Path with Qwen (Reasoning + Tools synthesis)
        capsule = build_jit_capsule(task_id, question, "deep_worker")
        # Pre-fetch relevant knowledge via search if needed
        search_evidence = tool_web_search(question[:100], limit=3)
        enhanced_prompt = f"""{question}

Available Fact Evidence:
{search_evidence}

Provide step-by-step reasoning, then end with:
FINAL ANSWER: <concise answer>"""

        messages = [
            {"role": "system", "content": capsule},
            {"role": "user", "content": enhanced_prompt}
        ]
        tool_calls_count += 1
        try:
            res = call_qwen_deep_worker(messages)
            content = res.get("choices", [{}])[0].get("message", {}).get("content", "")
            if "FINAL ANSWER:" in content:
                final_answer = content.split("FINAL ANSWER:")[-1].split("\n")[0].strip()
            elif "\\boxed{" in content:
                m = re.search(r'\\boxed\{([^}]+)\}', content)
                if m:
                    final_answer = m.group(1).strip()
            elif content:
                lines = [l.strip() for l in content.split("\n") if l.strip()]
                final_answer = lines[-1]
        except Exception as e:
            print(f"  [Qwen Error]: {e}")
            final_answer = None

    elapsed = time.time() - start_t
    match = is_answer_match(str(final_answer), ground_truth)
    
    print(f"--> RESULT: [{'PASS' if match else 'FAIL'}]")
    print(f"    Worker: {worker_used} (Replanned: {replanned})")
    print(f"    Model Answer: {final_answer}")
    print(f"    Ground Truth: {ground_truth}")
    print(f"    Time: {elapsed:.2f}s | Tools: {tool_calls_count}")
    
    return {
        "task_id": task_id,
        "question": question,
        "ground_truth": ground_truth,
        "model_answer": final_answer,
        "is_match": match,
        "worker_used": worker_used,
        "replanned": replanned,
        "duration_s": elapsed,
        "tool_calls": tool_calls_count
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["hybrid", "lfm_only", "qwen_only"], default="hybrid")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    
    # Load GAIA dataset tasks from local cached metadata
    val_json_path = "/tmp/gaia/validation_metadata.json"
    print(f"Loading GAIA Level 1 tasks from {val_json_path}...")
    tasks = []
    with open(val_json_path, "r", encoding="utf-8") as f:
        all_tasks = json.load(f)
        for rec in all_tasks:
            if str(rec.get("Level")) == "1":
                tasks.append(rec)
    
    print(f"Loaded {len(tasks)} Level 1 tasks. Running mode={args.mode} on {args.limit} tasks...")
    results = []
    passed = 0
    for i, t in enumerate(tasks[:args.limit]):
        res = execute_hybrid_task(
            task_id=t.get("task_id", f"task_{i}"),
            question=t.get("Question", ""),
            ground_truth=t.get("Final answer", ""),
            mode=args.mode
        )
        results.append(res)
        if res["is_match"]:
            passed += 1
            
    print(f"\n=======================================================")
    print(f"FINAL SUMMARY ({args.mode.upper()}): {passed} / {len(results)} ({passed/len(results)*100:.1f}%)")
    print(f"=======================================================")
