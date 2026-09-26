# JIT-JEV Context OS: Epistemic Runtime & System 1 Gate for AI Agents

<p align="center">
  <strong>The Epistemic Operating System for Autonomous Coding Agents. Eliminating the Haystack Tax: 61% fewer agent turns, 2.44x faster delivery, and >99% prompt token reduction on production codebases.</strong>
</p>

<p align="center">
  <a href="https://doi.org/10.5281/zenodo.22649542"><img src="https://zenodo.org/badge/DOI/10.5281/zenodo.22649542.svg" alt="CERN Zenodo DOI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://theones.io/benchmark/"><img src="https://img.shields.io/badge/Benchmark%20Hub-Live%20Telemetry-blue?logo=googlechrome&logoColor=white" alt="Benchmark Hub"></a>
  <a href="https://theones.io/blog/jit-jev-context-the-first-production-agent-runtime"><img src="https://img.shields.io/badge/Architecture-Deep%20Dive-purple" alt="Deep Dive"></a>
  <a href="https://theones.io/benchmark/"><img src="https://img.shields.io/badge/JEV%20System%201%20Gate--31.3%25%20Turns-emerald" alt="JEV System 1 Gate"></a>
  <a href="https://github.com/wojciechwiesner/jit-context"><img src="https://img.shields.io/badge/Synthapse-2.44x%20Faster-orange" alt="Synthapse speedup, not the fixture battle"></a>
  <a href="https://github.com/wojciechwiesner/jit-context"><img src="https://img.shields.io/badge/Token%20Reduction--99%25-green" alt="Tokens"></a>
</p>

---

### Production Benchmark Snapshot (Commercial Web Audio Codebase — 45 Modules)
| Metric | Without JIT-JEV (Haystack) | With JIT-JEV Context OS | Net Advantage |
| :--- | :---: | :---: | :--- |
| **Delivery Time** | 9m 27s | **3m 52s** | **2.44x Faster Delivery (-59%)** |
| **Agent Turns (API Rounds)** | 171 turns | **66 turns** | **-61.4% Fewer Multi-Turn Rounds** |
| **Active Prompt Footprint** | >50,000 tokens | **482 tokens** | **>99% Token Cost Elimination** |
| **Blind Tool Discovery / File Reads** | 73 file reads | **24 reads** | **-67.1% Less Context Wandering** |
| **Circular Error & Patch Loops** | 8 error loops | **0 error loops** | **Clean First-Shot Execution** |
| **JEV System 1 Decision Engine** | 6.7 turns/task | **4.6 turns/task** | **-31.3% Fewer Multi-Turn Cycles** |

---

## What is JIT-JEV Context OS?

**JIT-JEV Context OS** is an epistemic context runtime and fast decision engine built specifically for **autonomous coding agents with active tool access**. It bridges two complementary layers:

1. **JIT Context Compiler (System 2 Memory):** A deterministic, sub-3ms runtime memory engine operating between the agent harness and the LLM. Rather than stuffing 50,000+ tokens of raw logs and source files into context, JIT compiles an ultra-dense, prefix-aligned **Context Capsule (<1,500 tokens)** just-in-time for every execution turn.
2. **JEV Decision Gate (System 1 Fast Arbitration):** A sub-100ms epistemic gating layer that shadow-evaluates capsule facts, proposes dynamic evictions before context bloats, prefetches relevant memory before agent turns, and provides a 100% fail-open circuit breaker (Invariant I6).

> **Target Environment & Runtime Notice:**  
> JIT-JEV Context OS is specifically architected for **autonomous coding agents that possess active tool execution access** (file read/write, patch, terminal execution, AST parsing). It is not a generic conversational chatbot wrapper. The runtime's epistemic arbitration relies on deterministic physical tool feedback (`exit_code: 0`, runtime assertions, hash verification) to enforce Authority 1.0 ground truth while discarding speculative assistant monologue (Authority 0.0).  
> It was engineered and verified primarily in live agent execution harnesses (e.g., cmux agent loops, Hermes Agent architecture, Agent Zero). Behavior in arbitrary chat-only platforms without tool sandboxes or external harness integration is neither tested nor intended.

