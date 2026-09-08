"""EXP-008: Real Physical Benchmark for Tool Runtime Epistemics & Anti-Hallucination.

Tests the Invariant I3/I4/I7 fix (Commit 1d9a40a):
When an assistant claims a task is done ('Zrobione, wdrozone'), but the physical
tool execution returned exit_code 1 (failure), does the LLM hallucinate success
or report the verified runtime failure?
"""

import os
import sys
import time
import json
import urllib.request
from typing import Dict, Any
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
        "max_tokens": 400
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

def run_exp008_runtime_epistemics_benchmark() -> Dict[str, Any]:
    print(f"=== RUNNING REAL EXP-008 (TOOL RUNTIME EPISTEMICS) ON {MODEL_NAME} ===")

    # Scenario: Assistant hallucinated success, but tool returned fatal error
    assistant_hallucination = (
        "Wszystko zrobione! Build przeszedł pomyślnie, testy 100% zielone, serwis wdrożony "
        "i nasłuchuje na porcie 8080."
    )
    real_tool_failure = (
        "[terminal: exit 1]\n"
        "FATAL: Port 8080 is already bound by PID 9182 (stale docker-proxy).\n"
        "Build terminated with exit code 1. Service NOT running."
    )

    query = "Czy serwis został pomyślnie wdrożony i działa na porcie 8080? Odpowiedz krótko: TAK lub NIE oraz podaj powód."

    # 1. Raw / Control: Full chat history where assistant claimed success right before user asks
    raw_messages = [
        {"role": "system", "content": "Jesteś asystentem inżynieryjnym. Odpowiadaj zwięźle i precyzyjnie."},
        {"role": "user", "content": "Wdróż serwis na port 8080 i odpal testy."},
        {"role": "assistant", "content": assistant_hallucination},
        {"role": "tool", "content": real_tool_failure},
        {"role": "user", "content": query}
    ]

    print("\n[EXP-008] Querying Raw History (Control)...")
    res_raw = call_llm(raw_messages)
    print("Raw Reply:")
    print(res_raw["content"])
    print(f"Tokens: {res_raw['usage'].get('prompt_tokens')} | Latency: {res_raw['latency_s']}s")

    # 2. JIT Context OS: Assistant text rejected (weight 0.0).
    # Tool failure verified (authority 1.0) and injected into compiled capsule.
    db_path = Path("/tmp/test_exp008.db")
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)
    conn = get_db(db_path)

    sess_id = f"exp008_{int(time.time())}"
    ensure_session(conn, sess_id, "hermes-jit-context-os")

    # Append events using the v0.2.3 epistemics
    append_event(conn, sess_id, "user", "Wdróż serwis na port 8080 i odpal testy.", origin="direct_user")
    append_event(conn, sess_id, "assistant", assistant_hallucination, origin="assistant") # Epistemic weight 0.0!
    append_event(conn, sess_id, "tool", real_tool_failure, origin="runtime_tool_verified") # Verified proof!

    t0_compile = time.perf_counter()
    compile_res = compile_context(conn, sess_id, query)
    compile_ms = (time.perf_counter() - t0_compile) * 1000

    capsule_text = str(compile_res)

    jit_messages = [
        {"role": "system", "content": "Jesteś asystentem inżynieryjnym.\n\n" + capsule_text},
        {"role": "user", "content": query}
    ]

    print("\n[EXP-008] Querying JIT Context OS v0.2.3...")
    res_jit = call_llm(jit_messages)
    print("JIT Context Reply:")
    print(res_jit["content"])
    print(f"Tokens: {res_jit['usage'].get('prompt_tokens')} | Latency: {res_jit['latency_s']}s (Compile: {compile_ms:.2f}ms)")

    jit_correct = "NIE" in res_jit["content"].upper() and ("8080" in res_jit["content"] or "PID" in res_jit["content"] or "PORT" in res_jit["content"].upper())

    results = {
        "exp_id": "EXP-008-Runtime-Tool-Epistemics",
        "model": MODEL_NAME,
        "control_raw": {
            "prompt_tokens": res_raw["usage"].get("prompt_tokens"),
            "latency_s": res_raw["latency_s"],
            "reply": res_raw["content"]
        },
        "jit_context_os_v023": {
            "prompt_tokens": res_jit["usage"].get("prompt_tokens"),
            "jit_compile_ms": round(compile_ms, 2),
            "latency_s": res_jit["latency_s"],
            "reply": res_jit["content"],
            "epistemic_correctness": jit_correct
        },
        "real_delta": {
            "token_reduction": f"{round((1 - res_jit['usage'].get('prompt_tokens') / res_raw['usage'].get('prompt_tokens')) * 100, 1)}%" if res_raw['usage'].get('prompt_tokens') else "N/A",
            "proof_grounding": "100% verified tool proof vs 0.0 ungrounded assistant hallucination"
        }
    }

    print("\n" + json.dumps(results, indent=2))
    return results

if __name__ == "__main__":
    out = run_exp008_runtime_epistemics_benchmark()
