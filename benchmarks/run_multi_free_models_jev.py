#!/usr/bin/env python3
"""
Multi-Model Comparative SWE Benchmark with JEV Probabilistic Decision Engine.
Runs 10 tasks across multiple free / low-cost models on 3 arms:
  - Arm 1: BEZ JIT (Raw baseline without capsule)
  - Arm 2: Z JIT (BEZ JEV - Heuristic Token Ranking)
  - Arm 3: Z JIT + JEV (Probabilistic Decision Engine via OpenRouter ~typesafe/jev-latest)
Physical verification: Pytest returncode == 0 on disk.
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.run_swe_10_battle import TASKS, main as run_battle_main

MODELS = [
    {"name": "gemini-3.5-flash-lite", "provider": "gemini", "label": "Google Gemini 3.5 Flash-Lite (Free)"},
    {"name": "gemini-2.5-flash", "provider": "gemini", "label": "Google Gemini 2.5 Flash (Free)"},
    {"name": "qwen/qwen-2.5-7b-instruct", "provider": "openrouter", "label": "Qwen 2.5 7B Instruct (OpenRouter)"}
]

MODES = ["bez_jit", "jit_bez_jev", "jit_z_jev"]
OUT_DIR = ROOT_DIR / "benchmarks" / "results" / "swe_multi_model_jev_10"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("=" * 80)
    print(" 🚀 MULTI-MODEL SWE BENCHMARK: 10 TASKS × 3 ARMS (BEZ JIT vs JIT vs JIT+JEV)")
    print("=" * 80)
    print(f"• Total Models:        {len(MODELS)}")
    for m in MODELS:
        print(f"   - {m['label']} ({m['name']})")
    print(f"• JEV Engine:          ~typesafe/jev-latest (/api/alpha/decisions)")
    print(f"• Tasks per model:     10 isolated SWE-bench fixtures with decoy trees")
    print(f"• Verification:        Physical pytest execution on disk (exit code == 0)")
    print(f"• Output directory:    {OUT_DIR}")
    print("=" * 80)

    combined_summary = {}

    for idx, model_info in enumerate(MODELS, 1):
        m_name = model_info["name"]
        m_prov = model_info["provider"]
        m_label = model_info["label"]
        print(f"\n>>> [{idx}/{len(MODELS)}] STARTING MODEL: {m_label} ({m_name}) <<<")
        
        safe_name = m_name.replace("/", "_").replace(":", "_")
        m_out = OUT_DIR / f"{safe_name}_results.json"
        
        t0 = time.time()
        try:
            run_battle_main(
                modes=MODES,
                model=m_name,
                provider=m_prov,
                limit_tasks=10,
                out_path=m_out
            )
            elapsed = round(time.time() - t0, 1)
            print(f">>> [{idx}/{len(MODELS)}] FINISHED {m_label} in {elapsed}s <<<")
            
            if m_out.exists():
                data = json.loads(m_out.read_text())
                combined_summary[m_name] = {
                    "label": m_label,
                    "elapsed_s": elapsed,
                    "summary": data.get("summary", {})
                }
        except Exception as e:
            print(f">>> ERROR running model {m_name}: {e} <<<", file=sys.stderr)

    # Save combined report
    combined_file = OUT_DIR / "combined_multi_model_summary.json"
    combined_file.write_text(json.dumps(combined_summary, indent=2))

    print("\n" + "=" * 90)
    print(" 🏆 CONSOLIDATED MULTI-MODEL SWE BENCHMARK COMPARISON (10 TASKS)")
    print("=" * 90)
    header = f"{'Model':<32} | {'Arm':<15} | {'Pass Rate':<10} | {'Time':<8} | {'Avg Turns':<10} | {'Tokens':<8}"
    print(header)
    print("-" * 90)

    mode_short = {
        "bez_jit": "1. Bare",
        "jit_bez_jev": "2. JIT (Heur)",
        "jit_z_jev": "3. JIT + JEV"
    }

    for m_name, info in combined_summary.items():
        m_label = info["label"][:32]
        sums = info.get("summary", {})
        for arm in MODES:
            s = sums.get(arm, {})
            pass_rate = s.get("pass_rate", "N/A")
            total_time = f"{s.get('total_time_s', 0)}s"
            avg_turns = s.get("avg_turns", "N/A")
            tokens = s.get("total_tokens", "N/A")
            print(f"{m_label:<32} | {mode_short[arm]:<15} | {pass_rate:<10} | {total_time:>8} | {str(avg_turns):>9} | {str(tokens):>8}")
        print("-" * 90)

    print(f"\n[Consolidated artifact saved to: {combined_file}]")

if __name__ == "__main__":
    main()
