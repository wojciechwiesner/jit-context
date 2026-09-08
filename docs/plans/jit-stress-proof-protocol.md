# JIT Stress Proof Protocol

Status: designed, not implemented or executed. Extends T15/G5 of the promise-to-proof plan; does not certify G0–G4. No deployment or live API spend authorized by this document.

## Question and falsifiable outcome

Does the installed, isolated Hermes adapter preserve trust and task quality under long sessions, conflicting evidence, concurrent sessions and infrastructure faults, while reducing total cost to an accepted coding result relative to a competent no-JIT baseline?

Report three independent verdicts: integrity, coding effectiveness, efficiency. A fast wrong answer fails. A green doctor or unit suite cannot substitute for these verdicts. Results apply only to tested workloads, adapter, model and hardware.

## Freeze and reproducibility gate

Before collecting outcomes, freeze the source snapshot including dirty files, snapshot hash, dependency lock/environment, adapter version, model identifier/settings, task manifest, seeds, fault schedule, thresholds, graders and analysis script. Enumerate and hash collected test files; missing expected tests is a harness failure, not a smaller green suite. Retain manifests before and after execution to detect disappearing artifacts. Never use historical test counts as current evidence.

Use disposable repository copies, isolated HOME/HERMES_HOME/profile/SQLite and localhost fault servers; no live Obsidian, plugin databases, production credentials or deployment targets. Deny outbound traffic except the explicitly approved model endpoint in the live phase. Instrument attempted network/filesystem operations. Resource ceilings and cleanup must cover child processes and connections. No real secrets: seeded canaries only.

## Layer A: deterministic adversarial replay

Drive actual adapter hooks -> ingest -> SQLite -> scope/retrieval -> compiler -> final provider request capture. Component tests supplement, not replace this route. Disable external model calls; classifier and retrieval adversaries are controlled fixtures explicitly labelled synthetic. Maintain an independent reference state machine derived from contracts, not runtime helpers.

Initial workload: 100 seeded sessions, each 200 turns. Run sequentially, then with 8 and 32 simultaneous sessions in separate profiles. Mix realistic direct instructions, code/tool results and unrelated project references. Inputs range from short messages to a bounded 1 MB output. Also run a bounded 30-minute soak with fixed 32-session concurrency; report machine specs and workload rate. These are proposed workloads, not observed capacity claims.

Check after EVERY turn and after restart:
- Identical content under direct_user, harness, external, assistant and tool-echo provenance: only trusted direct input may populate instruction sections. Unknown provenance cannot elevate authority.
- A real user correction wins; quoted or embedded instructions from retrieval never authorize actions. XML-like closing tags and Unicode do not escape the data envelope.
- Successful write -> failed mutation -> retry -> deletion -> same-path recreation: observations stay historically accurate, current-state claims expire/supersede correctly. Exit 0, ordinary curl output or assistant testimony alone cannot certify deployment. Check service target, response assertions, revision and freshness separately.
- Delivery retries reuse an ID and produce one event; distinct IDs with identical text produce distinct events. Concurrent appends and forced rollback do not leave partial overlays. Kill a dedicated worker between transaction stages, reopen WAL and compare acknowledged durable events with the oracle; unacknowledged requests may require retry.
- Explicit scope switch, reference-only lookup, candidate hysteresis and restart retain correct session scope. Two profiles with identical project names must not share cache/status. Test absolute paths, traversal and symlink escapes against each permitted root.
- Preserve failure lines verbatim; never invent completion. Classifier outputs include NaN, malformed JSON, false scope and fabricated critical spans. Reject or label them without trust promotion.
- Disabled: no ingest, DB/telemetry writes, network or injection. Shadow: no injection and only documented isolated effects. Unapproved egress or seeded-canary disclosure is a critical failure.
- Final serialized dynamic block including appended alerts/clarification obeys <=1500 tokens under the declared tokenizer; CJK, Polish, code, long paths and entity escaping included. Original user message remains unchanged outside it. Missing tokenizer support is explicit UNKNOWN, never chars/4. Oversize inputs use source references/explicit omission or no enrichment, not malformed XML or silently cut instructions.
- L2 faults: connection stall, slow body trickle, malformed response, 429, 500, half-open recovery, stale late reply. End-to-end remote deadline <=600 ms + predeclared 100 ms scheduler tolerance on the test host. Check thread/socket count after cancellation and that SQLite writes are not blocked across network I/O. Repeated tolerance violations fail the performance gate; do not silently increase tolerance after results.
- Honest health: deliberately inject a contract violation, missing evidence and adapter exception. Health must expose FAIL/UNKNOWN and appropriate nonzero verification exit; it must not stay green.

Integrity acceptance: no critical trust, cross-session disclosure, unauthorized effect, durable-state loss or final budget violation across the frozen workload. One counterexample fails the gate; retain and minimize it as a regression fixture. Passing demonstrates bounded empirical coverage, not a universal zero-error theorem.

