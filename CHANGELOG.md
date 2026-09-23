# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.11] - 2026-09-23

### Fixed
- The SWE fixture agent loop now records per-task JEV telemetry: resolved model, HTTP status, usage, and fallback_count. A live call and a heuristic fallback are separate labels.
- Committed `benchmarks/results/swe_10_jev_live_agent_loop.json` from a fresh `jit_z_jev` run. All 10 fixture tasks used `typesafe/jev-1.13-20260917`, HTTP 200, fallback_count 0. This file is not a full SWE-bench score and is not a same-session comparison against the haystack run.

## [0.2.10] - 2026-09-23

### Fixed
- Relabeled the 10-task harness as SWE-bench-style isolated fixtures, not full Django/Astropy/Flask/Requests/Sympy/pytest checkouts.
- Separated the Synthapse 2.44x / -59% paired run from the fixture battle. The committed Gemini fixture log is 11.3% shorter wall clock (150.9s to 133.9s), -31.3% turns, -52.6% discovery ops, and 9/10 on the path labeled JIT+JEV.
- Stated that the agent loop does not record live JEV versus heuristic fallback. The live scoring replay is a separate artifact.

## [0.2.9] - 2026-09-23

### Added & SOTA
- **TypeSafe JEV Decision Engine (`src/cognitive/jev_engine.py`)**:
  - Integrated TypeSafe JEV (~typesafe/jev-latest, $0.042/M input, free output, 70-200ms) as a System 1 Epistemic Context Gate.
  - Sub-millisecond prefetch and cache read (<0.05ms) in daemon threads, eliminating latency on the agent hot-path.
  - Implemented CircuitBreaker with Invariant I6 (Fail-Open) falling back to deterministic token overlap on timeouts or rate-limits with zero agent crashes.
- **Domain & Tool Source Router (`src/context/domain_router.py`)**:
  - Deterministic routing of user intents to specific subsystems and toolsets without recursive `find`/`grep` filesystem crawls.
