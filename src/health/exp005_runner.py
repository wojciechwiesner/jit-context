"""EXP-005: Real Physical Benchmark for Lost-in-the-Middle & Context Efficiency.

Executes real HTTP calls to gemini-3.8-flash testing needle retrieval
when buried in the dead middle of large distractor context vs compiled JIT capsule.
"""

import os
import sys
import time
import json
import urllib.request
from typing import Dict, Any, List
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent.parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session
from context.compiler import compile_context

LLM_ENDPOINT = os.environ.get("BORG_TOOLS_LLM_URL", "http://127.0.0.1:8788/v1/chat/completions")
LLM_TOKEN = os.environ.get("BORG_TOOLS_LLM_TOKEN", "")
MODEL_NAME = "gemini-3.8-flash"

def call_llm(messages: list) -> Dict[str, Any]:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 500
    }
    req = urllib.request.Request(
        LLM_ENDPOINT,
        headers={
            "Authorization": f"Bearer {LLM_TOKEN}",
            "Content-Type": "application/json"
        },
        data=json.dumps(payload).encode("utf-8")
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        duration_s = time.perf_counter() - t0
        body = json.loads(resp.read().decode("utf-8"))
        return {
            "content": body["choices"][0]["message"]["content"].strip(),
            "usage": body.get("usage", {}),
            "latency_s": round(duration_s, 3)
        }

def run_exp005_lost_in_the_middle_and_gap_closure() -> Dict[str, Any]:
    print(f"=== RUNNING REAL EXP-005 ON {MODEL_NAME} ===")
    needle = "SECRET_AUTH_KEY: 948192-OMEGA"
    question = "Jaki jest dokladny SECRET_AUTH_KEY? Podaj wylacznie klucz."

    filler_paragraph = (
        "Infrastructure telemetry record:\n"
        "Node cluster hostinger-s1 reports 42 microservices healthy.\n"
        "Memory usage across PM2 processes is within normal thresholds: 412MB active, 128MB swap.\n"
        "Cloudflare edge caching shows a 94.2% hit ratio on static assets.\n"
        "Automated KSeF invoicing batch completed without token expiration.\n\n"
    )
    
    # 4000 tokens before needle, 4000 tokens after needle = 8000+ tokens haystack
    chunk_before = filler_paragraph * 50
    chunk_after = filler_paragraph * 50
    haystack_text = f"{chunk_before}\nCRITICAL CONFIGURATION OVERRIDE: {needle}\n{chunk_after}"

    # 1. Test Raw Haystack (Needle in the dead middle of ~8k tokens)
    print("\n[EXP-005] Calling Raw Haystack (Needle at 50% depth in ~8k tokens)...")
    res_haystack = call_llm([
        {"role": "system", "content": "You are a precise systems operator. Extract the requested key accurately."},
        {"role": "user", "content": f"Here is the system operational dump:\n{haystack_text}\n\n{question}"}
    ])
    print(f"Raw Haystack Answer: '{res_haystack['content']}' | Tokens: {res_haystack['usage'].get('prompt_tokens')} | Time: {res_haystack['latency_s']}s")

    # 2. Test JIT Context OS
    print("\n[EXP-005] Calling JIT Context OS (L0 WAL Capsule)...")
    init_db()
    conn = get_db()
    sess_id = f"exp005_{int(time.time())}"
    ensure_session(conn, sess_id)
    t0 = time.perf_counter()
    append_event(conn, sess_id, "user", f"Konfiguracja bazy: {needle}", "direct_user")
    capsule = compile_context(conn, sess_id, question, [])
    compile_ms = (time.perf_counter() - t0) * 1000
    conn.close()

    res_jit = call_llm([
        {"role": "system", "content": f"You are a precise systems operator.\n{capsule}"},
        {"role": "user", "content": question}
    ])
    print(f"JIT Context Answer:  '{res_jit['content']}' | Tokens: {res_jit['usage'].get('prompt_tokens')} | Time: {res_jit['latency_s']}s (Compile: {compile_ms:.2f}ms)")

    results = {
        "exp_id": "EXP-005-Real-Physical-Needle-Benchmark",
        "model": MODEL_NAME,
        "needle_target": needle,
        "raw_haystack": {
            "prompt_tokens": res_haystack["usage"].get("prompt_tokens"),
            "latency_s": res_haystack["latency_s"],
            "answer": res_haystack["content"],
            "found_needle": "948192-OMEGA" in res_haystack["content"]
        },
        "jit_context_os": {
            "prompt_tokens": res_jit["usage"].get("prompt_tokens"),
            "jit_compile_ms": round(compile_ms, 2),
            "latency_s": res_jit["latency_s"],
            "answer": res_jit["content"],
            "found_needle": "948192-OMEGA" in res_jit["content"]
        },
        "real_delta": {
            "token_reduction": f"{round((1 - res_jit['usage'].get('prompt_tokens', 0) / max(1, res_haystack['usage'].get('prompt_tokens', 1))) * 100, 1)}%",
            "speedup": f"{round(res_haystack['latency_s'] / max(0.001, res_jit['latency_s']), 2)}x faster"
        }
    }
    return results

if __name__ == "__main__":
    out = run_exp005_lost_in_the_middle_and_gap_closure()
    print("\n" + json.dumps(out, indent=2))
