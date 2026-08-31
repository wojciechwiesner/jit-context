# Hermes JIT Context OS: An Epistemic Runtime for Long-Lived AI Agents

**Version:** 0.1.0-canary (2026-08-31)  
**Author:** Wojciech Wiesner (`wojciech@theones.io`) — *The Ones*  
**Repository:** `https://github.com/vizi2000/hermes-jit-context-os`

---

## Executive Abstract

Modern LLM-based autonomous agent architectures suffer from the **"Haystack Tax"**: context window inflation (50k–100k+ tokens), severe attention degradation (*Lost-in-the-Middle*), self-poisoning through recursive consumption of prior assistant speculation, and severe rate-limiting (`429 Too Many Requests` / 5-hour rolling context exhaustion).

**Hermes JIT Context OS** introduces a deterministic, multi-tier temporal memory architecture with **Epistemic Invariants (I1–I10)**. By decoupling hot-path operational state (<3ms local SQLite WAL) from slow remote associative brokers and enforcing strict authority weighting (User Authority = 1.0, Assistant Weight = 0.0), JIT Context OS compiles a **Lean Context Capsule (<1,500 tokens)** just-in-time for each LLM turn.

```
                    ┌───────────────────────────────────────────────┐
                    │               USER / TASK INPUT               │
                    └───────────────────────┬───────────────────────┘
                                            │
                                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                         HERMES JIT CONTEXT OS COMPILER                           │
  │                                                                                  │
  │   ┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐│
  │   │  L0 HOT-PATH (<3ms)   │  │ L1 WARM-PATH (<10ms)  │  │  L2 DEEP-PATH (600ms) ││
  │   │  • SQLite WAL Overlay │  │ • Project Scope Cache │  │  • Circuit Breaker    ││
  │   │  • Read-Your-Own-Write│  │ • Scope Hysteresis    │  │  • Fail-Open Policy   ││
  │   │  • RecentTurnFence    │  │ • Active vs Retrieval │  │  • Borg Gateway/Honcho││
  │   └───────────┬───────────┘  └───────────┬───────────┘  └───────────┬───────────┘│
  │               │                          │                          │            │
  │               └───────────────────┬──────┴──────────────────────────┘            │
  │                                   ▼                                              │
  │                    ┌─────────────────────────────┐                               │
  │                    │  EPISTEMIC ARBITER (I1–I10) │                               │
  │                    │  • User Authority = 1.0     │                               │
  │                    │  • Assistant Weight = 0.0   │                               │
  │                    │  • Anti-Self-Poisoning Gate │                               │
  │                    └──────────────┬──────────────┘                               │
  │                                   ▼                                              │
  │                    ┌─────────────────────────────┐                               │
  │                    │    LEAN CONTEXT CAPSULE     │                               │
  │                    │    ~1,500 TOKENS (<10ms)    │                               │
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

## Controlled Benchmark Highlights (EXP-001 – EXP-004)

* **20 / 20 Paired Wins** against long-context baseline on complex software engineering tasks.
* **100% vs 75% Task Success** compared to vanilla semantic Top-k RAG.
* **0 Stale-Context Conflicts** observed vs 4 conflicts in vanilla RAG.
* **-67.0% Input Tokens** per execution loop (averaging 24.9k vs 75.5k).
* **-38.0% P95 Wall Time** (90.2s vs 145.4s).
* **+15.6 Quality Points** on deterministic automated rubrics (95.8 vs 80.2).

---

## The 10 Iron Safety & Epistemic Invariants (I1–I10)

* **I1 (Direct User Input Supremacy):** Unambiguous human instructions instantly supersede all prior assumptions with Authority = 1.0.
* **I2 (Atomic Monotonic Sequence):** Every turn and state change receives an atomic sequence number (`RETURNING seq`) in SQLite WAL.
* **I3 (Anti-Self-Poisoning):** Assistant generated text is assigned `epistemic_weight = 0.0`. Speculations never pollute canonical truth.
* **I4 (Read-Your-Own-Writes / RYOW):** Updates committed in turn $N$ are guaranteed readable in turn $N+1$ in $<0.5$ ms.
* **I5 (Scope Hysteresis):** Cross-project queries expand retrieval scope without thrashing the primary active workspace.
* **I6 (Double Circuit Breaker & Fail-Open):** L2 broker latency is capped at 600ms. Triple network failures trigger an open circuit with zero downtime.
* **I7 (Bounded Derived Authority):** Inferred observations from tools are capped at Authority = 0.70 until verified.
* **I8 (Event Idempotency):** Every external callback or hook is deduplicated by unique event signature.
* **I9 (Deterministic Fallback):** If memory subsystems fail, the agent falls back to pristine system prompts seamlessly.
* **I10 (Prompt Caching Prefix Alignment):** Frozen system manifests are positioned before dynamic capsules, achieving >95% prompt cache hit rates.

---

## Quickstart & Verification

```bash
# 1. Install & enable plugin
hermes plugins enable ona-context

# 2. Run automated Doctor verification
hermes-ona-doctor

# 3. View Live Observatory & Telemetry Dashboard
open http://127.0.0.1:8765/
```