- **SWE-bench 10-Task Battle & Empirical Telemetry**:
  - Achieved -31.3% reduction in multi-turn cycles (4.6 vs 6.7 avg turns) and -52.6% cut in blind discovery operations (18 vs 38 ops) across Django, Astropy, Flask, Requests, Sympy, and Pytest.
  - Published interactive Tab 5 to [theones.io/benchmark/](https://theones.io/benchmark/) and architectural deep dive on [theones.io/blog/](https://theones.io/blog/jit-jev-context-the-first-production-agent-runtime).

## [0.2.8] - 2026-09-18

### Added & Fixed (Epistemic Conscience Architecture)
- **Option D: Deterministic Conscience Gate (`benchmarks/run_gaia_full_cognitive_system.py`)**:
  - Completely stripped Sumienie of LLM answer ghostwriting/rewriting rights.
  - Implemented typed `GateDecision` (`VERIFIED`, `REJECTED`, `REPAIR_REQUIRED`, `UNDECIDABLE`).
  - Hard gate automatically rejects unhandled tool exceptions and confessed model inabilities.
  - Normalizer limited to deterministic unit conversions without altering semantic payload.
- **Subconscious Schema Sanitation (`run_subconscious_extraction`)**:
  - Replaced ambiguous `core_facts` with literal `observations` (authority 0.9) and speculative `hypotheses` (authority 0.0).
  - Eliminates self-poisoning where parametric hallucinations masquerade as facts.
- **Multimodal & Multiformat File Ingestion Pipeline**:
  - Native parsing for `.docx` (tables/text), `.xlsx` (cell data + fill color codes), `.pptx` (slides), `.pdf`, `.mp3` (audio transcription), and `.png` (vision grounding).
  - Downloaded and grounded all 11 GAIA Level 1 validation files to `/tmp/gaia/files/`.
- **Comprehensive Provenance Metadata**:
  - Injected `run_id`, `attempt_id`, `git_commit`, `jit_version`, `worker_model`, `conscience_version` into all benchmark artifacts.

## [0.2.7] - 2026-09-18

### Added
- **Invariant I11: No Epistemically Equivalent Retry (`src/l0/epistemics.py`, `src/health/invariants.py`)**:
  - Implemented typed epistemic rejections (`MISSING_EVIDENCE`, `FORMAT_MISMATCH`, `CONTRADICTED`, `INVARIANT_VIOLATION`, `STALE_EVIDENCE`, `UNDECIDABLE`).
  - Prohibits duplicate retries with identical tools, inputs, or evidence states without new information, killing agent loops at the runtime boundary.
  - Doctor diagnostic updated to verify all 11 Invariants (`Invariants I1–I11: 11/11 PASS`).
- **Structured Evidence Objects & Content Anchoring (`src/l0/tool_buffer.py`)**:
  - `EvidenceObject` schema binding claims directly to content-addressed raw blobs with verifiable byte ranges (`[start, end]`).
  - Added `extract_evidence_objects` and `dereference_evidence` to eliminate lossy epistemic compression between raw tool output and reasoning.
- **3-Stage Unabridged Tool Buffer Pipeline (`src/l0/tool_buffer.py`)**:
  - Eliminated arbitrary `[:N]` string slicing across web extract, search grounding, and file read tools.
  - Complete tool outputs are written immediately to `/tmp/jit_tools/*.raw` before deterministic sanitization and intent-grounded distillation.
- **Realtime Animated ANSI Telemetry Stream (`jit stream` / `src/telemetry/stream.py`)**:
  - Live 8-10 FPS terminal dashboard displaying Token Reduction %, Latency/Timings, Active Model, Speed (tok/s), and real-time SQLite WAL ticker.
- **Full Cognitive System Benchmark on GAIA Level 1**:
  - Verified 4/5 tasks (80.0% accuracy) on GAIA Level 1 benchmarks with full numeric preservation (e.g. 0.1777 fish bag volume, 17 Earth-Moon thousand hours).

## [0.2.6] - 2026-09-15

### Added
- **Per-Session URL Routing & Session Switcher in Live Observatory (`/live?session={session_id}`)**:
  - Live preview URL now dynamically binds to the active session (`/live?session={session_id}`), locking the view to that session even if background cron jobs or parallel workers execute turns.
  - Interactive session switcher dropdown in `live_context.html` allowing one-click navigation across recent sessions from all project scopes.
  - CLI status banner updated to output exact per-session live preview links.
- **1:1 Session Isolation Sandbox (`src/config.py`, `src/l0/db.py`, `src/hooks.py`)**:
  - Partitioned per-session storage under `{project}/.planning/sessions/{session_id}/` in the project repository and central store `~/.hermes/state/ona-context/sessions/{project}/{session_id}/`.
  - Dedicated `overlay_{session_id}.db` SQLite WAL and physical `ona_context_{session_id}.xml` snapshot written on every turn.
  - Project-level symlink `{project}/.planning/latest_context.xml` and automated `.planning/.gitignore` protection.
  - Obsidian SSOT Live Session Bridge (`src/l1/obsidian_sync.py`): automatic lean snapshot in `~/Documents/Wojciech/projects/{project}.md` (`## Ostatnia Sesja JIT`) with goal, active files, and capsule pointer, completely preventing epistemic self-poisoning.
  - Extended project aliases in `src/l1/scope.py` for `boocco` (`book.co`, `booc.co`, `boocco-web`).
  - Unit & regression test suite `src/tests/test_session_isolation.py` (30/30 tests passing).

### Fixed
- **Cross-Session Context Bleeding (Process CWD Leak)**:
  - Eliminated fallback to process-level `Path.cwd()`, ensuring fresh sessions without registered CWD default to `general` instead of inheriting the gateway daemon's working directory.
- **Nested Capsule Self-Poisoning**:
  - Sanitized input prompts to ignore quoted `<ONA_CONTEXT>` blocks from previous session logs or test briefs, preventing foreign project scope hijacking.

## [0.2.5] - 2026-09-08

### Added
- **SOTA High-Resolution Coding Capsule Architecture (`src/context/cascade_distiller.py`, `src/context/compiler.py`)**:
  - Implemented 4 high-resolution levers: `[DEV RUNTIME & VERIFICATION]` (cwd, verify command, git state, allowed tools), `[WORKING SET & CONTRACTS]` (actively read/mutated modules), `[ACTIVE INVARIANTS]` (auto-extracted from `.planning/STATE.md`), and `[AVAILABLE POINTERS]` (specification & knowhow links).
  - Added JIT Prompt Enhancer generating concrete technical specifications (`Enhanced Technical Spec`), observable verification conditions (`Acceptance Criteria`), and primary target files (`Target Files`) without overriding direct user intent (Invariant I1).
  - Added automatic epistemic intent tagging (`BUG_REPORT`, `FEATURE_SPEC`, `COMMAND`, `QUERY`, `DIRECT_TASK`).
  - Calibrated elastic context budget to the optimal sweet spot: 800–1,800 tokens (`direct_fix: 6000` chars, `feature: 9500` chars), qualifying for LLM Prompt Caching (>=1,024 tokens) while completely preventing working set amnesia.
- **Value-First Open-Source Narrative & SOTA Positioning (`README.md`)**:
  - Repositioned project documentation from academic jargon to high-impact developer marketing: "The Just-In-Time Context OS for AI Agents".
  - Clear value levers highlighting empirical 2.44x speedup, 61.4% fewer turns, zero amnesia loops, and elimination of the "Haystack Tax".
- **Formal Invariant & Claims Specification (`docs/SPECYFIKACJA.md`, `docs/audits/2026-09-08-baseline.md`)**:
  - Published baseline audit and invariant contract specification for Invariants I1–I10.
- **Tool Evidence Lifecycle (`src/l0/tool_evidence.py`, `src/l0/overlay.py`)**:
  - Typed tool evidence models (`EvidenceStatus`, `ClaimScope`, `OperationKind`) enforcing strict verified boundaries for mutations, process exits, and reads.
- **Unit Test Suite for Coding Capsule (`src/tests/test_coding_capsule.py`)**:
  - 28/28 unit and invariant tests passing (exit 0).

### Fixed
- **Literal Fidelity & Cleaner Error Masking (`src/context/cascade_distiller.py`, `src/context/renderer.py`)**:
  - Neutral omission markers replacing fabricated progress phrases; preserved error keywords in terminal output.
  - XML attribute and content escaping preventing premature tag closure and instruction injection.
- **Synthetic Experiment Labeling (`benchmarks/EXP-001..004.json`, `src/health/`)**:
  - Explicitly labeled synthetic baseline datasets and decoupled them from empirical live telemetry.
- **Path Traversal Containment (`src/l1/project_cache.py`)**:
  - Enforced `is_relative_to` checks preventing traversal outside allowed vault or project directories.

## [0.2.4] - 2026-09-08

### Added
- **Physical Benchmark EXP-008 (`src/health/exp008_tool_epistemics.py`)**:
  - Live E2E test verifying Invariant I3/I4: assistant assertion without runtime tool proof carries 0.0 weight; verified tool failure is reported with 100% truth against `gemini-3.8-flash`.
- **Dynamic Hot-Reloading (`src/hooks.py`)**:
  - `hot_reload_jit_modules()` in `pre_llm_call()` automatically detecting file `mtime` changes in `~/.hermes/plugins/ona-context/` and reloading modules in `sys.modules` without requiring session restarts.
- **Runtime Session CWD Tracking (`src/hooks.py`, `src/l0/db.py`, `src/l0/overlay.py`)**:
  - Added `last_cwd` column to `sessions` table in SQLite WAL overlay.
  - Automatically tracking `cd` commands and terminal runner directories in `post_tool_call()`.

### Fixed
- **Strict Scope Isolation & Anti-Bleed (`src/l1/project_cache.py`, `src/l1/scope.py`)**:
  - Scope `general` or `unknown` returns `None` rather than accidentally injecting an arbitrary working directory's `STATE.md`.
  - Added project name normalization (`normalize_project_name()`) and expanded `KNOWN_PROJECTS` with `synthapse`, `hermes-jit-context-os`, `jit-context`.
- **Harness Message Filtering & User Intent Protection (`src/hooks.py`, `src/l0/overlay.py`)**:
  - Added `is_synthetic_harness_message()` detecting curator skill triggers, async delegation callbacks, `/btw` side-questions, and canon injections.
  - Sinks synthetic harness events with `origin='harness_event'` (reduced authority) and retrieves latest authentic `direct_user` goal from SQLite WAL.

## [0.2.3] - 2026-09-08

### Fixed
- **Runtime Tool Verification & Fact Extraction (`src/hooks.py`, `src/l0/overlay.py`, `src/l0/epistemics.py`)**:
  - Fixed authority calculation for `tool_observation` (0.9) and `runtime_tool_verified` (1.0).
  - Added deterministic tool execution parser in `post_tool_call`: verified `exit_code: 0` for commands and verified writes for files are extracted as concrete facts with authority 1.0.
  - Sinks verified tool outputs directly into SQLite WAL `overlay` table so runtime proofs survive across session turns.
- **Invariant I1 Enforcement & Prior Instructions Preservation (`src/context/cascade_distiller.py`, `src/context/compiler.py`)**:
  - Guaranteed verbatim preservation of direct user prompt in `[CURRENT — direct user]`.
  - Added dedicated `[PRIOR USER INSTRUCTIONS]` and `[VERIFIED RUNTIME PROOFS (Authority 1.0)]` sections to `<ONA_CONTEXT>` capsule.
  - Implemented `CapsuleResult(str)` wrapper enabling backward-compatible string checks and tuple unpacking.
  - Added comprehensive test coverage in `src/tests/test_invariants.py` for tool verification and anti-hallucination guarantees.

## [0.2.2] - 2026-09-08

### Added
- **SOTA Linear & Raycast Observatory Dashboard (`src/health/dashboard.html`)**:
  - Dark graphite `#090A0F` canvas with translucent glassmorphic panels and subtle emerald status glows.
  - Zero-emoji UI: 100% crisp Lucide SVG vector iconography (1.5px stroke).
  - Live Bento Grid featuring real-time JIT Scope badge, L0/L1 latencies, and active model quotas.
  - Interactive Turn Timeline with live modal inspector for generated `<ONA_CONTEXT>` capsules.
  - Dedicated Invariants I1–I10 verification matrix with real-time status pulses.

## [0.2.1] - 2026-09-08

### Added
- **Active Clarification Gate (`src/context/compiler.py`, `src/hooks.py`)**:
  - Automatically assesses context certainty (`confidence < 0.85`).
  - Injects mandatory `<CLARIFICATION_REQUIRED>` directive into prompt preventing speculative or irreversible actions.
  - Surfaces real-time `⚠️ LOW CONF` indicator badge in CLI stream.
- **Deep & XHigh Knowledge Synthesis (`src/init.py`)**:
  - `jit init --tier deep`: Automatically links relevant knowhow canon from `~/Documents/Wojciech/knowhow/`.
  - Generates authoritative, up-to-date SOTA architectural reference cards (FastAPI routes/auth, SQLite WAL pragmas, asyncpg pools, Next.js server actions, Docker multi-stage).
- **Local Offline Fallback in Cascade Distiller (`src/context/cascade_distiller.py`)**:
  - Seamless fallback to local Ollama `qwen2.5-coder:7b` when offline or without Google API.
- **Observatory Telemetry Extensions (`src/hooks.py`)**:
  - Added live tracking of `confidence`, `complexity`, and `budget` to `/tmp/hermes-jit-live.json`.

## [0.2.0] - 2026-09-08

### Added
- **3-Tier Cascade Distillation Engine (`src/context/cascade_distiller.py`)**:
  - LLM Semantic Classifier (Gemini Flash with `thinkingBudget: 0`) delivering sub-1.2s extraction.
  - Verbatim protection of critical contracts (file paths, ports, error messages, export identifiers).
  - Elastic capsule assembler automatically scaling from 750 tokens up to 3,500 tokens based on task complexity.
- **Automated Project Profiler & Ingestion (`/jit init` / `src/init.py`)**:
  - Automatic language, framework, database, and test suite inspection.
  - Bidirectional sync to Obsidian SSOT (`~/Documents/Wojciech/projects/<name>.md`) and `.planning/STATE.md`.
  - Context7 and Hugging Face resource gap detection.
- **Real-Time CLI Telemetry Badges (`src/hooks.py`)**:
  - Direct stderr streaming of active scope, L0/L1 latencies, compilation duration, and capsule character count.
- **Comprehensive Benchmark Suite (`benchmarks/`)**:
  - EXP-005 local model evaluation on Apple Silicon M2 Pro.
  - Clean 1:1 refactoring duel between local Qwen-7B and cloud models on `retro-plumber-run`.
  - Distillation quality and speed comparison across local and cloud engines.

## [0.1.1] - 2026-09-07

### Added
- **EXP-005 Benchmark**: Real-time evaluation of local LLMs on Apple Silicon (M2 Pro 16 GB).
- Script `benchmarks/run_local_model_benchmark.py` evaluating Invariants I1, I3, I5 across:
  - `Qwen2.5-Coder-7B` (Ollama / Metal acceleration)
  - `LFM-2.5-1.2B` (LM Studio / MLX 8-bit)
  - `Mem-Agent` (HuggingFace / MLX 4-bit)
- Verified 100% epistemic correctness (3/3 PASS) for `Qwen2.5-Coder-7B` under JIT Context OS vs 0% (0/3 FAIL) under Naive Haystack, with 2.0x-3.0x inference speedup and ~60% prompt token reduction.

## [0.1.0] - 2026-08-31

### Added
- Initial public release of Hermes JIT Context OS & Borg Broker.
- L0 Hot-Path SQLite WAL overlay engine.
- L1 Scope Hysteresis filter.
- L2 Bounded Deep-Path Broker client.
- Invariants I1–I10 test suite and initial benchmarks (EXP-001..EXP-004).
