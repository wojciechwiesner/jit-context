# JIT-Context: The Trust-in-Time Context OS for AI Agents

<p align="center">
  <strong>Stop the Haystack Tax. Cut agent turns by 60%, ship fixes 2.5x faster, and kill infinite amnesia loops.</strong>
</p>

<p align="center">
  <a href="https://doi.org/10.5281/zenodo.22649542"><img src="https://zenodo.org/badge/DOI/10.5281/zenodo.22649542.svg" alt="DOI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://github.com/wojciechwiesner/jit-context"><img src="https://img.shields.io/badge/Tests-28%2F28%20PASS-success" alt="Tests"></a>
  <a href="https://github.com/wojciechwiesner/jit-context"><img src="https://img.shields.io/badge/Speedup-2.44x%20Faster-orange" alt="Speedup"></a>
  <a href="https://github.com/wojciechwiesner/jit-context"><img src="https://img.shields.io/badge/Token%20Reduction--99%25-green" alt="Tokens"></a>
</p>

---

## ⚡ Why Do AI Coding Agents Get Dumber The Longer They Work?

Every developer building autonomous coding agents hits the exact same wall: **The Haystack Tax**.

As your agent chats and runs tools, standard systems stuff the entire conversation history, massive compiler outputs, and whole files into a giant 50,000+ token prompt. 

### The Result? A Painful Breakdown:
* 🌀 **Amnesia & Baffling Loops:** The agent reads the same file 4 times, attempts to read directories as files, forgets what it solved two turns ago, and exhausts your turn budget.
* 💸 **Token Burn & Slug Speed:** Waiting 40+ seconds per turn while your prompt balloons to 30,000+ tokens. Massive API bills and `429 Too Many Requests` rate-limits.
* 🤥 **Self-Poisoning & Hallucinations:** The agent mistakes its own previous guesses for verified truth, building broken patches on top of fabricated assumptions.

---

## 🚀 The Fix: Trust-in-Time (JIT) Context OS

**JIT-Context** is not another slow vector database. It is not an embedding wrapper that dumps fuzzy Top-K chunks into your context.

It is a **deterministic, sub-3ms runtime memory engine** that sits between your agent and the LLM. It compiles an ultra-precise, high-density **Context Capsule (<1,500 tokens)** just in time for every turn.

```
+-----------------------------------------------------------------------------------+
|                            TRADITIONAL AGENTS vs JIT-CONTEXT                      |
+-----------------------------------------------------------------------------------+
| ❌ Standard Context Stuffing:                                                     |
|    Prompt: [System] + [50,000 tokens of raw logs, chat chatter, stale files]     |
|    -> High Latency (30-60s) | Lost-in-the-Middle | 10+ turns wandering | $$$      |
|                                                                                   |
| ⚡ JIT-Context OS:                                                                |
|    Prompt: [System] + [Lean 800-1,800 token High-Resolution Capsule]             |
|    -> Sub-2s Latency | AST Symbol Map | Verified Tool Proofs | 2-4 turns to fix   |
+-----------------------------------------------------------------------------------+
```

---

## 📊 Hard Numbers: Real Benchmarks, Real Codebases

We didn't test this on toy leetcode puzzles. We evaluated JIT-Context on complex, multi-module production codebases.

### 🏆 1. The Head-to-Head Duel: Local Qwen 3.8 9B vs Google Gemini Cloud
Task: Autonomously diagnose and fix 4 distinct root-cause bugs across 3 interconnected services (`event_pipeline.py`, `retry_policy.py`, `storage.py`) verified by an independent `pytest` test suite.

