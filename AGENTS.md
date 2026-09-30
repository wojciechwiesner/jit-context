# AGENTS.md

Rules for any AI agent (Hermes, Claude Code, OpenCode, Agent Zero, Codex) working on JIT Context.

## Single source of truth: this repository

Never edit deployed copies. They are read-only snapshots or mirrors and the next deploy overwrites them:

- `~/.hermes/plugins/ona-context` and `~/.hermes/plugin-releases/*`
- `~/.claude/hooks/jit-*` and `~/.claude/jit-context-runtime/*`
- the Agent Zero container (`usr/plugins/jit_context`)
- the `jit-context-os` mirror repository

Fix in this repo -> run tests -> commit -> `jit install` (redeploys all local hosts) -> push (CI mirrors to jit-context-os).

```bash
python3 -m pytest src/tests -q
git commit ...
jit install
git push
```

Every snapshot has a `DEPLOYED_FROM.txt` (commit, timestamp, source path). If a deployed copy misbehaves, reproduce and fix it here, never in place.

## Live mode (development only)

Claude Code hooks import the snapshot at `~/.claude/jit-context-runtime/current`, not the checkout. To exercise uncommitted `src/` changes, set `JIT_DEV_LIVE=1` (or `JIT_SRC=<path>`) in the Claude Code environment. Unset it and run `jit install` when done.

## Code rules

- Max 300 lines per file, 50 per function; constants in UPPER_SNAKE_CASE.
- Surgical changes only; update `CHANGELOG.md` (`[Unreleased]`) with every change.
