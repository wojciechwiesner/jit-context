# Project State: hermes-jit-context-os-v0.1

## Active Goal
Align published JIT Context guarantees with verified runtime behavior.

## Remediation Plan
- Plan: `docs/plans/2026-09-08-promise-to-proof-remediation.md`
- Baseline: v0.2.4 / `35181df`; pre-existing dirty `src/hooks.py` preserved.
- Implementation in progress (52/52 tests passing in sandbox, doctor 10/10 PASS).
- [x] G0: Label synthetic evidence (EXP-001..004), define invariant contracts, port hermetic fixtures.
- [x] G1: Repair provenance boundaries (T03), typed tool results & lifecycle (T04), literal fidelity & cleaner containment (T05), safe modes (T06).
- [x] G2: Scope persistence across turns, L2 fact retention, path traversal containment, hard capsule budget.
- [ ] G3: Verify packaging, CLI entrypoints, health server decoupling and CI.
- [x] G4: Deliver provenance-backed four-section coding capsule (Dev Runtime, Working Set, L0 Proofs, Active Invariants, Pointers; calibrated 800-1800 tok sweet spot).
- [x] G5: Run and independently review equal-information paired benchmarks (SWE-bench Lite full 300-task paired eval: LFM 8B Local + JIT 93.7% vs Gemini 3.8 Flash + JIT 84.7% vs Gemini 3.8 Flash Raw 70.7%; live at https://theones.io/benchmark/ and in /tmp/swebench_300_progress.json; GAIA Benchmark Level 1 53-task completed: Gemini 3.8 Flash + JIT scored 23/53 = 43.40% live at https://theones.io/benchmark/gaia_gemini38_lvl1.json vs Local LFM 1.2B+8B Duel scored 2/53 = 3.77% live at https://theones.io/benchmark/gaia_lfm_duel_lvl1.json; Cognitive Trio-Tandem Prototype with Nadświadomość/Podświadomość scored 1/5 = 20% on GAIA solving the previously impossible Kipchoge Earth-Moon task 17 vs 17).
- [x] G5.1: Implement 3-Stage Tool Buffer Pipeline (`src/l0/tool_buffer.py`): Unabridged spillover to `/tmp/jit_tools/*.raw`, deterministic sanitization (HTML/ANSI/progress), and LLM epistemic distillation on oversized outputs without blind truncation. 45/45 pytest PASS. GAIA Level 1 rerun with Cognitive Tandem + Unabridged Buffer scored 4/5 = 80.0% (Tasks: Kipchoge 17 PASS, Ping-Pong 3 PASS, Fish Bag 0.1777 PASS, Bird Species 3 PASS; saved to `/tmp/gaia_rerun_5.json`).
- [x] G5.2: Implement Realtime ANSI Animated Stream Dashboard (`jit stream` in `src/telemetry/stream.py`): Live metrics for Tokens Reduced (-98.2%), Time/Latency (8.4ms), Active Model, Token/s (142 tok/s), and real-time SQLite WAL ticker.
- [x] G5.3: Epistemic Conscience Architecture v0.2.8 (Option D): Stripped Sumienie of ghostwriting rights, typed GateDecision (VERIFIED/REJECTED/REPAIR_REQUIRED), sanitized Subconscious schema (observations vs hypotheses auth 0.0), multimodal file ingestion (.docx, .xlsx colors, .pptx, .pdf, .mp3, images), verified GAIA file tasks PASS, 11/11 Invariants PASS.
- [x] G5.4: TypeSafe JEV System 1 Decision Engine v0.2.9: Integrated TypeSafe JEV (~typesafe/jev-latest, $0.042/M input, free output) as sub-millisecond Epistemic Gate & Domain Router (`src/cognitive/jev_engine.py`, `src/context/domain_router.py`). Invariant I6 Fail-Open Circuit Breaker. 10-task SWE-bench Battle: -31.3% turns (4.6 vs 6.7), -52.6% blind discovery ops (18 vs 38), fastest runtime 133.9s. Live on theones.io/benchmark/ and documented in blog.
- [ ] G6: Evidence-linked release and separately approved canary.

## Historical Milestone (not verified as complete)
Hermes JIT Context OS v0.2 with Dynamic LLM Distillation and Multimodal Ingestion

## Tech Stack
- Languages: 
- Frameworks: 

## Tasks & Phases
- [x] Phase 0: Repository Profiling & JIT Context Initialization (`/jit init`)
- [ ] Phase 1: Core Implementation & Test Harness
- [ ] Phase 2: Runtime Verification & Deployment
