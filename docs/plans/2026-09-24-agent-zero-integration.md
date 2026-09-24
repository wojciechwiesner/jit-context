# Agent Zero integration in jit-context

## Scope and acceptance

- Preserve `jit-context` core, its existing Hermes integration and the published `jit-context-os` repository. No deletion, release, deploy, or version bump.
- Vendor the tracked, distributable Agent Zero v0.4.0 plugin files from `~/Projects/active/jit-context-os` into `integrations/agent-zero/`, retaining its own Apache-2.0 LICENSE and plugin version. No runtime database, credentials, untracked files, or planning cockpit.
- The plugin must remain self-contained at its own directory root: `plugin.yaml`, `execute.py`, `helpers/`, `jev_bridge/`, `extensions/` and UI/API assets. Do not pretend the root Python package and Agent Zero adapter are interchangeable: they are separately versioned runtimes for different hosts.
- Document an install path from this monorepo that copies only `integrations/agent-zero/` into `/a0/usr/plugins/jit_context/`, not an unverified Plugin Hub subdirectory URL.
- Run the existing core suite and the copied Agent Zero suite, including smoke verification of the plugin manifest and loader from its nested path. Add a test that checks the integration boundary and source fingerprint against the original release during this migration.

## Execution

1. Record the clean-room inventory of tracked plugin files; omit unrelated `.planning`, old README, changelog and citation. Confirm no secrets or generated data are included.
2. Add the files under `integrations/agent-zero/` without touching existing modified files. Preserve copyright/license. Document installation, separate versions, and JEV enablement/verification.
3. Verify tests in separate pytest invocations (both suites contain a `tests` package), smoke check `execute.py` with isolated data path, check file hashes against the source, and review git diff for unintended files.

## Runtime distinction

`jit mode active` and `jit jev status` describe the currently configured Hermes runtime; they do not imply that Agent Zero's plugin is installed or running in this CLI process. A passing JEV probe is not a measured reduction in this conversation's tokens. Activation for Agent Zero requires installation in its host and runtime verification there; this migration deliberately does not deploy.

## Verified locally (2026-09-24)

- Existing Hermes JIT: `jit status` active; `jit jev status` upstream probe PASS; `jit doctor` JEV PASS and 11/11 invariants PASS (capsule compiler latency WARN).
- 49 copied tracked files byte-identical to the v0.4.0 release tree; the adapter remains a separate Apache-2.0-licensed package.
- Fresh isolated environment: editable install with declared `httpx` and `pydantic`; core 60 passed, Agent Zero 56 passed. Plugin self-test in a temporary installed copy: SQLite WAL and capsule compiler PASS.
- At this point the migration was local only; GitHub Actions and Agent Zero runtime were not yet verified. Publication and deployment were performed and verified separately below.

## Published and deployed (2026-09-24)

- Commit `75981e1659ece8f6e7400e7334af6c221b302d40` pushed to `wojciechwiesner/jit-context` `master`; GitHub read-back confirmed the plugin manifest. GitHub Actions run `36023944755` passed.
- Agent Zero host `borgtools`, container `agent-zero` (`agent0ai/agent-zero:v2.5`): plugin `/a0/usr/plugins/jit_context` reports v0.4.0 and the exact deployed SHA; pre-existing `config.json` and SQLite database were preserved. Local HTTP returned 200 and the installed plugin's self-test passed (SQLite WAL and capsule compiler). Public HTTPS returned 401 without credentials, as expected for its access gate; authenticated plugin UI/API was not tested.
- Full pre-deploy plugin backup plus nginx/compose/env copies retained at `/home/vizi/backups/agent-zero-jit-75981e1659ece8f6e7400e7334af6c221b302d40-safe/`; previous live tree retained under `/home/vizi/agent-zero-persistent/usr/plugins/.jit_context-previous-75981e1659ece8f6e7400e7334af6c221b302d40`. The deployment registry was backed up and updated.
- Hermes upstream PR #110874 is independent of this Agent Zero adapter: current-main conflict resolution was pushed as merge commit `f954af61521be66b0db412f87f1b3be94ef4d9e4`; PR is mergeable but blocked with no checks reported. Maintainers were asked to run CI/re-review. Focused suite: 215 passed; broader compaction sweep: 255 passed, 3 failures reproduced on unmodified upstream `main`.
