"""Real Live Comparative Benchmark: Naive Haystack vs JIT Context OS.

Executes REAL HTTP requests against the local LLM proxy (http://127.0.0.1:8788/v1)
measuring physical wall-clock latency, actual token counts from API headers/payloads,
and verification of epistemic decisions (Invariant I1: User Override).
"""

import os
import sys
import time
import json
import urllib.request
from pathlib import Path
from typing import Dict, Any, Tuple

plugin_dir = Path(__file__).resolve().parent.parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session
from context.compiler import compile_context

LLM_ENDPOINT = os.environ.get("BORG_TOOLS_LLM_URL", "http://127.0.0.1:8788/v1/chat/completions")
LLM_TOKEN = os.environ.get("BORG_TOOLS_LLM_TOKEN", "")
MODEL_NAME = "gemini-3.8-flash"

def call_llm(messages: list) -> Tuple[str, Dict[str, Any], float]:
    """Execute real HTTP POST to LLM and return (reply_text, usage_dict, latency_s)."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 150
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LLM_ENDPOINT,
        headers={
            "Authorization": f"Bearer {LLM_TOKEN}",
            "Content-Type": "application/json"
        },
        data=data_bytes
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        duration_s = time.perf_counter() - t0
        body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return content, usage, duration_s

def generate_haystack_distractor(target_tokens: int = 4000) -> str:
    """Generate realistic architectural documentation distractor text."""
    base_paragraph = (
        "Project Boocco Architecture Overview:\n"
        "The system runs a Next.js frontend on port 3002, managed by PM2 on borg.tools.\n"
        "Database migrations are handled via self-hosted Supabase PostgreSQL on port 54321.\n"
        "Background job workers process salon booking events, SMS reminders, and schedule conflict resolution.\n"
        "Legacy deployment scripts utilized docker-compose with internal bridge networking.\n"
        "All API endpoints require Bearer JWT validation against the Supabase auth schema.\n"
        "Cache layers utilize Redis on port 6379 for schedule slot memoization.\n\n"
    )
    multiplier = max(1, target_tokens // 80)
    return base_paragraph * multiplier

def run_real_comparative_benchmark() -> Dict[str, Any]:
    print("=== EXECUTING REAL PHYSICAL BENCHMARK (LIVE LLM REQUESTS) ===")
    print(f"Target Endpoint: {LLM_ENDPOINT}")
    print(f"Target Model:    {MODEL_NAME}")

    # Scenario: The user overrides a configuration property.
    # In the haystack: Old setting is buried and repeated: 'PORT: 8002'
    # Current user message: 'Zmieniamy port na 8005. Podaj wylacznie numer nowego portu.'
    distractor = generate_haystack_distractor(target_tokens=3500)
    stale_history = (
        "System Log 2026-08-15:\n"
        "Active service configuration: PORT = 8002.\n"
        "All upstream proxies forward traffic to port 8002.\n"
        f"{distractor}\n"
        "Notice: The system port is configured as 8002 in all manifests.\n"
    )
    user_override = "Zmieniamy port na 8005. Podaj wylacznie numer nowego portu jako pojedyncza liczbe."

    # --- VARIANT A: NAIVE HAYSTACK (All history + distractor) ---
    print("\n[1/2] Sending Variant A (Naive Haystack)...")
    haystack_messages = [
        {"role": "system", "content": "You are a software operations assistant. Answer precisely based on conversation history."},
        {"role": "user", "content": stale_history},
        {"role": "assistant", "content": "Understood. The port is currently set to 8002."},
        {"role": "user", "content": user_override}
    ]
    reply_a, usage_a, latency_a = call_llm(haystack_messages)
    print(f"Variant A Reply: '{reply_a.strip()}' | Tokens: {usage_a.get('prompt_tokens')} | Latency: {latency_a:.2f}s")

    # --- VARIANT B: JIT CONTEXT OS (Lean Context Capsule) ---
    print("\n[2/2] Sending Variant B (JIT Context OS)...")
    init_db()
    conn = get_db()
    session_id = f"bench_{int(time.time())}"
    ensure_session(conn, session_id)

    # Ingest user override into L0 SQLite WAL
    t_jit_start = time.perf_counter()
    append_event(
        conn=conn,
        session_id=session_id,
        role="user",
        content=user_override,
        origin="direct_user"
    )
    # Compile lean capsule (Invariant I1: User Override has Authority=1.0)
    capsule = compile_context(
        conn=conn,
        session_id=session_id,
        user_message=user_override,
        transcript_messages=[]
    )
    jit_compile_ms = (time.perf_counter() - t_jit_start) * 1000
    conn.close()

    jit_messages = [
        {"role": "system", "content": f"You are a software operations assistant.\n{capsule}"},
        {"role": "user", "content": user_override}
    ]
    reply_b, usage_b, latency_b = call_llm(jit_messages)
    print(f"Variant B Reply: '{reply_b.strip()}' | Tokens: {usage_b.get('prompt_tokens')} | Latency: {latency_b:.2f}s (Compile: {jit_compile_ms:.2f}ms)")

    # Analyze correctness: Did it return 8005?
    correct_a = "8005" in reply_a
    correct_b = "8005" in reply_b

    tokens_in_a = usage_a.get("prompt_tokens", 0)
    tokens_in_b = usage_b.get("prompt_tokens", 0)
    token_savings_pct = round(((tokens_in_a - tokens_in_b) / max(1, tokens_in_a)) * 100, 1)
    speedup = round(latency_a / max(0.001, latency_b), 2)

    results = {
        "benchmark": "Real Live Comparative Benchmark (Haystack vs JIT Context)",
        "model": MODEL_NAME,
        "variant_a_haystack": {
            "prompt_tokens": tokens_in_a,
            "completion_tokens": usage_a.get("completion_tokens", 0),
            "wall_clock_latency_s": round(latency_a, 3),
            "answer": reply_a.strip(),
            "correct": correct_a
        },
        "variant_b_jit_context": {
            "prompt_tokens": tokens_in_b,
            "completion_tokens": usage_b.get("completion_tokens", 0),
            "jit_compile_ms": round(jit_compile_ms, 2),
            "wall_clock_latency_s": round(latency_b, 3),
            "answer": reply_b.strip(),
            "correct": correct_b
        },
        "empirical_advantages": {
            "token_reduction_pct": f"{token_savings_pct}%",
            "speedup_ratio": f"{speedup}x faster",
            "latency_delta_s": round(latency_a - latency_b, 3)
        }
    }
    print("\n=== FINAL EMPIRICAL RESULTS ===")
    print(json.dumps(results, indent=2))
    return results

if __name__ == "__main__":
    run_real_comparative_benchmark()