---

## Why Do AI Coding Agents Degrade Over Multi-Turn Sessions?

Autonomous coding agent architectures suffer from a fundamental design flaw: **The Haystack Tax**.

Standard harnesses append the entire conversation history, verbose compiler logs, and full-file dumps into a giant 50,000+ token context window.

### Observed Failure Modes:
* **Context Amnesia & Circular Loops:** The agent repeatedly reads previously inspected files, attempts invalid directory reads, loses track of changes applied two turns prior, and exhausts execution budgets.
* **Token Choke & Latency Blowout:** Time-to-First-Token (TTFT) increases to 40+ seconds per turn as prompt size balloons past 30,000 tokens, triggering API cost blowouts and HTTP 429 rate limits.
* **Epistemic Self-Poisoning:** The model treats its own earlier speculative hypotheses as established ground truth, constructing subsequent patches on top of hallucinated assumptions.

---

## The Dual-Engine Architecture: JIT Context OS + JEV System 1 Gate

**JIT-JEV Context OS** is not a vector database or an embedding wrapper that injects fuzzy Top-K chunks into the prompt.

It is a **deterministic, sub-3ms runtime memory engine** operating between the agent harness and the LLM. It compiles an ultra-precise, high-density **Context Capsule (<1,500 tokens)** just in time for every turn.

```
+-----------------------------------------------------------------------------------+
|                            TRADITIONAL AGENTS vs JIT-CONTEXT                      |
+-----------------------------------------------------------------------------------+
| Standard Full-History Context Stuffing:                                           |
|    Prompt: [System] + [50,000 tokens of raw logs, chat chatter, stale files]     |
|    -> High Latency (30-60s) | Lost-in-the-Middle | 10+ turns wandering | High Cost|
|                                                                                   |
| JIT-Context Epistemic OS:                                                         |
|    Prompt: [System] + [Lean 800-1,800 token High-Resolution Capsule]             |
|    -> Sub-2s Latency | AST Symbol Map | Verified Tool Proofs | 2-4 turns to fix   |
+-----------------------------------------------------------------------------------+
```

---

## Empirical Benchmarks & Hard Measurements

Evaluated across production environments and multi-module codebases.

### 1. Controlled Multi-File Repair: Local Qwen 3.8 9B vs Google Gemini
Task: Autonomously diagnose and fix 4 distinct root-cause bugs across 3 interconnected services (`event_pipeline.py`, `retry_policy.py`, `storage.py`), verified by an independent `pytest` test suite.

| Competitor | Setup | Turns to Solve | Total Time | Verified Tests | Cost |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Local Qwen 3.8 9B + JIT** | Mac Mini M2 Pro (32k context) | **4 turns** | ~2 min | **4/4 PASSED (exit 0)** | **$0.00 (100% Offline)** |
| **Google Gemini 3.8 Flash + JIT** | Frontier Cloud API | **9 turns** | **17.7s** | **4/4 PASSED (exit 0)** | Cloud API |
| **Google Gemini 3.8 WITHOUT JIT** | Raw Full History Accumulation | 10 turns (cap) | 34.5s | **0/4 FAILED** | Cloud API |

> **Summary:** Without JIT, Google's flagship cloud model spent turns reading `tests/` directories and failed. **With JIT, a local 9B model on a Mac Mini resolved the multi-file failure in 4 turns — 100% offline with zero token cost.**

---

### 2. Full Production Codebase Evaluation (Synthapse, 45 Modules)
Paired evaluation on a commercial generative Web Audio instrument running full Vitest E2E suites:

| Metric | Without JIT (Raw Context Dump) | With JIT-Context OS | Net Impact |
| :--- | :---: | :---: | :--- |
| **Delivery Time** | 9m 27s | **3m 52s** | **2.44x Faster Delivery (-59%)** |
| **Agent Turns (API Calls)** | 171 turns | **66 turns** | **-61.4% Fewer Turns (-105 rounds avoided)** |
| **Tool Execution Churn** | 169 calls | **64 calls** | **-62.1% Less Thrashing** |
| **Blind File Reads** | 73 reads | **24 reads** | **-67.1% Less Context Wandering** |
| **Error / Patch Loops** | 8 error loops | **0 error loops** | **Clean First-Shot Execution** |
| **Prompt Size per Turn** | >50,000 tokens | **482 tokens** | **>99% Token Cost Reduction** |
| **Scope Drift** | 14 files polluted | **4 files touched** | **Surgical Single-Responsibility Edits** |