| Competitor | Setup | Turns to Solve | Total Time | Verified Tests | Cost |
| :--- | :--- | :---: | :---: | :---: | :---: |
| 🥇 **Local Qwen 3.8 9B + JIT** | Mac Mini M2 Pro (32k context) | **4 turns** | ~2 min | **4/4 PASSED (exit 0)** | **$0.00 (100% Offline)** |
| 🥈 **Google Gemini 3.8 Flash + JIT** | Frontier Cloud API | **9 turns** | **17.7s** | **4/4 PASSED (exit 0)** | Cloud API |
| 🥉 **Google Gemini 3.8 WITHOUT JIT** | Raw Full History Accumulation | 10 turns (cap) | 34.5s | ❌ **0/4 FAILED** | Cloud API |

> **Takeaway:** Without JIT, Google's flagship cloud model got lost reading `tests/` directories and failed. **With JIT, a local 9B model on a Mac Mini crushed the problem in only 4 turns — 100% offline with zero token cost.**

---

### 📈 2. Full Production Codebase Benchmark (*Synthapse*, 45 Modules)
Paired evaluation on a commercial generative Web Audio instrument running full Vitest E2E suites:

| Metric | Without JIT (Raw Context Dump) | With JIT-Context OS | Your Bottom Line |
| :--- | :---: | :---: | :--- |
| **Delivery Time** | 9m 27s | **3m 52s** | **⚡ 2.44x Faster Delivery (-59%)** |
| **Agent Turns (API Calls)** | 171 turns | **66 turns** | **📉 -61.4% Less Turns (-105 rounds avoided)** |
| **Tool Execution Churn** | 169 calls | **64 calls** | **🎯 -62.1% Less Thrashing** |
| **Blind File Reads** | 73 reads | **24 reads** | **🔍 -67.1% Less Context Wandering** |
| **Error / Patch Loops** | 8 error loops | **0 error loops** | **🛡️ 100% Clean First-Shot Execution** |
| **Prompt Size per Turn** | >50,000 tokens | **482 tokens** | **💰 >99% Token Cost Reduction** |
| **Scope Drift** | 14 files polluted | **4 files touched** | **🎯 Surgical Single-Responsibility Edits** |

---

## 🛠️ The 4 Core Levers (Why It Works)

### 1. 🗺️ High-Density AST Symbol Map (`@ref`)
Instead of forcing the agent to read 500-line files over and over, JIT dynamically extracts class and method signatures with line numbers:
```
[WORKING SET & CONTRACTS]
  @ref:src/event_pipeline.py:1-35
    class EventPipeline:
      def __init__(self, dlq_policy=None): ... # line 8
      def compute_payload_hash(self, payload: Dict[str, Any]) -> str: ... # line 13
      def process_event(self, event: Dict[str, Any]) -> Dict[str, Any]: ... # line 18
```
The agent instantly knows the exact symbols and contracts without wasting a single turn or token on exploratory `read_file` calls.

### 2. ⚡ Sub-3ms Local SQLite WAL (Read-Your-Own-Writes)
No waiting for vector embeddings to index. Operational state, tool outputs, and file hashes land in an in-memory SQLite WAL in `<3ms`. When the agent writes a file in Turn 1, Turn 2 already has the verified hash and verified state.

### 3. 🛡️ Epistemic Invariants: Authority 1.0 vs 0.0 (No Self-Poisoning)
* **Direct User Instructions:** Authority = **1.0** (Never overwritten).
* **Physical Tool Proofs (`exit_code: 0`):** Authority = **1.0** (Treated as ground truth).
* **Assistant Speculation:** Authority = **0.0** (Filtered out. The agent will **never** cite its own unverified guesses as facts).

### 4. 🎯 Prompt-Cache Sweet Spot (800–1,800 Tokens)
Standard prompts jump between 1,000 and 60,000 tokens, constantly breaking prefix prompt caching. JIT maintains a stable, prefix-aligned context capsule, hitting **>95% prompt cache hits** on Gemini, Claude, and OpenAI.

---

## ⚡ Quickstart: Get Started in 60 Seconds

### 1. Install via pip
```bash
git clone https://github.com/wojciechwiesner/jit-context.git
cd jit-context
pip install -e .
```

### 2. Verify Your System (10/10 Invariants Check)
```bash
python3 src/health/doctor.py
# Output: [PASS] 10/10 Epistemic Invariants Verified (<3ms WAL, zero-drift)
```

