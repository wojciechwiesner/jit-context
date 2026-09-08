# Promise-to-Proof Remediation Implementation Plan

> **For Hermes:** Use the subagent-driven-development skill when implementation is authorized. Execute one bounded task at a time, with independent regression review. This document authorizes planning only, not code changes, commits, dispatch, or deployment.

**Goal:** Make published JIT Context claims match implemented, repeatably verified behavior; repair the runtime rather than merely weaken its documentation.

**Architecture:** Retain local SQLite WAL operational state, a deterministic compiler, scoped project retrieval, and optional advisory remote retrieval. Separate instruction authority from evidence of a specific observed outcome. Optional LLM classification may suggest selection but must not create facts, promote trust, change active scope, or block the hot path.

**Tech stack:** Existing Python/SQLite runtime and pytest. Declare existing HTTP dependencies explicitly. Select and pin a tokenizer in the budget task after checking current documentation; do not invent token counts from character ratios.

**Baseline:** Git master/tag v0.2.4 = `35181dffb696b6d78b193ee097eba247f4345583`; local `src/hooks.py` has pre-existing uncommitted edits. The active-project path is a symlink to this repository. Installed plugin hook/compiler hashes matched working-copy files during audit; this is not a full deployment verification.

**Audit evidence:** `/tmp/jit-audit-core.md`, `/tmp/jit-audit-core-repro.py`, `/tmp/jit-audit-core-verified.log`, `/tmp/jit-audit-evidence.md`, `/tmp/jit-audit-tests.log`, `/tmp/jit-audit-runner.py`, `/tmp/jit-audit-probes.py`, `/tmp/jit-audit-package.log`. These are local audit artifacts, not release assets. Existing 27 tests pass in an isolated environment but miss the documented defects. No live model benchmark was run by this audit.

## 1. Release contract and non-goals

Target a proposed v0.3.0 prerelease because trust semantics, budgets and installation behavior change; retain the v0.2.4 tag and history. Confirm the final release number before release. First supported adapter: Hermes. Other harnesses remain planned until each has its own executable compatibility test.

Do not promise universal absence of hallucinations, zero 429s, arbitrary model compliance, fixed speedup, or universal cache hit rates. Deterministic guarantees apply at the compiler's input/output boundary, not inside an LLM. User intent has precedence over earlier task instructions; it does not turn an assertion about reality into runtime evidence.

The small capsule is an *additional dynamic context block*, not a replacement for the entire system prompt, schemas, transcript or current user message. Full-prompt cost and latency must be measured separately.

No broad rewrite, additional remote memory engines, multimodal features, or new commercial SaaS surface in this milestone. Four high-resolution sections (CODEBASE MAP, INTENT, DEV RUNTIME, ACTIVE INVARIANTS) follow the integrity work and must fit the same provenance and budget contract.

## 2. Promise → implementation → evidence matrix

| Contract | Required implementation | Release evidence |
|---|---|---|
| Only direct user input becomes current/prior user instructions | Typed origin allowlist at ingest AND compiler/fence boundaries | Full-hook direct/harness/external/assistant replay tests |
| No promotion of assistant speculation | No implicit authority inheritance through summaries, tool echoes or classifiers | Provenance-laundering adversarial cases |
| Runtime evidence describes only the observed operation | Validated tool-specific result, resource/version/time, explicit unknown/failure states | False/pending/ambiguous results never render as verified |
| RYOW and monotonic, idempotent events | Transactional append and stable delivery identifier | Repeat delivery, concurrent writers, rollback and replay tests |
| Stable and isolated scope | One persisted resolver with explicit switches and retrieval-only references | Multi-turn, multi-session, cwd, symlink and path-containment tests |
| L2 is advisory and bounded | Result consumed with provenance; global deadline; no DB transaction across I/O | Controlled server tests for slow/trickling/invalid responses and breaker recovery |
| Capsule ≤1,500 tokens | Tokenizer-specific final serialization check, bounded overflow path | Multilingual/code/XML/large-input property tests |
| Local hot path is independent of network/LLM | Disabled gate first; deterministic compile; optional bounded enrichment | Network forbidden tests and end-to-end hook latency distributions |
| Health reports actual checks | PASS/FAIL/SKIP/UNKNOWN, no constant PASS or invented metrics | Injected failures lead to FAIL/nonzero exit |
| Installation works on a clean machine | Wheel contents, dependency and entrypoint correctness | Fresh wheel install and packaged CLI smoke tests without repo on sys.path |
| Claimed speed/cost/quality improvement | Equal-information paired experiment through real adapter | Versioned raw trials, frozen grader, paired uncertainty and actual model usage |
| Cache friendliness | Stable prefix placement | Captured provider request/usage evidence; unsupported means UNKNOWN |