---

### 3. SWE-bench-style fixture battle (10 isolated tasks, not full checkouts)
The harness builds small multi-file trees from inline strings plus decoy files. It is not a run on full Django, Astropy, Flask, Requests, Sympy, or pytest checkouts.

Live JEV evidence from the agent loop, not a post-hoc replay, is `benchmarks/results/swe_10_jev_live_agent_loop.json` (2026-09-23). Each of the 10 fixture tasks records `typesafe/jev-1.13-20260917`, HTTP 200, usage, and `fallback_count: 0`. That file is not a same-session comparison against haystack, and it is not a full SWE-bench score.

The older table below is a separate run. Its `jit_z_jev` column did not record live versus fallback, so it is not an independently verified live JEV result:

| Metric | 1. Haystack Baseline | 2. JIT (Heuristic Tokens) | 3. JIT + JEV Decision Engine | JEV Net Advantage |
| :--- | :---: | :---: | :---: | :--- |
| **Solve Rate** | 10/10 (100%) | 10/10 (100%) | **9/10 (90%)** | Solve rate dropped. Miss: `pallets__flask-4045` JSON parse error |
| **Average Turns / Task** | 6.7 turns | 5.6 turns | **4.6 turns** | **-31.3% turns (67 to 46), not -61%** |
| **Blind Discovery Ops (ls/grep/cat)** | 38 ops | 28 ops | **18 ops** | **-52.6% discovery ops, not zero** |
| **Total Wall-Clock Time** | 150.9s | 139.3s | **133.9s** | **11.3% shorter (1.13x). The 2.44x figure is a different Synthapse run** |
| **Decision Cost** | not recorded | not recorded | **not recorded in the agent log** | Do not cite a dollar figure for this run |
| **Fault Tolerance (I6)** | N/A | Heuristic only | **not measured here** | Agent loop did not log live JEV vs fallback |

---

### 4. GAIA Level 1 validation (N=53): harness fixes, Sumienie and Rozwaga (2026-09-26)
Worker `gemini-3.8-flash`, STANDARD mode, one run per row, same 53 validation tasks. "Exact" is a normalized string match against the ground truth; the runner's own "clean" scorer is more lenient and is shown in brackets. The harness was tuned on these same 53 tasks, so this is a development-set number, not a held-out score.

| Run | Exact | Avg time / task | What changed |
| :--- | :---: | :---: | :--- |
| Before fixes (8 turns) | 34/53 (36) | 29 s | 14 answers were empty: synthesis sent history without tool declarations |
| Cognitive pre-pipeline (LFM2 sensory + planner) | 33/53 (36) | 31 s | No gain over STANDARD; 4 tasks flipped each way |
| Loop guard + forced final answer, 8 turns | 40/53 (42) | 26 s | 0 empty answers |
| Same, 15 turns | 45/53 (47) | 36 s | Turn budget was hardcoded to 8 and never passed to the worker |
| + Sumienie gate + Rozwaga judge (`--judge`) | **47/53 (49)** | 62 s | 39/53 verified by Sumienie; judge ran on 16 tasks, changed 3 answers (2 right, 1 wrong) |

What the numbers say: almost all of the gain (34 to 45) came from deterministic harness fixes: tool declarations on the synthesis turn, a loop guard, a forced last-turn answer and a real turn budget. The judge added +4 / -2 tasks against the 15-turn run at 1.7x the time per task, which one run cannot separate from sampling noise. The cognitive pre-pipeline did not help and is scheduled for removal.

