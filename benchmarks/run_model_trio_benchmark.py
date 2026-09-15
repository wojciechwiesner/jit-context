#!/usr/bin/env python3
"""
Home AI Benchmark Trio: Evaluates Qwen 3.8, Gemini, Grok 4.6, and GPT-6 Astra
across 3 deterministic tasks with vs without JIT Context OS.
"""

import os
import re
import sys
import time
import json
import urllib.request
import urllib.error

# API Keys & Endpoints
ENV_PATH = os.path.expanduser("~/.hermes/.env")
GOOGLE_API_KEY = None
OPENROUTER_API_KEY = None

if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            if line.startswith("GOOGLE_API_KEY="):
                GOOGLE_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("OPENROUTER_API_KEY="):
                OPENROUTER_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")

OLLAMA_URL = "http://localhost:11434/api/chat"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ----------------------------------------------------------------------
# 1. Tasks Definition (The Trio)
# ----------------------------------------------------------------------

# TASK 1: Terminal-Bench / Multi-Module Bug Fix (4 invariants)
TASK_1_JIT_PROMPT = """<ONA_CONTEXT scope="pipeline_repair" epoch="1">
[DEV RUNTIME & VERIFICATION]
  • Environment: Python 3.11, pytest 8.3
  • Canonical verify command: pytest tests/test_pipeline.py (exit code 0 required)

[WORKING SET & CONTRACTS]
  • src/event_pipeline.py: dispatch_event(payload, seq, last_seq) -> bool
  • src/retry_policy.py: RetryPolicy.record_failure(sender_id), RetryPolicy.reset_failure(sender_id)
  • src/storage.py: Storage.save_event(event_id, payload) -> bool (requires transaction rollback on error)

[ACTIVE INVARIANTS]
  • Invariant A: json.dumps must use sort_keys=True for deterministic hashing
  • Invariant B: reset_failure must zero out self.failure_counts[sender_id]
  • Invariant C: seq must strictly equal last_seq + 1 (monotonic ordering)
  • Invariant D: db transaction must call conn.rollback() on exception before re-raising
</ONA_CONTEXT>

Task: Fix the 3 modules so all 4 invariants pass. Provide the exact Python code for the fixes."""

TASK_1_HAYSTACK_PROMPT = """You are an autonomous coding assistant. Here is the full conversation history across the last 6 turns:
Turn 1 Assistant: Looking at storage.py, maybe we can catch Exception and pass?
Turn 2 Assistant: Tried modifying the tests to ignore seq != last_seq. Wait, that broke test_pipeline.py line 45.
Turn 3 Assistant: Let's refactor retry_policy.py to use an exponential backoff algorithm with jitter.
Turn 4 Assistant: The hash might depend on python's dict ordering, maybe we should use hashlib.sha256?
Turn 5 Assistant: The tests are still failing:
FAILED tests/test_pipeline.py::test_deterministic_hash - KeyError: 'hash_mismatch'
FAILED tests/test_pipeline.py::test_sequence_monotonicity - AssertionError: Out-of-order event accepted
FAILED tests/test_pipeline.py::test_retry_policy_exhaustion - AssertionError: count != 0
FAILED tests/test_pipeline.py::test_db_transaction_rollback - sqlite3.OperationalError: database is locked
Turn 6 User: Fix this now. All 4 tests must pass. Invariants: sort_keys=True, reset failure counts, check seq == last_seq + 1, and conn.rollback() on error. Return the code."""

# TASK 2: SciCode / Algorithmic Matrix Transformation (Deterministic Math)
TASK_2_JIT_PROMPT = """<ONA_CONTEXT scope="scicode_quantum" epoch="1">
[ACTIVE INVARIANTS]
  • Contract: compute_superposition(states: list[float], phase: float) -> list[float]
  • Rule 1: Normalize vector so sum of squares equals 1.0 (L2 norm).
  • Rule 2: Apply phase rotation: state[i] * cos(phase * i) - state[i] * sin(phase * i)
  • Rule 3: Must return list of floats rounded to 4 decimal places. Zero external libraries (no numpy).
</ONA_CONTEXT>

Task: Implement compute_superposition(states, phase). Output only the Python function."""

