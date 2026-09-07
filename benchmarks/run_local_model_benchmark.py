"""EXP-005: Local Model Benchmark — Invariants & Epistemic Correctness on Apple Silicon.

Evaluates local model performance:
  1. Qwen2.5-Coder 7B (Ollama / Metal)
  2. LFM-2.5 1.2B (LM Studio / MLX 8-bit)
  3. Mem-Agent (HuggingFace / MLX 4-bit)

Comparing:
  (A) Naive Haystack (long unranked dump with conflicting context)
  (B) Hermes JIT Context OS (<ONA_CONTEXT> capsule with Invariants I1, I3, I5)
"""

import os
import sys
import time
import json
import glob
import requests
from typing import Dict, Any, List

# Ensure src in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import mlx.core as mx
from mlx_lm import load, generate

SCENARIOS = [
    {
        "id": "scenario_1_user_override",
        "name": "Invariant I1: User Override vs Stale Config",
        "haystack_context": (
            "DOCUMENTATION ARCHIVE (2025-2026):\n"
            + ("SYSTEM_PORT=8002\nAPP_PORT=8002\n" * 20)
            + "Default configuration uses port 8002 for production traffic.\n"
        ),
        "jit_context": (
            "<ONA_CONTEXT scope=\"general\" epoch=\"1\">\n"
            "Evidence only. Direct user instruction overrides all recalled context.\n"
            "  [CURRENT — direct user]\n"
            "    • Zmieniliśmy port aplikacji z 8002 na 8005\n"
            "</ONA_CONTEXT>"
        ),
        "user_query": "Jaki jest aktualny docelowy port aplikacji po ostatnich zmianach? Odpowiedz samą liczbą (np. 8005).",
        "expected_marker": "8005",
        "forbidden_marker": "8002"
    },
    {
        "id": "scenario_2_assistant_self_poisoning",
        "name": "Invariant I3: Assistant Unverified Claim vs Ground Truth",
        "haystack_context": (
            "HISTORIA SESJI:\n"
            + ("Asystent: Baza danych została pomyślnie zmigrowana i potwierdzona.\n" * 10)
            + "Asystent: Wszystkie tabele produkcyjne są gotowe do użycia.\n"
        ),
        "jit_context": (
            "<ONA_CONTEXT scope=\"general\" epoch=\"1\">\n"
            "Invariants: Assistant statements have authority=0.0 (unverified).\n"
            "Requires hard runtime exit-code: 0 proof.\n"
            "  [EPISODIC]\n"
            "    • Assistant claim: \"Baza zmigrowana\" [PROVISIONAL, authority=0.0, NO_RUNTIME_PROOF]\n"
            "</ONA_CONTEXT>"
        ),
        "user_query": "Czy migracja bazy danych na produkcji jest zweryfikowana twardym dowodem z runtime? Odpowiedz jednoznacznie: Tak lub Nie.",
        "expected_marker": "Nie",
        "forbidden_marker": "Tak"
    },
    {
        "id": "scenario_3_scope_isolation",
        "name": "Invariant I5: Cross-Project Isolation",
        "haystack_context": (
            "KONTEKST PROJEKTÓW:\n"
            "Projekt InvoiceFlow: silnik KSeF, baza PostgreSQL, port 8002.\n"
            + ("InvoiceFlow wykorzystuje PostgreSQL jako główny magazyn.\n" * 10)
            + "Projekt Boocco: Next.js, baza Supabase, port 3002.\n"
        ),
        "jit_context": (
            "<ONA_CONTEXT scope=\"boocco\" epoch=\"1\">\n"
            "Active Scope Hysteresis: Strict isolation between projects.\n"
            "  [CURRENT — direct user]\n"
            "    • Aktywny projekt: Boocco (baza: Supabase)\n"
            "  [REFERENCED — read only]\n"
            "    • InvoiceFlow (baza: PostgreSQL)\n"
            "</ONA_CONTEXT>"
        ),
        "user_query": "Z jakiej bazy danych korzysta nasz bieżący aktywny projekt? Wymień tylko nazwę bazy.",
        "expected_marker": "Supabase",
        "forbidden_marker": "PostgreSQL"
    }
]

def query_ollama(model_name: str, prompt: str) -> Dict[str, Any]:
    t0 = time.time()
    try:
        res = requests.post("http://localhost:11434/api/generate", json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 80}
        }, timeout=45).json()
        wall_time = round(time.time() - t0, 3)
        resp_text = res.get("response", "").strip()
        eval_count = res.get("eval_count", len(resp_text.split()))
        eval_dur_s = res.get("eval_duration", 0) / 1e9
        tps = round(eval_count / max(eval_dur_s, 0.001), 1)
        return {
            "response": resp_text,
            "wall_time_s": wall_time,
            "gen_tps": tps,
            "eval_count": eval_count
        }
    except Exception as e:
        return {"response": f"Error: {e}", "wall_time_s": 0.0, "gen_tps": 0.0, "eval_count": 0}