Create a single versioned invariant registry mapping legacy I1–I10 labels to explicit contracts and tests. README, doctor and dashboard consume that registry. Do not silently reinterpret an existing invariant number.

## 3. Execution discipline

Each task below is a small work package, split into 2–5 minute steps: (1) add one failing regression, (2) run and preserve RED output, (3) implement the minimal fix, (4) rerun targeted tests, (5) run affected integration tests, (6) record result in STATE/diary. Stop each work block within 30 minutes; split rather than skip verification.

Before execution: inspect current git status/diff and preserve existing edits. Do not overwrite or auto-commit them. Use temp state, HOME and HERMES_HOME, disable credential inheritance and pytest plugin autoload. Tests must never access live plugin state or dispatch real tools. No commits/pushes without authorization; when authorized, update CHANGELOG and use the mandatory author trailer.

### Phase 0 — Evidence integrity and reproducible baseline

**T00 — Preserve audit evidence.** Create `docs/audits/2026-09-08-baseline.md` and sanitized regression fixtures under `src/tests/fixtures/`. Port audit repro cases from /tmp; preserve limitation labels (component reproduction versus full hook). Do not publish live DBs, personal content or credentials. Record source SHA, working diff fingerprint, commands and outputs. Acceptance: a new checkout can run baseline repro cases without /tmp files or the author's machine.

**T01 — Correct experimental status, without erasing history.** Modify `src/health/experiment_runner.py`, `src/health/experiment_suites.py`, `src/health/server.py`, `src/health/dashboard.html`, `benchmarks/EXP-001.json` through `EXP-004.json`, `README.md`, `CHANGELOG.md`. Mark generated datasets `synthetic_demo`, exclude them from measured aggregates and badges, and require explicit demo mode. Preserve original values with provenance/correction notes. Label unreproduced Synthapse claims historical/unverified; do not merge conflicting runs. Remove unsupported absolute guarantees from current product claims. Acceptance: synthetic or unknown results cannot appear as measured PASS, speedup or savings.

**T02 — Establish invariant and evidence schemas.** Create `docs/SPECYFIKACJA.md` and `src/tests/test_claims_registry.py`; update `src/health/invariants.py`. Define contract IDs, test references and allowed statuses. Define `observed_success`, `observed_failure`, `unknown`, `superseded`, `expired`; authority is not truth. Acceptance: every published guarantee has a test reference and every failed/absent check is visible.

### Phase 1 — Repair trust boundaries (release blocker)

**T03 — Provenance at all boundaries.** Modify `src/hooks.py`, `src/l0/epistemics.py`, `src/l0/recent_fence.py`, `src/l0/overlay.py`, `src/context/compiler.py`. Create `src/tests/test_provenance_boundaries.py`. Test identical content delivered as direct_user, harness_event, external and assistant. Only direct_user enters instruction sections. Unknown origins fail closed for trust, not for host availability. Harness notifications may remain observations; never resurrect their embedded task text as a user command. Acceptance: tests cover full ingest → DB → fence → capsule, including post-compression replay.

**T04 — Typed tool results and evidence lifecycle.** Extract parsing from `src/hooks.py` into proposed `src/l0/tool_evidence.py`; modify overlay/compiler. Create `src/tests/test_tool_evidence.py`. Validate provider/tool result shapes, explicit success flags, exit codes and scope of the claim. `verified=false`, pending, missing success and contradictory flags yield unknown/failure, not verified. A successful shell command is evidence of that command's exit, not proof of deployment. Bind evidence to event, session, resource, operation, version/hash if available, timestamp and validity. Later conflicting mutation invalidates the current-state inference while preserving historical success. Read-only errors do not erase historical events. Acceptance: success→failed mutation, delete, resource reuse, stale deploy evidence, malformed payloads and echoed assistant statements all have explicit expected outcomes.

**T05 — Literal fidelity and classifier containment.** Modify `src/context/cascade_distiller.py`, renderer/compiler. Create `src/tests/test_literal_fidelity.py`. Replace fabricated progress-success wording with neutral omission markers; preserve errors. Require critical fragments to be exact source spans. Validate classifier schema, enum values and finite confidence range; reject malformed/NaN/out-of-source values. Classifier cannot override active_scope or label its own summary as verified/direct user. Escape serialized attributes/content; test closing tags and instruction-like text. Acceptance: adversarial fixtures retain provenance and no generated summary becomes a new fact.