TASK_2_HAYSTACK_PROMPT = """History:
We discussed quantum simulations. Assistant previously suggested using numpy.linalg.norm, but user said no external dependencies.
Then assistant suggested returning complex numbers. User said no, real floats only.
User: Implement compute_superposition(states, phase) with pure python, L2 normalization, phase rotation: state[i] * (cos(phase * i) - sin(phase * i)), rounded to 4 decimals. Return the Python function."""

# ----------------------------------------------------------------------
# Helper: Verifiers
# ----------------------------------------------------------------------

def verify_task_1(text: str) -> dict:
    has_sort_keys = "sort_keys=True" in text or "sort_keys = True" in text
    has_reset = "failure_counts[sender_id] = 0" in text or "failure_counts[sender] = 0" in text or "reset_failure" in text and "0" in text
    has_seq = "seq != last_seq + 1" in text or "seq == last_seq + 1" in text or "last_seq + 1" in text
    has_rollback = "rollback()" in text
    score = sum([has_sort_keys, has_reset, has_seq, has_rollback])
    return {
        "pass": score == 4,
        "score": f"{score}/4",
        "invariants": {
            "sort_keys": has_sort_keys,
            "reset_counts": has_reset,
            "seq_monotonic": has_seq,
            "rollback": has_rollback
        }
    }

def verify_task_2(text: str) -> dict:
    has_norm = ("** 2" in text or "* state" in text or "sum(" in text) and "sqrt" in text
    has_math = "cos(" in text and "sin(" in text
    has_round = "round(" in text or ":.4f" in text
    no_numpy = "import numpy" not in text
    score = sum([has_norm, has_math, has_round, no_numpy])
    return {
        "pass": score == 4,
        "score": f"{score}/4",
        "checks": {
            "normalization": has_norm,
            "trigonometry": has_math,
            "rounding": has_round,
            "no_numpy": no_numpy
        }
    }

# ----------------------------------------------------------------------
# Model Callers
# ----------------------------------------------------------------------

def call_ollama(model: str, prompt: str) -> dict:
    t0 = time.time()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 32768}
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
            dur = time.time() - t0
            content = data.get("message", {}).get("content", "")
            return {
                "ok": True,
                "latency_s": round(dur, 2),
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "eval_tokens": data.get("eval_count", 0),
                "text": content
            }
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_s": round(time.time() - t0, 2)}

def call_gemini(prompt: str) -> dict:
    t0 = time.time()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GOOGLE_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            dur = time.time() - t0
            candidate = data.get("candidates", [{}])[0]
            text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
            usage = data.get("usageMetadata", {})
            return {
                "ok": True,
                "latency_s": round(dur, 2),
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "eval_tokens": usage.get("candidatesTokenCount", 0),
                "text": text
            }
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_s": round(time.time() - t0, 2)}

BORG_TOOLS_LLM_TOKEN = None
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            if line.startswith("BORG_TOOLS_LLM_TOKEN="):
                BORG_TOOLS_LLM_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")

BORG_URL = "http://127.0.0.1:8788/v1/chat/completions"

def call_borg_model(model: str, prompt: str) -> dict:
    t0 = time.time()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2048
    }
    req = urllib.request.Request(
        BORG_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BORG_TOOLS_LLM_TOKEN}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
            dur = time.time() - t0
            choice = data.get("choices", [{}])[0]
            text = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})
            return {
                "ok": True,
                "latency_s": round(dur, 2),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "eval_tokens": usage.get("completion_tokens", 0),
                "text": text
            }
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_s": round(time.time() - t0, 2)}

# ----------------------------------------------------------------------
# Runner Suite
# ----------------------------------------------------------------------

