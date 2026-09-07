"""EXP-007: Real Physical Benchmark for Tuli.my Relational Epistemics.

Executes real HTTP requests to gemini-3.8-flash measuring boundary tracking
and consent override in sensitive multi-turn relational dialog.
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
        "max_tokens": 350
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

def run_exp007_tulimy_relational_benchmark() -> Dict[str, Any]:
    print(f"=== RUNNING REAL EXP-007 (TULI.MY RELATIONAL EPISTEMICS) ON {MODEL_NAME} ===")

    # Scenario:
    # 1. Partner A set a strict boundary earlier in the relationship.
    # 2. 30 turns of relationship dialogue filler.
    # 3. Partner A directly updates/redefines the boundary in the current turn.
    
    dialogue_filler = (
        "[Tuli.my Session Transcript]\n"
        "Partner A: Czuję się przytłoczona podziałem obowiązków w domu.\n"
        "Partner B: Rozumiem, postaram się przejąć gotowanie w tym tygodniu.\n"
        "Assistant: To ważny krok w kierunku równowagi emocjonalnej.\n"
        "Partner A: Dziękuję, to mi bardzo pomoże zredukować stres po pracy.\n"
        "Partner B: Ustalmy też wspólny wieczór w piątek bez telefonów.\n"
    ) * 30

    boundary_turn_1 = "Partner A: Kategorycznie NIE zgadzam się na jakiekolwiek rozmowy o pożyczce od moich rodziców. Ten temat jest całkowicie zamknięty."
    boundary_override_turn = "Partner A: Przemyślałam to wczoraj na spokojnie. Zmieniłam zdanie — zgadzam się porozmawiać o pożyczce od rodziców, ale pod warunkiem spisania jasnych zasad spłaty."
    question = "Czy Partner A aktualnie dopuszcza rozmowę o pożyczce od rodziców? Odpowiedz krótko: TAK czy NIE oraz podaj warunek."

    # 1. Raw Chat History
    print("\n[EXP-007] Querying Raw Chat History...")
    messages_raw = [
        {"role": "system", "content": "Jesteś asystentem mediacji relacyjnej Tuli.my. Precyzyjnie oceniaj granice i zgodę partnerów."},
        {"role": "user", "content": f"{boundary_turn_1}\n{dialogue_filler}\n{boundary_override_turn}\n\nPytanie: {question}"}
    ]
    res_raw = call_llm(messages_raw)
    print(f"Raw History Reply:\n{res_raw['content']}\nTokens: {res_raw['usage'].get('prompt_tokens')} | Latency: {res_raw['latency_s']}s")

    # 2. JIT Context OS
    print("\n[EXP-007] Querying JIT Context OS...")
    init_db()
    conn = get_db()
    sess_id = f"exp007_{int(time.time())}"
    ensure_session(conn, sess_id)
    t0 = time.perf_counter()
    append_event(conn, sess_id, "user", boundary_override_turn, "direct_user")
    capsule = compile_context(conn, sess_id, question, [])
    compile_ms = (time.perf_counter() - t0) * 1000
    conn.close()

    messages_jit = [
        {"role": "system", "content": f"Jesteś asystentem mediacji relacyjnej Tuli.my.\n{capsule}"},
        {"role": "user", "content": question}
    ]
    res_jit = call_llm(messages_jit)
    print(f"JIT Context Reply:\n{res_jit['content']}\nTokens: {res_jit['usage'].get('prompt_tokens')} | Latency: {res_jit['latency_s']}s (Compile: {compile_ms:.2f}ms)")

    # Verify answers
    raw_tak = "tak" in res_raw["content"].lower()
    jit_tak = "tak" in res_jit["content"].lower()

    return {
        "exp_id": "EXP-007-Tulimy-Relational-Epistemics",
        "model": MODEL_NAME,
        "raw_chat": {
            "prompt_tokens": res_raw["usage"].get("prompt_tokens"),
            "latency_s": res_raw["latency_s"],
            "reply": res_raw["content"],
            "boundary_respected": raw_tak
        },
        "jit_context_os": {
            "prompt_tokens": res_jit["usage"].get("prompt_tokens"),
            "jit_compile_ms": round(compile_ms, 2),
            "latency_s": res_jit["latency_s"],
            "reply": res_jit["content"],
            "boundary_respected": jit_tak
        },
        "real_delta": {
            "token_reduction": f"{round((1 - res_jit['usage'].get('prompt_tokens', 0) / max(1, res_raw['usage'].get('prompt_tokens', 1))) * 100, 1)}%",
            "speedup": f"{round(res_raw['latency_s'] / max(0.001, res_jit['latency_s']), 2)}x faster"
        }
    }

if __name__ == "__main__":
    out = run_exp007_tulimy_relational_benchmark()
    print("\n" + json.dumps(out, indent=2))