**T06 — Safe modes and privacy.** Modify `src/hooks.py`, `src/config.py`, classifier, telemetry collector. Create `src/tests/test_hook_modes.py`. `disabled` returns before ingest, telemetry writes, DB/network access or compilation. `shadow` computes isolated telemetry but never injects; document its allowed effects explicitly. Default local-only; cloud enrichment requires explicit provider configuration/consent, no direct read of ~/.hermes/.env. Honor profile paths. Replace global /tmp state with profile/session-scoped atomic writes and restrictive permissions; reject unsafe symlink targets. Acceptance: filesystem/network spies prove mode contracts and two profiles/sessions cannot overwrite each other's status.

### Phase 2 — State, retrieval and budget correctness

**T07 — Transactional events and safe schema migration.** Modify `src/l0/db.py`, overlay, recent_fence; reconcile duplicate legacy paths in `src/session_overlay.py` only after tracing callers. Create `src/tests/test_event_lifecycle.py`. Persist stable delivery ID, unique within session; do not deduplicate intentional repeated user text. Event/overlay/outbox/sequence updates are atomic. Introduce explicit schema version and migration for last_cwd and evidence fields. Acceptance: repeated delivery yields one event; distinct deliveries with identical text yield two; parallel writes are monotonic; failed transactions leave no partial overlay. Upgrade a fixture v0.2.4 DB in temp and preserve all records. Production migration requires backup and separate approval.

**T08 — Single scope authority and containment.** Modify `src/l1/scope.py`, `src/l1/project_cache.py`, compiler and hooks. Create `src/tests/test_scope_lifecycle.py`. Persist candidate/turn count/epoch atomically; explicit direct user switch wins immediately, reference-only queries expand retrieval without switching. Use session cwd supplied by the adapter, not process-global cwd. Cache key includes resolved workspace/profile/scope. Reject traversal/absolute scope IDs and symlink escapes after resolve; define allowed project roots explicitly. Acceptance: boocco→continue stays boocco; concurrent sessions remain isolated; cwd updates and conflicting LLM scope suggestions cannot redirect trusted lookup.

**T09 — Real bounded L2.** Modify `src/l2/client.py`, `src/l2/circuit_breaker.py`, `src/broker_client.py` after tracing active/legacy call paths, compiler and classifier. Create `src/tests/test_retrieval_deadline.py`. Pass returned facts into a separately tagged advisory section with citations. Release SQLite transactions before network I/O. Use one monotonic end-to-end deadline, including retries/fallback, and bounded cancellation/resources; never create unbounded orphan workers. Proposed L2 budget 600 ms; deterministic path continues with explicit unavailable/timeout metadata. Remove synchronous 6s+6s classification from the hot path; optional enrichment must share the deadline or arrive on a later turn with freshness checks. Acceptance: local controlled server tests cover slow body trickle, DNS/connect abstraction, malformed JSON, breaker open/half-open/recovery, concurrent calls and DB failure; elapsed upper bound includes documented scheduler tolerance. No real provider credentials.

**T10 — Hard budget without losing the user request.** Modify assembler/renderer/compiler; proposed `src/context/budget.py`; create `src/tests/test_capsule_budget.py`. Standard contract: final dynamic block including clarification/metadata ≤1,500 tokens for a declared tokenizer/model. Unsupported tokenizer uses a proven conservative bound or skips enrichment with explicit status, never a chars/4 guess. Preserve the original current user message unchanged outside the capsule. Oversized instructions are not silently truncated: keep source references and explicit omission status in the capsule; adapter must prove the original message is retained. Drop low-priority recalled/history/project sections first, preserve complete events and well-formed structure. If mandatory envelope cannot fit, return no enrichment plus diagnostic rather than violate the ceiling. Acceptance: Polish/CJK/code, long paths, hostile XML, giant current intent, large proofs and all clarification branches obey the final measured limit.

**T11 — Hook integration and telemetry accuracy.** Modify hooks, `src/telemetry/collector.py`, `src/telemetry/db_schema.py`, health server. Create `src/tests/test_hook_integration.py`. Consume CapsuleResult.meta correctly; record actual stage and total durations, mode, budget, dropped items and source IDs without sensitive raw text. Eliminate constant latency/cache/quota claims or label estimates and configured values. Test hot reload consistency and fallback on import/DB/config failures. Acceptance: actual hook roundtrip in an isolated Hermes adapter retains direct message, uses compiled metadata and degrades without breaking the host. Do not claim cache hit rate from stable prefix alone.