### 3. Initialize in Any Project
Run the JIT profiler in your project directory:
```bash
jit init .
```
This instantly creates your `.planning/STATE.md` working set and configures your project for surgical context injection.

### 4. Launch the Live Observatory Dashboard
Track your agent's real-time token savings and epistemic integrity:
```bash
python3 src/telemetry/observatory.py
# Open http://127.0.0.1:8765 in your browser
```

---

## 🔬 Deep Architecture & The 10 Invariants

For systems engineers, AI architects, and researchers who want to inspect the engine under the hood:

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
  │   │  • SQLite WAL Overlay │  │ • Scope Cache         │  │  • Circuit Breaker    ││
  │   │  • Read-Your-Own-Write│  │ • Scope Hysteresis    │  │  • Fail-Open Policy   ││
  │   │  • Tool Proof Engine  │  │ • AST Symbol Pointers │  │  • Associative Broker ││
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
  │                    │    HIGH-RESOLUTION CAPSULE  │                               │
  │                    │    800–1,800 TOKENS (<10ms) │                               │
  │                    └──────────────┬──────────────┘                               │
  └───────────────────────────────────┼──────────────────────────────────────────────┘
                                      ▼
                      ┌───────────────────────────────┐
                      │    STABLE PREFIX LLM CACHE    │
                      │   (Gemini / Claude / Qwen)    │
                      │    • 2.44x Faster Delivery    │
                      │    • Zero 429 Rate Limits     │
                      └───────────────────────────────┘
```

### The 10 Iron Epistemic Invariants (I1–I10)
1. **I1 (Direct User Input Supremacy):** Unambiguous human instructions instantly supersede all prior assumptions with Authority = 1.0.
2. **I2 (Atomic Monotonic Sequence):** Every turn and state change receives an atomic sequence number (`RETURNING seq`) in SQLite WAL.
3. **I3 (Anti-Self-Poisoning):** Assistant generated text is assigned `epistemic_weight = 0.0`. Speculations never pollute canonical truth.
4. **I4 (Read-Your-Own-Writes / RYOW):** Updates committed in turn $N$ are guaranteed readable in turn $N+1$ in $<0.5$ ms.
5. **I5 (Scope Hysteresis):** Cross-project queries expand retrieval scope without thrashing the primary active workspace.
6. **I6 (Double Circuit Breaker & Fail-Open):** Deep memory broker latency is capped at 600ms. Triple network failures trigger an open circuit with zero downtime.
7. **I7 (Bounded Derived Authority):** Inferred observations from tools are capped at Authority = 0.70 until physically verified (`exit_code: 0` = 1.0).
8. **I8 (Event Idempotency & Budget Ceiling):** Dynamic capsules are strictly bounded (800–1,800 tokens) to preserve prompt caching stability.
9. **I9 (Deterministic Fallback):** If memory subsystems fail, the agent falls back to pristine system prompts seamlessly.
10. **I10 (Prompt Caching Prefix Alignment):** Frozen system manifests are positioned before dynamic capsules, achieving >95% prompt cache hit rates.

---

## 📚 Academic Citation

If you use or reference **JIT-Context** in research, benchmarks, or agent runtimes, please cite:

```bibtex
@software{wiesner2026jitcontext,
  author       = {Wiesner, Wojciech},
  title        = {JIT-Context: An Epistemic Context Runtime for AI Agents},
  year         = 2026,
  publisher    = {Zenodo},
  version      = {v0.2.5},
  doi          = {10.5281/zenodo.22649542},
  url          = {https://doi.org/10.5281/zenodo.22649542}
}
```

---

## 📄 License

MIT License — Copyright (c) 2026 Wojciech Wiesner (`wojciech@theones.io`) — *The Ones* (`join.theones.io`).
Developed by Wojciech Wiesner wojciech@theones.io -= join.theones.io =- be The One Who Is Many -