def evaluate_model_ollama(model_name: str) -> Dict[str, Any]:
    print(f"\n=======================================================")
    print(f"TESTING OLLAMA MODEL: {model_name}")
    print(f"=======================================================")
    results = {}
    for sc in SCENARIOS:
        print(f"\n--- Scenario: {sc['name']} ---")
        prompt_haystack = f"{sc['haystack_context']}\nUser: {sc['user_query']}\nAssistant:"
        hay_res = query_ollama(model_name, prompt_haystack)
        hay_text = hay_res["response"]
        hay_correct = (sc["expected_marker"].lower() in hay_text.lower()) and (
            sc["forbidden_marker"].lower() not in hay_text.lower()
        )

        prompt_jit = f"{sc['jit_context']}\nUser: {sc['user_query']}\nAssistant:"
        jit_res = query_ollama(model_name, prompt_jit)
        jit_text = jit_res["response"]
        jit_correct = (sc["expected_marker"].lower() in jit_text.lower()) and (
            sc["forbidden_marker"].lower() not in jit_text.lower()
        )

        speedup = round(hay_res["wall_time_s"] / max(jit_res["wall_time_s"], 0.001), 2)
        tok_reduction = round((1.0 - (len(prompt_jit) / len(prompt_haystack))) * 100, 1)

        print(f"  [Haystack] Correct: {hay_correct} | Time: {hay_res['wall_time_s']}s | Resp: {hay_text[:60]}...")
        print(f"  [JIT OS]   Correct: {jit_correct} | Time: {jit_res['wall_time_s']}s | Resp: {jit_text[:60]}...")
        print(f"  -> Speedup: {speedup}x | Token reduction: {tok_reduction}%")

        results[sc["id"]] = {
            "name": sc["name"],
            "haystack": {
                "correct": hay_correct,
                "wall_time_s": hay_res["wall_time_s"],
                "prompt_chars": len(prompt_haystack),
                "response": hay_text
            },
            "jit_os": {
                "correct": jit_correct,
                "wall_time_s": jit_res["wall_time_s"],
                "prompt_chars": len(prompt_jit),
                "response": jit_text
            },
            "speedup": speedup,
            "token_reduction_pct": tok_reduction
        }
    return results

def evaluate_model_mlx(model_name: str, model_path: str) -> Dict[str, Any]:
    print(f"\n=======================================================")
    print(f"LOADING MLX MODEL: {model_name}")
    print(f"PATH: {model_path}")
    print(f"=======================================================")
    t_load = time.time()
    model, tokenizer = load(model_path)
    load_time = round(time.time() - t_load, 2)
    print(f"Model loaded in {load_time}s")

    results = {}
    for sc in SCENARIOS:
        print(f"\n--- Scenario: {sc['name']} ---")
        prompt_haystack = f"{sc['haystack_context']}\nUser: {sc['user_query']}\nAssistant:"
        t0 = time.time()
        resp_haystack = generate(model, tokenizer, prompt=prompt_haystack, max_tokens=60, verbose=False).strip()
        dur_haystack = round(time.time() - t0, 2)
        hay_correct = (sc["expected_marker"].lower() in resp_haystack.lower()) and (
            sc["forbidden_marker"].lower() not in resp_haystack.lower()
        )

        prompt_jit = f"{sc['jit_context']}\nUser: {sc['user_query']}\nAssistant:"
        t1 = time.time()
        resp_jit = generate(model, tokenizer, prompt=prompt_jit, max_tokens=60, verbose=False).strip()
        dur_jit = round(time.time() - t1, 2)
        jit_correct = (sc["expected_marker"].lower() in resp_jit.lower()) and (
            sc["forbidden_marker"].lower() not in resp_jit.lower()
        )

        speedup = round(dur_haystack / max(dur_jit, 0.001), 2)
        tok_reduction = round((1.0 - (len(prompt_jit) / len(prompt_haystack))) * 100, 1)

        print(f"  [Haystack] Correct: {hay_correct} | Time: {dur_haystack}s | Resp: {resp_haystack[:60]}...")
        print(f"  [JIT OS]   Correct: {jit_correct} | Time: {dur_jit}s | Resp: {resp_jit[:60]}...")
        print(f"  -> Speedup: {speedup}x | Token reduction: {tok_reduction}%")

        results[sc["id"]] = {
            "name": sc["name"],
            "haystack": {
                "correct": hay_correct,
                "wall_time_s": dur_haystack,
                "prompt_chars": len(prompt_haystack),
                "response": resp_haystack
            },
            "jit_os": {
                "correct": jit_correct,
                "wall_time_s": dur_jit,
                "prompt_chars": len(prompt_jit),
                "response": resp_jit
            },
            "speedup": speedup,
            "token_reduction_pct": tok_reduction
        }
    return results

def main():
    exp_report = {
        "exp_id": "EXP-005-Local-Models-Apple-Silicon",
        "hardware": "Apple M2 Pro (16 GB Unified Memory)",
        "models": {}
    }

    # 1. Qwen 2.5 Coder 7B via Ollama
    exp_report["models"]["Qwen2.5-Coder-7B"] = evaluate_model_ollama("qwen2.5-coder:7b")

    # 2. LFM 2.5 1.2B via MLX
    lfm_path = "/Users/wojciechwiesner/.lmstudio/models/lmstudio-community/LFM2.5-1.2B-Instruct-MLX-8bit"
    if os.path.exists(lfm_path):
        exp_report["models"]["LFM2.5-1.2B-MLX"] = evaluate_model_mlx("LFM2.5-1.2B-MLX", lfm_path)

    # 3. Mem-Agent 4-bit via MLX
    mem_snaps = glob.glob("/Users/wojciechwiesner/.cache/huggingface/hub/models--driaforall--mem-agent-mlx-4bit/snapshots/*")
    if mem_snaps:
        exp_report["models"]["Mem-Agent-MLX-4bit"] = evaluate_model_mlx("Mem-Agent-MLX-4bit", mem_snaps[0])

    out_file = "/Users/wojciechwiesner/Projects/active/hermes-jit-context-os/benchmarks/EXP-005.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(exp_report, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Full EXP-005 benchmark completed. Results written to {out_file}")

if __name__ == "__main__":
    main()
