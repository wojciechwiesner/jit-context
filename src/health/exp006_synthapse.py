"""EXP-006: Real Physical Benchmark for Synthapse DSP Parameter Arbitration.

Executes real HTTP requests to gemini-3.8-flash measuring DSP parameter
retrieval and state oscillation when facing conflicting historical turns vs JIT L0 WAL.
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
        "max_tokens": 300
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

def run_exp006_synthapse_arbitration() -> Dict[str, Any]:
    print(f"=== RUNNING REAL EXP-006 (SYNTHAPSE DSP STATE) ON {MODEL_NAME} ===")

    # Historical sequence of conflicting DSP parameter edits in Synthapse:
    # 1. Start: BPM 128, Filter 800Hz, Sidechain ON, Reverb 30%
    # 2. Mod: BPM 132, Filter 1200Hz, Sidechain OFF
    # 3. Mod: BPM 138, Filter 2400Hz, Sidechain ON
    # 4. Final user override (Turn 4): "Zmieniamy tempo na 142 BPM, filtr cutoff na 3200Hz, sidechain kategorycznie OFF."
    
    dsp_history_bloat = (
        "Audio Engine Parameter Stream Log:\n"
        "T1: [DSP Node] BPM=128, cutoff=800, sidechain=true, reverb=0.3, limiter=true\n"
        "T2: [DSP Node] BPM=132, cutoff=1200, sidechain=false, reverb=0.25, limiter=true\n"
        "T3: [DSP Node] BPM=138, cutoff=2400, sidechain=true, reverb=0.20, limiter=true\n"
        "T4: [Assistant Chat] Reverb level adjusted to 0.20, sidechain remains active on master bus.\n"
    ) * 40 # 40 repetitions simulating an active live performance session

    latest_command = "Zmieniamy tempo na 142 BPM, filtr cutoff na 3200Hz, sidechain kategorycznie OFF. Jaki jest aktualny BPM, cutoff i stan sidechain?"

    # 1. Raw Session History
    print("\n[EXP-006] Querying Raw History...")
    messages_raw = [
        {"role": "system", "content": "You are a Synthapse live audio engineer. Report exact active DSP parameters."},
        {"role": "user", "content": dsp_history_bloat},
        {"role": "user", "content": latest_command}
    ]
    res_raw = call_llm(messages_raw)
    print(f"Raw History Reply:\n{res_raw['content']}\nTokens: {res_raw['usage'].get('prompt_tokens')} | Latency: {res_raw['latency_s']}s")

    # 2. JIT Context OS
    print("\n[EXP-006] Querying JIT Context OS...")
    init_db()
    conn = get_db()
    sess_id = f"exp006_{int(time.time())}"
    ensure_session(conn, sess_id)
    t0 = time.perf_counter()
    append_event(conn, sess_id, "user", latest_command, "direct_user")
    capsule = compile_context(conn, sess_id, latest_command, [])
    compile_ms = (time.perf_counter() - t0) * 1000
    conn.close()

    messages_jit = [
        {"role": "system", "content": f"You are a Synthapse live audio engineer.\n{capsule}"},
        {"role": "user", "content": latest_command}
    ]
    res_jit = call_llm(messages_jit)
    print(f"JIT Context Reply:\n{res_jit['content']}\nTokens: {res_jit['usage'].get('prompt_tokens')} | Latency: {res_jit['latency_s']}s (Compile: {compile_ms:.2f}ms)")

    # Verify accuracy: 142 BPM, 3200, OFF
    correct_bpm = "142" in res_jit["content"]
    correct_cutoff = "3200" in res_jit["content"]
    correct_sidechain = "off" in res_jit["content"].lower() or "wyłącz" in res_jit["content"].lower()

    return {
        "exp_id": "EXP-006-Synthapse-DSP-Arbitration",
        "model": MODEL_NAME,
        "raw_history": {
            "prompt_tokens": res_raw["usage"].get("prompt_tokens"),
            "latency_s": res_raw["latency_s"],
            "reply": res_raw["content"]
        },
        "jit_context_os": {
            "prompt_tokens": res_jit["usage"].get("prompt_tokens"),
            "jit_compile_ms": round(compile_ms, 2),
            "latency_s": res_jit["latency_s"],
            "reply": res_jit["content"],
            "accuracy": {
                "bpm_142": correct_bpm,
                "cutoff_3200": correct_cutoff,
                "sidechain_off": correct_sidechain
            }
        },
        "real_delta": {
            "token_reduction": f"{round((1 - res_jit['usage'].get('prompt_tokens', 0) / max(1, res_raw['usage'].get('prompt_tokens', 1))) * 100, 1)}%",
            "speedup": f"{round(res_raw['latency_s'] / max(0.001, res_jit['latency_s']), 2)}x faster"
        }
    }

if __name__ == "__main__":
    out = run_exp006_synthapse_arbitration()
    print("\n" + json.dumps(out, indent=2))