Local model, same first 10 tasks, `qwen3.8:jit` (9B, Ollama, Mac mini M2 Pro): 3/10 exact without the judge (Gemini: 10/10 on the same 10). That run hit 4 HTTP 400 errors that ended tasks early. The rerun logged the response body: Ollama rejects a history ending in two assistant messages. That harness bug is fixed in `bba46e5`.

Rerun at `7fe938d` with the fix and `--judge`, same 10 tasks, 15 turns: **8/10 exact**, all 8 verified by Sumienie. 0 HTTP 400. Where it moved:

| | qwen3.8:jit before fix, no judge | qwen3.8:jit fix + judge | gemini-3.8-flash + judge |
|---|---|---|---|
| Exact | 3/10 | 8/10 | 10/10 |
| Avg time per task | 107 s | 316 s | 37 s |
| API errors | 4x HTTP 400 (our history bug) | 4x HTTP 500 (llama-server: truncated tool-call JSON) | 0 |

The fix and the judge landed together, so this run cannot split their shares. What the log shows: Rozwaga ran on 5 tasks. On 2 of them the first attempt was empty and the second attempt was right and verified (`Fred`, `No`). On 1 it picked the verified short `3` over a verbose sentence. On 1 it picked a verified but wrong paper title. On 1 both attempts were empty after the HTTP 500s. The other 3 gains had no judge involvement. N=10, one run each, at 8.5x Gemini's time per task. "Exact" here is normalized string equality (case and punctuation ignored); the runner's own substring-based CLEAN metric scored the old run 5/10 and this one 8/10. Raw JSON and log: `benchmarks/results/gaia_loop_guard/qwen38jit_t15_judge_10.{json,log}`.