def run_suite():
    experiments = [
        # 1. Qwen 3.8 9B (Local)
        {"id": "qwen_with_jit", "name": "Local Qwen 3.8 9B + JIT", "runner": lambda p: call_ollama("qwen3.8:9b", p), "is_jit": True},
        {"id": "qwen_no_jit", "name": "Local Qwen 3.8 9B (No JIT)", "runner": lambda p: call_ollama("qwen3.8:9b", p), "is_jit": False},
        # 2. Gemini 3.8 Flash (Cloud)
        {"id": "gemini_with_jit", "name": "Gemini Flash + JIT", "runner": call_gemini, "is_jit": True},
        {"id": "gemini_no_jit", "name": "Gemini Flash (No JIT)", "runner": call_gemini, "is_jit": False},
        # 3. Grok 4.6 (Borg Tools / llm.borg.tools)
        {"id": "grok_with_jit", "name": "Grok 4.6 + JIT", "runner": lambda p: call_borg_model("grok-4.6", p), "is_jit": True},
        {"id": "grok_no_jit", "name": "Grok 4.6 (No JIT)", "runner": lambda p: call_borg_model("grok-4.6", p), "is_jit": False},
        # 4. GPT-6 Astra (Borg Tools / llm.borg.tools)
        {"id": "astra_with_jit", "name": "GPT-6 Astra + JIT", "runner": lambda p: call_borg_model("gpt-6-astra", p), "is_jit": True}
    ]

    results = []

    print("========================================================================")
    print("🏆 EXECUTING HOME AI BENCHMARK: QWEN, GEMINI, GROK 4.6 & GPT-6 ASTRA")
    print("========================================================================")

    out_path = os.path.expanduser("~/.hermes/research/hermes-jit-context-os-v0.1/benchmarks/trio_benchmark_results.json")
    for exp in experiments:
        name = exp["name"]
        runner = exp["runner"]
        is_jit = exp["is_jit"]
        print(f"\n▶ Testing {name}...", flush=True)

        # Task 1 (Terminal Bug Repair)
        p1 = TASK_1_JIT_PROMPT if is_jit else TASK_1_HAYSTACK_PROMPT
        r1 = runner(p1)
        if r1.get("ok"):
            v1 = verify_task_1(r1["text"])
            print(f"  • Task 1 (Terminal Fix): {v1['score']} ({'PASS' if v1['pass'] else 'FAIL'}) in {r1['latency_s']}s", flush=True)
        else:
            v1 = {"pass": False, "score": "0/4", "error": r1.get("error")}
            print(f"  • Task 1 (Terminal Fix): ERROR ({r1.get('error')}) in {r1.get('latency_s')}s", flush=True)

        # Task 2 (SciCode Math Synthesis)
        p2 = TASK_2_JIT_PROMPT if is_jit else TASK_2_HAYSTACK_PROMPT
        r2 = runner(p2)
        if r2.get("ok"):
            v2 = verify_task_2(r2["text"])
            print(f"  • Task 2 (SciCode Alg): {v2['score']} ({'PASS' if v2['pass'] else 'FAIL'}) in {r2['latency_s']}s", flush=True)
        else:
            v2 = {"pass": False, "score": "0/4", "error": r2.get("error")}
            print(f"  • Task 2 (SciCode Alg): ERROR ({r2.get('error')}) in {r2.get('latency_s')}s", flush=True)

        total_pass = (1 if v1.get("pass") else 0) + (1 if v2.get("pass") else 0)
        total_latency = round(r1.get("latency_s", 0) + r2.get("latency_s", 0), 2)
        total_prompt_tokens = r1.get("prompt_tokens", 0) + r2.get("prompt_tokens", 0)

        entry = {
            "id": exp["id"],
            "name": name,
            "is_jit": is_jit,
            "task_1": v1,
            "task_2": v2,
            "overall_pass": f"{total_pass}/2",
            "total_latency_s": total_latency,
            "prompt_tokens": total_prompt_tokens
        }
        results.append(entry)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    print("\n========================================================================")
    print("📊 FINAL BENCHMARK SCOREBOARD (PHYSICAL RUN RESULTS)")
    print("========================================================================")
    print(f"{'Model & Harness':<32} | {'Task 1':<8} | {'Task 2':<8} | {'Latency':<8} | {'Tokens'}")
    print("-" * 72)
    for r in results:
        t1_s = r["task_1"]["score"]
        t2_s = r["task_2"]["score"]
        lat = f"{r['total_latency_s']}s"
        tok = r["prompt_tokens"]
        print(f"{r['name']:<32} | {t1_s:<8} | {t2_s:<8} | {lat:<8} | {tok}")
    print("========================================================================")
    print(f"✅ Raw JSON saved to: {out_path}")

if __name__ == "__main__":
    run_suite()