### Phase 3 — Installation and honest health

**T12 — Package and CLI.** Modify `pyproject.toml`, `src/plugin.yaml`, `install.sh`, README/CITATION/CHANGELOG; inspect `src/health/server.py` and doctor entrypoints before mapping scripts. Create `src/tests/test_distribution.py`. Align all version metadata; declare requests/httpx if retained; select actual supported Python minimum and test it. Explicitly configure package discovery, namespace-safe imports, package data/dashboard/plugin inclusion. Correct Observatory entrypoint rather than point to a nonexistent module. Installer installs dependencies and adapter intentionally, never masks failures; reruns are safe. Acceptance: build sdist/wheel from temp copy, install in clean venv, run both CLIs without repository/PYTHONPATH, bind test server only on ephemeral localhost, fetch actual health route, stop it, verify nonzero failure exit. Test no-key/offline install behavior. Use proposed `src/tests/test_distribution.py` as subprocess harness with isolated HOME.

**T13 — Health and CI as release gates.** Modify `src/health/doctor.py`, invariants, autocheck and server; create `.github/workflows/ci.yml`, `src/tests/test_health_truthfulness.py`. Remove unconditional PASS; unsupported checks become SKIP/UNKNOWN. Run lint, unit, adversarial, integration, package and migration tests on declared Python versions. Live paid benchmarks are a separate manually approved job, not PR CI. Acceptance: injected failed contract produces failed health and nonzero CLI exit; missing benchmark evidence cannot produce a green claim badge. No workflow deploys automatically.

### Phase 4 — Four-section coding capsule, then empirical validation

**T14 — Provenance-backed coding capsule.** Modify compiler, project_cache and renderer; create `src/tests/test_coding_capsule.py`. Specify CODEBASE MAP from bounded inspected project sources with paths/hashes; INTENT from current direct user input (classifier suggestions labelled separately); DEV RUNTIME from scoped actual git/test/tool observations with freshness; ACTIVE INVARIANTS from explicit project constraints, max three. Do not treat STATE 'done' as test evidence. No full repo scan or shell git process on every hot-path turn; cache with invalidation and bounded refresh. Acceptance: changes in files/cwd/branch invalidate relevant data; no stale test success; every section has provenance; total budget remains enforced. If required context cannot fit, explicit retrieval reference, not invented content.

**T15 — Replace simulated comparisons with reproducible harness.** Create `benchmarks/paired_runtime.py`, `benchmarks/schemas/run.schema.json`, `benchmarks/tasks/manifest.json`, `src/tests/test_benchmark_grading.py`. Preserve old scripts as labelled historical/demo material; repair grading in `run_local_model_benchmark.py`, `exp006_synthapse.py`, `exp007_tulimy.py`, `exp008_tool_epistemics.py`, `benchmark_distillation.py`, `run_coding_task_8k_benchmark.py`. Replace substring correctness with structured decisions/executable assertions; test 'pomyślnie' versus 'Nie', contradictions and incomplete answers. EXP-008 must include fact_key/resource and prove the failure reaches the actual capsule before any model call. Count actual tokens; measure TTFT from first streamed token rather than prompt evaluation duration.

Experiment protocol, fixed before collecting outcomes:
- Two baselines: realistic equal-information no-JIT harness, and optional naive long-history demo (labelled, not primary).
- Exactly the same source events, user task, repo checkpoint, permissions, tool budget, model/version/settings and hidden acceptance tests. JIT capsule built by runtime, never handwritten with the answer.
- Initial suite: ten frozen tasks, three repeated paired trials per task; include coding, scope switch, corrections, tool failure, stale proof and unrelated retrieval. This is a pilot protocol, not a claim of statistical power or universal representativeness.
- Randomize/counterbalance run order, separate clean worktrees/sessions, record warm/cold cache and model loading. Include runtime compilation/retrieval/classification in end-to-end wall time and cost. Log failures, timeouts and all attempted trials; no cherry-picking.
- Store prompts, sanitized source events, final capsule, request configuration, tool trajectories, test results, model usage, output patch, start/end timestamps, environment, source SHA and artifact hashes. Publish deterministic reproduction without secrets.
- Primary quality: identical hidden executable acceptance tests and no critical provenance violation. Report paired success difference and uncertainty, not only speed among successes. Report conditional speed separately; include failure/timeouts in overall cost-to-success.
- Report paired latency/cost distributions and task-clustered uncertainty. Cache read ratio uses provider usage fields; unsupported fields remain UNKNOWN. 429 rate is observed, never guaranteed zero.
- Optional ablation disables real components one at a time on identical trials. No literal precomputed 'ablation results'. Independent reviewer grades before seeing variant labels.

