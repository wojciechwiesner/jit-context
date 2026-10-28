# Project State: hermes-jit-context-os-v0.1

## 2026-10-29 — cockpit freshness + architecture map
- [x] `713d77e` cockpit_sync + post_commit: git post-commit rebuilds `.planning/state.html` (skips tracked cockpits),
  syncs Obsidian, warns when `ARCHITECTURE.mmd` is 15+ code commits behind; `<ARCHITECTURE_DRIFT_ALERT>` in the capsule.
  Pushed to origin/master, `jit install` exit 0 on all 5 hosts.
- [x] Import cycles 3 -> 0 (AST scan of src/): harness-message filters moved to `context/capsule_policy.py`
  (hooks re-exports), `evaluate_all_invariants` moved to `health/diagnostics.py`, `ProjectScanner` and dossier naming
  moved to `context/project_scan.py` (init re-exports; `init.resolve_dossier` keeps honouring `OBSIDIAN_PROJECTS_DIR`).
- [x] `.planning/ARCHITECTURE.mmd` redrawn from the package import graph (was 79 code commits behind, from 2026-09-25).
- Verification: `python3.11 -m pytest src/tests -q` 247 passed; no new Ruff F/E9 findings in touched files;
  imports OK on system python3 (3.9) and 3.11; `jit init`, `jit skills`, `jit doctor` (READY FOR ACTIVE) exit 0.
- Open: `.planning/state.html` is tracked here, so the hook does not rebuild it; regenerate by hand when it matters.

## Release v0.5.1 — 2026-10-17
- User approved commit, production replacement, push and release.
- Verification: **231 tests PASS**, supported Python 3.14; wheel/sdist build and Ruff F/E9 PASS.
- Deployment command: `jit install --only hermes --active-profile-only`; other Hermes profiles and their snapshots must remain unchanged.
- Production rollback backup includes code, configs, immutable releases and consistent copies of 2455 SQLite databases.
- Publication and production read-back proofs are recorded by the operator in the external deployment registry and Obsidian after rollout; this section records the pre-publication verification gate, not an assumed successful deploy.

## Historical verified block — 2026-10-16 audit remediation
- Status: implemented and verified locally; UNCOMMITTED, NOT DEPLOYED. Base HEAD: `a6c0dfa`; existing unrelated working-tree files preserved.
- [x] Ground targets in the current request; keep inferred guidance advisory and exclude foreign working-set paths.
- [x] Preserve `CapsuleResult` metadata; enforce the independent 14,000-character host cap after enrichment.
- [x] Treat background/MCP notifications as zero-authority system events while preserving real requests following notices.
- [x] Isolate synthetic diagnostics; expose actual scope, disabled L2, self-test versus E2E, and non-mutating HTTP health checks.
- [x] Remove fabricated savings/compression baselines and static dashboard success claims; isolate status to configured session storage.
- [x] Repair hidden-parent file discovery and nested-venv packaging tests; count line-based file reads in metadata.
- [x] Full supported-Python suite: **230 passed in 16.25s**, exit 0; `git diff --check` exit 0; Ruff F/E9 checks on new modules PASS.
- [x] Real pre-LLM hook subprocess, packaged wheel CLI/HTTP/assets, live dashboard DOM, and three read-only health HTTP requests verified.
- Evidence: `docs/diary/2026-10-16_audit-runtime-remediation.md`; detailed operator proofs are stored outside the public repository.
- Deferred by design: production deployment, explicit repo trust, real Borg L2 delivery, destructive cleanup of historic synthetic entries, paired savings benchmark.
- Older sections below are historical claims, not a new certification of deployment, benchmarks, or the entire architecture.

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
- [x] G5.5: Local Edge Worker & LFM 2.5 2.6B-64k Autonomy: Added `src/worker/local_agent.py`, CLI command `jit solve` / `jit worker` for offline agentic bugfixing on Apple Silicon Metal via Ollama, empirical SWE-bench evaluation on `django__django-15400` (-40% turns, -67% discovery, -32% time, 100% pass, 0 PLN), Tier 2 local classifier fallback in `cascade_distiller.py`, and README case study.
- [x] G6: Evidence-linked release v0.2.11 published on GitHub with latest tag, Zenodo DOI concept and version linkage.

## Historical Milestone (not verified as complete)
Hermes JIT Context OS v0.2 with Dynamic LLM Distillation and Multimodal Ingestion

## Tech Stack
- Languages: Python 3.11+ (core, hooks, CLI); TypeScript (OpenCode / Pi integrations)
- Frameworks: none (stdlib + SQLite WAL); pytest

## Wave 2026-10-14 — v0.5.0 (cmux orchestration, Sonnet 5.5 workers)
Plan: `.planning/ORCH_2026-10-14.md` · Evidence: `/tmp/orch-jit/`
- [x] W1 stack detector: manifests over helper scripts, Vite/Vitest/pnpm, data-driven doc resources, verify_cmd from package.json (`d8b6695`). Proof: synthapse -> TypeScript, Vite, Vitest, pnpm, `pnpm run test`, 4 resources.
- [x] W2 scope_split: session dir pinned to first-created scope (`bfd8a6f`).
- [x] W3 autochecker false positives: synthetic turns, ANCHOR goals, negated/proven claims (`1c41d4e`).
- [x] W5 cwd anchors the active scope; prompt mentions only widen retrieval (`76bb9a6`, CI fix `89c1458`).
- [x] W6 per-project skill selection: `jit skills`, `.planning/SKILLS.md`, `@skill:` capsule pointers, worktree sync (`b3bc84e`, `b154222`).
- [x] Deploy: `jit install` all 5 hosts; CI Tests green.
- [ ] Hermes-side skill allowlist (`skills.enabled_only` / per-project profile) — upstream PR to NousResearch/hermes-agent.
- [ ] hook_latency (506x) profiling; GAIA runner mods; agent-behaviour mods (long_turn, duplicate_calls).

## Tasks & Phases
- [x] Phase 0: Repository Profiling & JIT Context Initialization (`/jit init`)
- [ ] Phase 1: Core Implementation & Test Harness
- [ ] Phase 2: Runtime Verification & Deployment