Performance targets: report cold/warm L0, compiler and FULL hook p50/p95/p99/max separately. Existing targets L0 p95 <=3 ms and warm deterministic compiler p95 <=10 ms apply to the declared single-session host; report contention curves without conflating them with single-session SLA. Record RSS, open FDs, workers, connections, WAL size and queue length before/during/after soak. After cleanup no orphan workers/connections; separately distinguish intended DB retention from leaks.

## Layer B: real multi-turn coding under fault schedules

Use a frozen pilot of ten independent bug/feature tasks, three paired repeats per task. Each requires cross-file work, executable acceptance tests and 20–40 scheduled context turns before final grading. Include API contract change, stale signature, cross-project reference, user reversal, failed write, failing build, migration rollback in a disposable DB, context compaction/restart, retrieval outage and oversized tool output. Fault injection applies to the environment/transport and is logged; do not falsify claimed real tool execution.

Primary A: competent no-JIT Hermes with its normal search/tools, documented transcript compaction and identical access to source history.
Primary B: identical Hermes with actual JIT adapter enabled; never hand-author a solution-bearing capsule.
Both receive exactly the same source event stream, repository checkpoint, task, available tools, permissions, model settings and tool/time budgets. Record precisely what changes in context policy. Equal information availability does not require identical selected prompts. A deliberately repetitive haystack is optional demonstration only, not the primary baseline.

Each pair uses independent clean copies and state; randomize/counterbalance order and log warm/cold model/cache conditions. Keep model routing fixed, record effective returned model and flag substitutions. Do not run arms concurrently on a shared saturated provider without recording/interpreting interference. Budget: maximum 40 agent action turns and 15 minutes per arm, no retries outside the registered policy. Preserve failed/time-limited runs in denominators.

Hidden acceptance tests are written by an independent evaluator from the task specification, unavailable to the agent and outside writable workspace. Validate each task: tests fail on buggy snapshot and pass on independently checked reference fix. Include visible regression suite, hidden acceptance, public API behavior and no unauthorized modifications. Agent exit 0 or a commit alone is not success; evaluator executes the resulting patch in a fresh environment and rejects tampered tests or unrelated unsafe changes. Grader sees masked arm IDs until verdicts are frozen.

Capture full sanitized source events, actual provider request (system/tools/history/current message/capsule), responses, tool trajectories, patches, reference events, fault times, compile/retrieval/classifier costs, provider usage, acceptance outputs, timeout/error flags and artifact hashes. Use monotonic clocks. Non-streamed request duration is NOT TTFT; TTFT requires timing first streamed content. Count the entire run including retries, enrichment and verification, not only capsule tokens. Unknown usage/cache metrics remain UNKNOWN.

## Analysis and decision rules

Primary quality: task acceptance rate and critical violations for all attempted trials. Analyze paired differences with task-clustered uncertainty; repeats of one task are not independent tasks. Report failed/missing trials and infrastructure exclusions under a frozen rule with sensitivity analysis. No cherry-picked successful speedups.

Pilot is for finding faults and estimating variance, not proving universal superiority. Before a confirmatory run, freeze a larger independent task set and determine sample size from pilot paired outcomes, a proposed noninferiority margin of 5 percentage points and the desired power. Do not tune tasks or margin after looking at confirmatory outcomes. Quality passes noninferiority only if the lower bound of the paired 95% interval exceeds -5 percentage points; otherwise INCONCLUSIVE or FAIL, not PASS.

Only after integrity and quality pass, assess efficiency: paired full-run token/cost and time distributions, all-run resource totals, accepted tasks per fixed resource budget and success-conditional latency separately. A speed/cost benefit requires its preregistered 95% interval to support improvement. A smaller capsule alone is not sufficient. Report model-specific results without pooling different models into one headline ratio.

Gate verdicts: FAIL (counterexample or violated criterion), INCONCLUSIVE (insufficient evidence/power), PASS for the explicitly bounded contract, BLOCKED (harness/environment cannot run). No missing artifact may count as PASS.

## Negative controls and implementation order

Before any paid run, deliberately introduce isolated mutants: promote harness to user, retain stale verified evidence, discard L2, reset scope, remove budget enforcement, make health always PASS. The corresponding tests must fail; if a mutant survives, repair coverage before claiming that contract is tested. Do not edit the actual working runtime to insert mutants; use temporary copies.

1. Implement isolated runner, independent oracle, manifests and artifact collection; self-test the runner.
2. Implement Layer A and mutation controls. Record RED failures against the frozen current snapshot; do not weaken assertions to match it.
3. Repair runtime separately and rerun unchanged tests; independently review adapter paths.
4. Implement Layer B fixtures/hidden grader and verify reference fixes.
5. Obtain live provider and spend ceiling approval, then run pilot; freeze analysis before collection.
6. Decide confirmatory sample size, execute only under separate budget, publish failures and uncertainty alongside successes.

Deliverables proposed (not existing by implication): benchmarks/stress/ runner, task/fault manifest, independent oracle tests and per-run immutable report directories. This design document is the only artifact created by this task. No test execution, implementation, commit or deployment is implied.