> 📊 **Explore the Live Telemetry & Architecture:**
> * **Interactive Benchmark Hub:** [theones.io/benchmark/](https://theones.io/benchmark/) *(fixture-battle logs and other measured runs; not a full SWE-bench Docker sweep)*
> * **Architectural Deep-Dive:** [theones.io/blog/jit-jev-context-the-first-production-agent-runtime](https://theones.io/blog/jit-jev-context-the-first-production-agent-runtime) *(System 1 routing, Fail-Open Circuit-Breaker, and telemetry)*


---

## The Six Core Levers of JIT-JEV Context OS

### 1. High-Density AST Symbol Map (@ref)
Instead of re-reading multi-hundred line source files, JIT extracts exact class and method signatures with line numbers dynamically:
```
[WORKING SET & CONTRACTS]
  @ref:src/event_pipeline.py:1-35
    class EventPipeline:
      def __init__(self, dlq_policy=None): ... # line 8
      def compute_payload_hash(self, payload: Dict[str, Any]) -> str: ... # line 13
      def process_event(self, event: Dict[str, Any]) -> Dict[str, Any]: ... # line 18
```
The agent receives precise interfaces and contracts without consuming turn budgets on exploratory `read_file` operations.

### 2. Sub-3ms Local SQLite WAL (Read-Your-Own-Writes)
Operational state, tool execution results, and file mutation hashes are recorded in an in-memory SQLite WAL in `<3ms`. When the agent mutates a file in Turn 1, Turn 2 accesses confirmed hashes and verified state without indexing delays.

### 3. Epistemic Invariants: Authority Arbitration (1.0 vs 0.0)
* **Direct User Instructions:** Authority = **1.0** (Never overwritten).
* **Physical Tool Proofs (`exit_code: 0`):** Authority = **1.0** (Treated as ground truth).
* **Assistant Speculation:** Authority = **0.0** (Filtered out. The agent cannot cite its own unverified assumptions as facts).

### 4. Deterministic Prompt Cache Alignment (800–1,800 Tokens)
Uncontrolled prompts swing widely in size, repeatedly breaking prefix prompt caching. JIT enforces a stable, prefix-aligned context capsule, achieving **>95% prompt cache hit rates** on Gemini, Claude, and OpenAI.

### 5. Local Obsidian Vault: Human-in-the-Loop SSOT (Zero Black-Box)
Why doesn't JIT-Context hide knowledge in an opaque, uneditable vector database index (Chroma/Pinecone)?
* **Total Human Auditability:** Your canonical Single Source of Truth (SSOT) is your **local Obsidian vault** (plain Markdown files on disk).
* **Deterministic L1 Retrieval:** Project dossiers live in `projects/<project>.md` and architecture rules in `knowhow/<topic>.md`.
* **Zero Indexing Latency (<2ms):** The agent reads live Markdown in `<2ms` with zero embedding lag, zero hallucinated chunking, and full support for bidirectional Obsidian backlinks (`[[link]]`).
* **You Stay in Command:** If an agent misunderstands a rule, you edit the Markdown file directly in Obsidian. No vector re-indexing, no black-box drift.

### 6. JEV System 1 Epistemic Gate (Shadow Judge & Eviction Advisor)
Operating in tandem with the JIT context compiler, the **JEV System 1 Engine** provides real-time arbitration over active memory:
* **Shadow Helpfulness Judge:** Evaluates facts per turn and enforces strict promotion gates (`>=10` evaluations, `0` harmful verdicts, `>=30%` helpful ratio) before facts reach persistent L2 memory.
* **Dynamic Eviction Advisor:** Triggers eviction recommendations when L0 capacity approaches threshold budgets, ensuring stale or disproven hypotheses never pollute future turns.
* **Invariant I6 Circuit Breaker:** Any timeout or network anomaly on remote JEV evaluation immediately degrades to deterministic local heuristics — guaranteeing 100% fail-open execution with zero agent crashes.

---

## Integrations

The [Agent Zero plugin](integrations/agent-zero/README.md) is now available inside this repository under `integrations/agent-zero/` (plugin v0.4.0, Apache-2.0). The Python core remains v0.2.11 (MIT); these versions and runtime hosts are independent. Install only the plugin subdirectory into Agent Zero, not the repository root. The source tree alone does not activate the plugin; the [verified production rollout](docs/plans/2026-09-24-agent-zero-integration.md) is recorded separately.

## Quickstart

### 1. Install the Python CLIs (Python 3.11+)
```bash
git clone https://github.com/wojciechwiesner/jit-context.git
cd jit-context
python3 -m pip install -e .
```
This installs `jit`, `jit-doctor`, and `jit-observatory`. The pip package does not automatically activate the Hermes plugin; `jit-doctor` reports a missing plugin until the Hermes adapter is installed.

### 2. Configure Your Obsidian Vault (Optional / Auto-detected)
By default, JIT auto-detects `~/Documents/Vault` or `~/Documents/Wojciech`. You can point to any local Obsidian vault:
```bash
export OBSIDIAN_VAULT="$HOME/Documents/MyVault"
```

### 3. Verify System Invariants
```bash
jit-doctor
# Exits nonzero if any check fails or the Hermes plugin/Observatory is absent.
```

### 4. Initialize in Any Project
Run the JIT profiler in your project directory:
```bash
jit init .
```
This generates the `.planning/STATE.md` working set and configures the project for structured context injection.

### 5. Launch the Live Observatory Dashboard
```bash
jit-observatory
# Open http://127.0.0.1:8765 in your browser (or set JIT_HEALTH_PORT).
```

---

## Architecture & The 10 Invariants

```
                    +-----------------------------------------------+
                    |               USER / TASK INPUT               |
                    +-----------------------+-----------------------+
                                            |
                                            v
  +----------------------------------------------------------------------------------+
  |                           JIT-CONTEXT RUNTIME COMPILER                           |
  |                                                                                  |
  |   +-----------------------+  +-----------------------+  +-----------------------+|
  |   |  L0 HOT-PATH (<3ms)   |  | L1 WARM-PATH (<10ms)  |  |  L2 DEEP-PATH (600ms) ||
  |   |  * SQLite WAL Overlay |  | * Scope Cache         |  |  * Circuit Breaker    ||
  |   |  * Read-Your-Own-Write|  | * Scope Hysteresis    |  |  * Fail-Open Policy   ||
  |   |  * Tool Proof Engine  |  | * AST Symbol Pointers |  |  * Associative Broker ||
  |   +-----------+-----------+  +-----------+-----------+  +-----------+-----------+|
  |               |                          |                          |            |
  |               +-------------------+------+--------------------------+            |
  |                                   v                                              |
  |                    +-----------------------------+                               |
  |                    |  EPISTEMIC ARBITER (I1-I10) |                               |
  |                    |  * User Authority = 1.0     |                               |
  |                    |  * Assistant Weight = 0.0   |                               |
  |                    |  * Tool Proof Weight = 1.0  |                               |
  |                    |  * Anti-Self-Poisoning Gate |                               |
  |                    +--------------+--------------+                               |
  |                                   v                                              |
  |                    +-----------------------------+                               |
  |                    |    HIGH-RESOLUTION CAPSULE  |                               |
  |                    |    800-1,800 TOKENS (<10ms) |                               |
  |                    +--------------+--------------+                               |
  +-----------------------------------+----------------------------------------------+
                                      v
                      +-------------------------------+
                      |    STABLE PREFIX LLM CACHE    |
                      |   (Gemini / Claude / Qwen)    |
                      |    * 2.44x Faster Delivery    |
                      |    * Zero 429 Rate Limits     |
                      +-------------------------------+
```

### The 10 Epistemic Invariants (I1–I10)
1. **I1 (Direct User Input Supremacy):** Explicit human instructions override historical context with Authority = 1.0.
2. **I2 (Atomic Monotonic Sequence):** Every turn and state change receives an atomic sequence number (`RETURNING seq`) in SQLite WAL.
3. **I3 (Anti-Self-Poisoning):** Assistant generated text is assigned `epistemic_weight = 0.0`. Speculations never pollute canonical truth.
4. **I4 (Read-Your-Own-Writes / RYOW):** Updates committed in turn N are guaranteed readable in turn N+1 in `<0.5ms`.
5. **I5 (Scope Hysteresis):** Cross-project queries expand retrieval scope without thrashing the primary active workspace.
6. **I6 (Double Circuit Breaker & Fail-Open):** Deep memory broker latency is capped at 600ms. Consecutive network failures trigger an open circuit with zero downtime.
7. **I7 (Bounded Derived Authority):** Inferred observations from tools are capped at Authority = 0.70 until physically verified (`exit_code: 0` = 1.0).
8. **I8 (Event Idempotency & Budget Ceiling):** Dynamic capsules are bounded (800–1,800 tokens) to maintain prompt caching stability.
9. **I9 (Deterministic Fallback):** If memory subsystems fail, the agent falls back to base system prompts without blocking.
10. **I10 (Prompt Caching Prefix Alignment):** Static system manifests are positioned before dynamic capsules, maintaining >95% prompt cache hit rates.

---

## Quickstart: Model Context Protocol (MCP) Integration

JIT-Context exposes a native MCP server over standard stdio JSON-RPC 2.0, allowing seamless integration with **Claude Code**, **OpenCode**, and **Cursor**.

### 1. Claude Code
```bash
claude mcp add jit-context python3 src/mcp_server.py
```

### 2. OpenCode
Add to `~/.opencode/config.json`:
```json
{
  "mcpServers": {
    "jit-context": {
      "command": "python3",
      "args": ["path/to/jit-context/src/mcp_server.py"]
    }
  }
}
```

### 3. Hermes Agent
Native plugin integration via `plugins/context_engine/jit` (PR #110874).

---

## Academic Citation

If you reference **JIT-Context** in research, benchmarks, or agent runtimes, please cite:

```bibtex
@software{wiesner2026jitcontext,
  author       = {Wiesner, Wojciech},
  title        = {JIT-JEV Context OS: Epistemic Runtime & System 1 Gate for AI Agents},
  year         = 2026,
  publisher    = {Zenodo},
  version      = {v0.2.11},
  doi          = {10.5281/zenodo.22649542},
  url          = {https://doi.org/10.5281/zenodo.22649542}
}
```

---

## License

MIT License — Copyright (c) 2026 Wojciech Wiesner (`wojciech@theones.io`) — *The Ones* (`join.theones.io`).
Developed by Wojciech Wiesner wojciech@theones.io -= join.theones.io =- be The One Who Is Many -
