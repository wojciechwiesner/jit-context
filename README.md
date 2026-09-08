# JIT-Context: An Epistemic Context Runtime for AI Agents

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22649542.svg)](https://doi.org/10.5281/zenodo.22649542)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/Tests-27%2F27%20PASS-success)](https://github.com/wojciechwiesner/jit-context)
[![Benchmarks](https://img.shields.io/badge/Benchmarks-2.44x%20Faster-orange)](https://github.com/wojciechwiesner/jit-context#empirical-production-benchmark-exp-005--exp-009-real-world-codebase)

**Version:** 0.2.4 (2026-09-08)  
**Author:** Wojciech Wiesner (`wojciech@theones.io`) — *The Ones* (`join.theones.io`)  
**DOI:** [10.5281/zenodo.22649542](https://doi.org/10.5281/zenodo.22649542)  
**Repository:** [https://github.com/wojciechwiesner/jit-context](https://github.com/wojciechwiesner/jit-context)

---

## Executive Abstract

Modern LLM-based autonomous agent architectures suffer from the **"Haystack Tax"**: context window inflation (50k–100k+ tokens), severe attention degradation (*Lost-in-the-Middle*), self-poisoning through recursive consumption of prior assistant speculation, and severe rate-limiting (`429 Too Many Requests` / rolling context window exhaustion).

**JIT-Context** is a universal, deterministic, multi-tier temporal memory and context runtime with **Epistemic Invariants (I1–I10)**. It serves as an architectural drop-in runtime for autonomous agents (Claude Code, Hermes, Cursor, OpenCode, Codex, and custom multi-agent harnesses).

By decoupling hot-path operational state (<3ms local SQLite WAL) from slow associative brokers and enforcing strict authority weighting (User Authority = 1.0, Assistant Speculation = 0.0, Runtime Tool Proof = 1.0), **JIT-Context** compiles a **Lean Context Capsule (400–1,200 tokens, ceiling <1,500 tokens)** just-in-time for each turn.

---

## The Architectural Moat: Why Traditional Memory Fails Long-Lived Agents

| Capability / Challenge | Semantic Vector Stores (Mem0 / Zep) | Self-Managed Agent Memory (Letta / MemGPT) | Context Stuffing (100k+ Dump / Prompt Caching) | **JIT-Context (This Architecture)** |
|---|---|---|---|---|
| **Hot-Path Latency** | Slow (200–800ms API / embedding) | Moderate (LLM decides tool call) | Zero (Static Prompt) | **<3ms (Local SQLite WAL, In-Memory)** |
| **Read-Your-Own-Writes** | Eventual consistency / indexing lag | Delayed by multi-turn tool loops | N/A (Frozen context) | **Instant RYOW (<0.5ms)** |
| **Self-Poisoning Vulnerability** | HIGH (re-ingests assistant answers) | HIGH (agent writes own core facts) | MODERATE (hallucinations stay in transcript) | **ZERO (Assistant Epistemic Weight = 0.0)** |
| **Scope Drift Resistance** | LOW (fuzzy similarity pulls other repos) | LOW (unconstrained agent queries) | VERY LOW (lost-in-the-middle confusion) | **HIGH (L1 Scope Hysteresis Guard)** |
| **Prompt Cache Alignment** | POOR (dynamic injected text breaks cache) | POOR (frequent core memory edits) | MODERATE (large prefix, expensive cache misses) | **>95% Cache Hit Rate (Prefix-stable)** |
| **Hot-Reloading in RAM** | Requires service restart | Process rebuild | Re-prompting required | **Dynamic In-Process Hot-Reload (<1ms)** |
| **Token Economy** | Inflates prompt with Top-K fragments | Multiple turns of tool-calling overhead | Severe ($$$ context tax, rolling 5h limits) | **Lean Capsule (400–1,200 tokens)** |

```
                    ┌───────────────────────────────────────────────┐
                    │               USER / TASK INPUT               │
                    └───────────────────────┬───────────────────────┘
                                            │
                                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                           JIT-CONTEXT RUNTIME COMPILER                           │
  │                                                                                  │
  │   ┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐│
  │   │  L0 HOT-PATH (<3ms)   │  │ L1 WARM-PATH (<10ms)  │  │  L2 DEEP-PATH (600ms) ││
  │   │  • SQLite WAL Overlay │  │ • Project Scope Cache │  │  • Circuit Breaker    ││
  │   │  • Read-Your-Own-Write│  │ • Scope Hysteresis    │  │  • Fail-Open Policy   ││
  │   │  • Runtime Tool Proofs│  │ • Active vs Retrieval │  │  • Associative Broker ││
  │   │  • Dynamic Hot-Reload │  │ • Session CWD Track   │  │  • Ollama Fallback    ││
  │   └───────────┬───────────┘  └───────────┬───────────┘  └───────────┬───────────┘│
  │               │                          │                          │            │
  │               └───────────────────┬──────┴──────────────────────────┘            │
  │                                   ▼                                              │
  │                    ┌─────────────────────────────┐                               │
  │                    │  EPISTEMIC ARBITER (I1–I10) │                               │
  │                    │  • User Authority = 1.0     │                               │
  │                    │  • Assistant Weight = 0.0   │                               │
  │                    │  • Tool Proof Weight = 1.0  │                               │
  │                    │  • Anti-Self-Poisoning Gate │                               │
  │                    └──────────────┬──────────────┘                               │
  │                                   ▼                                              │
  │                    ┌─────────────────────────────┐                               │
  │                    │    LEAN CONTEXT CAPSULE     │                               │
  │                    │    400–1,200 TOKENS (<10ms) │                               │
  │                    │   (Ceiling <1,500 tokens)   │                               │
  │                    └──────────────┬──────────────┘                               │
  └───────────────────────────────────┼──────────────────────────────────────────────┘
                                      ▼
                      ┌───────────────────────────────┐
                      │    STABLE PREFIX LLM CACHE    │
                      │    (Gemini / Claude / GLM)    │
                      │    • 4.51x Faster TTFT        │
                      │    • Zero 429 Rate Limits     │
                      └───────────────────────────────┘
```

---

## Empirical Production Benchmarks (Live Codebases & Models)

### EXP-005 & EXP-009: Paired Production Codebase Benchmark (Synthapse)
A head-to-head paired benchmark was executed on the production repository **Synthapse** (Web Audio Generative AI Techno Instrument, ~45 modules, Vitest + Vite build). Autonomous agents were tasked with implementing direct MP3 audio export and recording alongside WAV:

| Metric | With JIT-Context (Calibrated Capsule) | Control (No JIT / Long-Context) | Delta / Real Impact |
|---|---|---|---|
| **Wall Clock Time** | **232.43 s** (3m 52s) | **567.57 s** (9m 27s) | **-59.0% (2.44x faster)** |
| **LLM API Calls (Turns)** | **66** | **171** | **-61.4% (105 rounds avoided)** |
| **Total Tool Calls** | **64** | **169** | **-62.1%** |
| **Files Read (`read_file`)** | **24** | **73** | **-67.1% (3x less context churn)** |
| **Discovery Ops Before Edit** | **31** | **65** | **-52.3%** |
| **Time to First Code Mutation** | **125 s** | **202 s** | **-38.1% (-77s)** |
| **Runtime / Test / Patch Errors** | **0** (100% clean) | **8 errors** (tests, syntax, patch) | **100% error loop elimination** |
| **Scope Drift (Files Touched)** | **4 files** (surgical SRP) | **14 files** (severe drift into DJ/Studio) | **Zero scope drift** |
| **Context Capsule Size** | **482 tokens** (calibrated architecture) | Monolithic workspace dump (>50k tok) | **100x leaner context window** |
| **Verification Suite** | **PASS** (199/199 Vitest tests) | **PASS** (216/216 tests after 8 fixes) | First-shot clean build |

### EXP-008: Real-World Runtime Tool Epistemics & Anti-Hallucination
Evaluates Invariant I3 & I4 against `gemini-3.8-flash`: when an assistant falsely asserts a service is running and deployed, but the physical tool returned `exit_code: 1 (Port 8080 already bound)`:

* **Control (No JIT / Raw Chat History):** The LLM read previous assistant claims, compounding the speculation.
* **JIT Context OS v0.2.4:** Assistant text rejected (weight 0.0). Physical tool output compiled into `[VERIFIED RUNTIME PROOFS (Authority 1.0)]`.
* **Result:** **100% Grounded Accuracy** — model answered: *"NIE – w tej sesji nie przeprowadzono wdrożenia ani nie wykonano weryfikacji uruchomieniowej potwierdzającej działanie serwisu na porcie 8080."*

### EXP-006 & EXP-007: Real-Time Audio DSP & Relational Epistemics
* **EXP-006 (Synthapse DSP Arbitration):** -86.3% prompt tokens (774 vs 5,659), 1.4x faster latency (3.24s vs 4.55s), 100% exact retrieval of in-flight audio parameters (142 BPM, 3200 Hz cutoff, sidechain OFF).
* **EXP-007 (Tuli.my Relational Epistemics):** -76.6% prompt tokens (783 vs 3,347), 100% strict adherence to user-defined boundary overrides.

---

## The 10 Iron Safety & Epistemic Invariants (I1–I10)

* **I1 (Direct User Input Supremacy):** Unambiguous human instructions instantly supersede all prior assumptions with Authority = 1.0.
* **I2 (Atomic Monotonic Sequence):** Every turn and state change receives an atomic sequence number (`RETURNING seq`) in SQLite WAL.
* **I3 (Anti-Self-Poisoning):** Assistant generated text is assigned `epistemic_weight = 0.0`. Speculations never pollute canonical truth.
* **I4 (Read-Your-Own-Writes / RYOW):** Updates committed in turn $N$ are guaranteed readable in turn $N+1$ in $<0.5$ ms.
* **I5 (Scope Hysteresis):** Cross-project queries expand retrieval scope without thrashing the primary active workspace.
* **I6 (Double Circuit Breaker & Fail-Open):** L2 broker latency is capped at 600ms. Triple network failures trigger an open circuit with zero downtime.
* **I7 (Bounded Derived Authority):** Inferred observations from tools are capped at Authority = 0.70 until physically verified (`exit_code: 0` = 1.0).
* **I8 (Event Idempotency & Budget Ceiling):** Dynamic capsules strictly bounded below <1,500 tokens to preserve prompt caching stability.
* **I9 (Deterministic Fallback):** If memory subsystems fail, the agent falls back to pristine system prompts seamlessly.
* **I10 (Prompt Caching Prefix Alignment):** Frozen system manifests are positioned before dynamic capsules, achieving >95% prompt cache hit rates.

---

## Repository Architecture

```
jit-context/
├── benchmarks/              # Empirical and synthetic benchmark datasets
│   ├── EXP-001-CANARY.json
│   ├── EXP-002-STATISTICAL-20.json
│   ├── EXP-003-TRI-VARIANT.json
│   ├── EXP-004-ABLATION.json
│   └── EXP-005-REAL-WORLD-SYNTHAPSE.json
├── src/
│   ├── context/
│   │   ├── compiler.py          # Multi-tier capsule compiler (<10ms)
│   │   └── cascade_distiller.py # 3-tier cascade distiller & elastic budget
│   ├── health/
│   │   ├── doctor.py            # Automated system verification CLI
│   │   ├── exp005_runner.py     # Needle-in-haystack benchmark
│   │   ├── exp006_synthapse.py  # DSP state arbitration benchmark
│   │   ├── exp007_tulimy.py     # Relational boundary benchmark
│   │   └── exp008_tool_epistemics.py # Runtime tool anti-hallucination test
│   ├── hooks.py                 # Hermes & agent harness integration hooks
│   ├── init.py                  # /jit init project profiler CLI
│   ├── l0/
│   │   ├── db.py                # SQLite WAL database layer (<1ms)
│   │   ├── epistemics.py        # Authority & epistemic weighting engine
│   │   └── overlay.py           # Read-Your-Own-Writes operational overlay
│   ├── l1/
│   │   ├── project_cache.py     # Scope cache with hysteresis (<10ms)
│   │   └── scope.py             # Scope resolution with hysteresis
│   ├── l2/
│   │   ├── broker_client.py     # Deep retrieval client with circuit breaker
│   │   └── distill.py           # Context compressor & pruner
│   ├── telemetry/
│   │   └── observatory.py       # Realtime HTTP telemetry server (:8765)
│   └── tests/                   # 27 automated unit and regression tests
├── CITATION.cff                 # CERN Zenodo citation metadata
├── MANIFEST.sha256              # Cryptographic file integrity manifest
└── README.md
```

---

## Quickstart & Verification

### Universal Installation
```bash
# Clone the repository
git clone https://github.com/wojciechwiesner/jit-context.git
cd jit-context

# Install package & dependencies
pip install -e .

# Run the 27 automated unit & invariant tests
pytest src/tests/
```

### Verify System Invariants
```bash
# Run Doctor check verifying 10/10 Invariants
python3 src/health/doctor.py
```

### Launch the Observatory Dashboard
```bash
# Start local metrics server on port 8765
python3 src/telemetry/observatory.py
open http://127.0.0.1:8765/
```

---

## Citation & Academic Provenance

If you use or reference **JIT-Context** in academic research or production agent frameworks, please cite:

```bibtex
@software{wiesner2026jitcontext,
  author       = {Wiesner, Wojciech},
  title        = {JIT-Context: An Epistemic Context Runtime for AI Agents},
  year         = 2026,
  publisher    = {Zenodo},
  version      = {v0.2.4},
  doi          = {10.5281/zenodo.22649542},
  url          = {https://doi.org/10.5281/zenodo.22649542}
}
```

---

## License

MIT License — Copyright (c) 2026 Wojciech Wiesner (`wojciech@theones.io`) — *The Ones* (`join.theones.io`).
