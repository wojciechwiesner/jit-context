# Cognition rollout plan (2026-09-26)

Source: repo state after commit 2a5c6ef, review by claude-fable-5-1 (`~/.hermes/cache/scratch/fable-deploy-review.md`),
live checks on the gateway log and `~/.hermes/state/ona-context/session_overlay.db`.

## Facts established
- Commit 1 done: 2a5c6ef (goal anchor, Sumienie, Rozwaga, vision_inspect, tool_routing). Local only, not pushed.
- Tests: 88 passed, 1 failed (`test_wheel_entrypoints_and_assets`). The failure is environmental: the wheel test
  creates a venv whose `ensurepip` aborts (SIGABRT) with the uv-managed Python, and with Homebrew 3.13 the
  isolated doctor fails on `certifi`. It fails identically on the previous commit (stash check), so not a regression.
- Plugin: `~/.hermes/plugins/ona-context` is a copy. 15 files differ from `src/`, 3 modules missing
  (`judge.py`, `loop_guard.py`, `goal_anchor.py`). Live Hermes runs old code.
- FOREIGN KEY: 48 errors in the gateway log (38 post_tool_call, 5 pre_llm, 5 post_llm), all on 2026-08-31 .. 2026-09-01.
  None since. Cause: 6,012 of 13,005 `overlay` rows point to `events` rows that no longer exist (oldest surviving event
  2026-09-11; no `DELETE FROM events` exists in current code, so the events were removed outside the code path).
  Current `record_tool_evidence` replays all operation kinds cleanly on a copy of the prod DB.

## Steps (each has a go/no-go)
1. Commit remaining work. Leave `benchmarks/results/wynajmujemy_slice/*` and `.planning/state.html` as a separate
   commit or discard, decided by Wojciech. GO: `git status` clean for `src/`.
2. STATE.md / README honest numbers: "47/53 GAIA L1 validation, single run, 44 exact (official scorer ~46),
   harness tuned on the same 53 tasks (dev set)". GO: no number without its N, scorer and run count.
3. DB migration (before plugin deploy): backup `session_overlay.db`, delete orphan overlay rows, add
   `plugin_version` to events, add a `foreign_key_check` to `jit doctor`. GO: orphans = 0, doctor FK check PASS,
   old plugin still boots on the migrated DB. Requires Wojciech's confirmation (deletes 6,012 rows).
4. Plugin deploy as a versioned copy: `~/.hermes/plugins/ona-context-<sha>/` + pointer symlink `ona-context`.
   Keep the previous version on disk. `jit doctor` compares plugin sha with repo HEAD. GO: sha match, new modules import.
5. Shadow mode 24h (`mode.json` -> shadow), then active. GO: zero `[ona-context:error]`, latency not >30% worse.
   Rollback: repoint symlink to the previous sha, restart gateway.
6. Benchmark credibility before any public number: GAIA source blocklist (HF dataset, mirrors, pages quoting
   GAIA) + URL audit log, official `question_scorer`, full 165 tasks x 3 runs, mean +- std, ablations
   STANDARD / +Sumienie / +Rozwaga with cost, turns, tokens.
7. Public numbers (README, Zenodo) only after step 6.

## Cognition improvements (impact / effort)
1. Budget-forced alone -> VERIFIED-WEAK, not UNVERIFIED (removes ~12 false flags and their second attempts).
2. Relation grounding without an extra LLM call: answer + key entity of the question must co-occur in one
   sentence / table row of tool output (regex window); optional local NLI cross-encoder.
3. Rozwaga 0/2 verified: third attempt with a forced different strategy, or abstain; no judge between two unverified.
4. Typed answer contract (number / string / list + unit) enforced before the final turn.
5. Remove the cognitive pre-pipeline (LFM2 sensory + planner): measured 36/53 = STANDARD, no gain.

## Small local models (<=9B)
- Realistic roles: distiller/classifier, Sumienie as constrained JSON classification. Worker for GAIA web tasks and
  the pairwise judge stay on a frontier model until measured otherwise.
- Harness requirements: thinking off, Ollama `format` JSON schema for structured outputs, tolerant tool-call parser,
  <=5 tools, tool output capped ~1.5k tokens, 16k context ceiling, one error-feedback retry, temperature 0 for gates.
- Measurement in progress: qwen3.8:jit worker on 10 GAIA L1 tasks
  (`~/.hermes/cache/scratch/cogab3/qwen_smoke/res.json`).