Acceptance: offline fake-provider tests validate the harness mechanics but are labelled synthetic; they are never performance evidence. A paid/live pilot requires explicit budget/provider approval. If quality regresses or uncertainty does not support improvement, do not publish a positive speed/quality claim; expand evaluation or repair runtime.

### Phase 5 — Release readiness, then separately approved canary

**T16 — Evidence-linked release.** Every README quantitative claim links to an immutable run artifact and describes its scope/model/sample size. Replace manual PASS counts with actual CI status. Generate checksum manifest from release files with self-file excluded. Documentation includes limitations, privacy defaults, supported adapter, complete quickstart, migration and rollback. Create `docs/diary/<execution-date>_promise-to-proof.md` with decisions and real command results; update STATE only for verified gates.

**T17 — Canary plan (not authorized by this document).** Before deployment inspect deployment registry, `docker ps` in correct context, and target port; stop on conflict. Back up installed plugin and SQLite with a consistent SQLite backup operation, retaining permissions. Separate test profile and DB first, then explicitly approved shadow run with local-only networking, then active canary. Minimum acceptance: seeded replay passes, no unexpected trust/scope transitions, actual message retention, latency distribution and no unexpected data egress; an idle time window alone is not evidence. Roll back on provenance violation, budget violation, host exception, state corruption or unapproved network call. Restore compatible plugin/state together; never restore a DB backup over newer user events without reconciliation/approval. Read back plugin hashes, mode and health after switching. No auto-deploy.

## 4. Verification commands and expected results

New test paths above are planned files, not claims that tests currently exist. After T00 establishes hermetic fixtures:

- Trust: `python -m pytest -q src/tests/test_provenance_boundaries.py src/tests/test_tool_evidence.py src/tests/test_literal_fidelity.py src/tests/test_hook_modes.py`
- State: `python -m pytest -q src/tests/test_event_lifecycle.py src/tests/test_scope_lifecycle.py src/tests/test_retrieval_deadline.py src/tests/test_capsule_budget.py`
- Adapter/product: `python -m pytest -q src/tests/test_hook_integration.py src/tests/test_distribution.py src/tests/test_health_truthfulness.py src/tests/test_coding_capsule.py`
- Measurement: `python -m pytest -q src/tests/test_benchmark_grading.py src/tests/test_claims_registry.py`
- Full regression: `python -m pytest -q src/tests/`

Run with isolated HOME/HERMES_HOME/JIT_STATE_DIR/JIT_DB_PATH, no inherited secrets, `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; fixtures must block unapproved network and live-state access. Redirect outputs to /tmp and preserve sanitized release evidence later. Expected result for each implemented task: actual failing regression before fix, then exit 0 after fix; do not predeclare a fixed passing test count.

Targets (not measured promises): isolated L0 p95 ≤3 ms; warm deterministic compiler p95 ≤10 ms; remote work deadline 600 ms with explicit test scheduler tolerance. Measure full hook separately, including cold cache and lock contention. If hardware/workload misses a target, show actual percentiles and narrow the documented SLA or optimize before release.

## 5. Gates and order

G0 evidence labelled + invariant spec → G1 provenance/evidence/modes pass → G2 state/scope/L2/budget pass → G3 real adapter/package/health/CI pass → G4 coding capsule passes → G5 paired benchmark reviewed → G6 approved release/canary.

T03–T06 share trust boundaries: one owner, no concurrent editing of hooks/compiler. Independent test author may work in isolated files; no bulk worker dispatch. Packaging can be prepared after schemas settle. Benchmark protocol can be reviewed early but live execution waits for G4.

A gate is CLOSED only with commit/worktree identity, command, exit code and artifact showing the asserted behavior. Passing the plan's checklist is not a substitute for meeting the product contracts.

## 6. Status of this document

Planning complete; implementation not started. No runtime changes, no published claim edits, no benchmark rerun, no commit, no deploy are implied by this plan. First execution block: T00–T02, followed by T03–T06 before any feature expansion.
