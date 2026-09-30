# JIT Context OS for Agent Zero (v0.4.1)

Agent Zero plugin for [JIT Context](https://github.com/wojciechwiesner/jit-context):
3-tier memory cascade (L0/L1/L2), JEV shadow judge, distill/eviction layer and a
live chat status bar, in one self-contained plugin (Apache-2.0).

> **Source of truth:** this plugin lives in
> [`wojciechwiesner/jit-context`](https://github.com/wojciechwiesner/jit-context)
> under `integrations/agent-zero/`. The
> [`jit-context-os`](https://github.com/wojciechwiesner/jit-context-os) repository
> is an automatic read-only mirror with the plugin at its root, as the Agent Zero
> Plugin Hub requires. Please star, open issues and send PRs in `jit-context`.
>
> **This directory is mirrored to `jit-context-os`; edit it here, not there.**
> Every push to `master` that touches `integrations/agent-zero/**` is synced by
> [`.github/workflows/agent-zero-mirror.yml`](https://github.com/wojciechwiesner/jit-context/blob/master/.github/workflows/agent-zero-mirror.yml)
> (regular commits, never a force-push). Changes committed directly in
> `jit-context-os` are overwritten by the next sync.

Benchmarks and architecture:
[live benchmark hub](https://theones.io/benchmark/),
[architecture deep-dive](https://theones.io/blog/jit-jev-context-the-first-production-agent-runtime).
Snapshot published with v0.4.0:

| Metric | Without JIT-JEV | With JIT-JEV | Delta |
| :--- | :---: | :---: | :--- |
| Agent turns / task (SWE-bench, 10 tasks) | 6.7 | 4.6 | -31.3% |
| Blind discovery calls (ls/grep/cat) | 38 | 18 | -52.6% |
| Active context prompt footprint | 3,085 tokens | 341 tokens | -88.9% |
| Code pass rate (Liquid AI LFM 2.5) | 72.0% (36/50) | 92.0% (46/50) | +20.0 p.p. |
| Self-healing accuracy (Qwen 3.8) | 76.0% (38/50) | 94.0% (47/50) | +18.0 p.p. |

## What it does

1. **JIT Context engine (memory).** L0 hot path (SQLite WAL, read-your-own-writes),
   L1 project scope with hysteresis, L2 deep retrieval behind a 600 ms circuit
   breaker, a deterministic `<jit_capsule>` prompt prefix for stable prompt-cache
   hits, epistemic invariants I1-I10 (assistant output carries 0.0 weight, direct
   user input wins, destructive actions are gated) and a recent-turn fence.
2. **JEV Bridge (judge / eviction / verification).** Merged into this plugin since
   v0.4.0-beta.1:
   - Shadow judge (`message_loop_end`): scores capsule facts in shadow mode and
     promotes to live filtering only after the gate (>=10 evals, 0 harmful, >=30% helpful).
   - Eviction advisor: proposes L0 evictions when the hot path exceeds the budget.
   - JEV prefetch (`message_loop_start`): warms the remote judge cache (TTL cache,
     I6 fallback to local heuristics).
   - Live status bar above the chat input (`/api/plugins/jit_context/jit_status`):
     capsule size, L0 facts, cache hits and issue hints.

   All JEV calls fail safe: on any remote error the bridge degrades to local
   deterministic heuristics and never blocks the agent loop.
3. **Tool** `jit_context_query`: inspect active L0 facts, update facts, switch
   project scope, or preview the compiled capsule.

The plugin targets autonomous coding agents with real tool access (shell, files,
tests); ground truth comes from tool feedback, not assistant monologue.

## Install

Pick one:

1. **One line, every agent host on the machine** (Claude Code, Hermes, OpenCode, Agent Zero):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/wojciechwiesner/jit-context/master/install.sh | bash -s -- --only agent-zero
   ```
   It finds a local Agent Zero checkout (or `A0_DIR`) or a running Agent Zero
   container, copies the plugin to `usr/plugins/jit_context`, keeps the plugin's
   `data/`, and runs `execute.py` (idempotent setup and self-test). Restart Agent Zero afterwards.
2. **Agent Zero UI, install from git:** `https://github.com/wojciechwiesner/jit-context-os`
3. **Agent Zero UI, install from ZIP:** download `jit_context-<version>.zip` from the
   [releases](https://github.com/wojciechwiesner/jit-context/releases) (tags `a0-v*`).

Do not give Agent Zero the `jit-context` root URL: the plugin is nested there,
and the loader expects `plugin.yaml` at the plugin root.

Keep runtime `data/`, `config.json` and secrets out of version control. Configure
the JEV API credential through the host configuration or environment.

## Configuration

Global or per agent/project via **Settings > Agent > JIT Context OS**. Defaults
live in [`default_config.yaml`](default_config.yaml); the main keys:

| Key | Default | Description |
| :--- | :---: | :--- |
| `mode` | `active` | `active` injects the capsule, `disabled` pauses it. |
| `max_capsule_tokens` | `1500` | Capsule token budget. |
| `recent_turn_fence` | `4` | Recent turns preserved to stop history explosion. |
| `circuit_breaker_timeout_ms` | `600` | L2 retrieval timeout. |
| `jev_enabled` | `true` | Master switch for the JEV Bridge. |
| `jev_distill_enabled` | `true` | Distill finished turns into compact L0 facts. |
| `jev_distill_max_facts` | `3` | Max distilled facts per turn. |
| `jev_eviction_budget_pct` | `0.9` | L0 fill ratio above which the eviction advisor fires. |
| `jev_remote_enabled` | `true` | Remote JEV judge/rerank model (OpenRouter-compatible API). |
| `jev_remote_model` | `~typesafe/jev-latest` | Remote JEV model id. |

## Verification in the monorepo

The Python core and this adapter both have a `tests` package, so run the suites separately:

```bash
python3 -m pytest src/tests -q
python3 -m pytest integrations/agent-zero/tests -q
```

`python3 integrations/agent-zero/execute.py` initializes a database at the
plugin's `data/` path; use a temporary copy for an isolated smoke test.
Production rollout notes: [`docs/plans/2026-09-24-agent-zero-integration.md`](https://github.com/wojciechwiesner/jit-context/blob/master/docs/plans/2026-09-24-agent-zero-integration.md).

In the Hermes CLI, `jit mode active`, `jit jev status` and `jit doctor` inspect
Hermes's JIT/JEV runtime, not this plugin.

## Citation

DOI [10.5281/zenodo.22649542](https://doi.org/10.5281/zenodo.22649542)
