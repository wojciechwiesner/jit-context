# opencode-plugin-jit-context

Your coding agent forgets the project every session, then spends its first ten turns grepping for what it already knew. This plugin gives OpenCode a small, scoped, persistent project memory. Nothing is added to the prompt when there is nothing to say.

Built for coding agents with real tool access (shell, file edits, tests), not general chatbots. Part of [JIT Context OS](https://github.com/wojciechwiesner/jit-context) (DOI: [10.5281/zenodo.22649542](https://doi.org/10.5281/zenodo.22649542)).

## What it does

| Mechanism | OpenCode hook | Effect |
|---|---|---|
| Capsule injection | `experimental.chat.system.transform` | Adds a compact `<JIT_CONTEXT>` block (scoped observations + `.planning/STATE.md`) to the system prompt each turn. Adds nothing when the project has no data. |
| `get_jit_context` | `tool` | On-demand capsule, for when the agent wants to re-check. |
| `record_jit_observation` | `tool` | Persists a verified fact. Idempotent per fact. |
| `get_project_state` | `tool` | Reads `.planning/STATE.md` without a filesystem search. |
| Edit trail | `tool.execute.after` | Records every file touched by `apply_patch` / `edit` / `write`. |

Storage is a local SQLite WAL (`session_overlay` table). The schema matches the jit-context MCP server, so Hermes, Claude Code (via MCP) and OpenCode share one memory per project.

### Guarantees

- **Fail-open.** Observatory down, timed out (300 ms) or DB locked: the turn continues without a capsule. The plugin never blocks or crashes the prompt loop.
- **Scope isolation.** Scope is the worktree folder name. A live capsule from another project is rejected rather than injected, so project A's context never leaks into project B.
- **Bounded size.** The capsule is capped at `maxCapsuleChars` (default 6000 chars, ~1.5k tokens).

## Verified behaviour (OpenCode 1.17.8, real runs)

| Check | Result |
|---|---|
| Agent answers a question whose answer exists only in `.planning/STATE.md`, with no tool calls | Plugin on: correct answer. `JIT_INJECT=0`: `UNKNOWN` |
| `record_jit_observation` called by the agent | Row written to L0 with `source=opencode:build` |
| Agent edits via `apply_patch` | `File modified via apply_patch: notes.txt` auto-recorded |
| Unit tests (`bun test`) | 14 pass, including timeout fail-open and cross-scope rejection |

## Install

```bash
opencode plugin opencode-plugin-jit-context        # after npm publish
```

Local, before publishing:

```jsonc
// opencode.json
{
  "plugin": [["file:///ABS/PATH/opencode-plugin-jit-context/dist/index.js", {}]]
}
```

## Configuration

Plugin options in `opencode.json` take precedence over env vars, which take precedence over defaults.

| Option | Env | Default |
|---|---|---|
| `observatoryUrl` | `JIT_OBSERVATORY_URL` | `http://127.0.0.1:8765` |
| `dbPath` | `JIT_L0_DB_PATH` | `~/.hermes/state/ona-context/session_overlay.db` |
| `injectSystemCapsule` | `JIT_INJECT` (`0` = off) | `true` |
| `observatoryTimeoutMs` | | `300` |
| `autoRecordTools` | | `edit, write, patch, multiedit, apply_patch` |
| `maxCapsuleChars` / `maxStateChars` | | `6000` / `2500` |

The Observatory is optional. Without it the plugin runs fully local on SQLite.

## Development

```bash
bun install
bun run check   # typecheck + tests + build (dist/index.js + .d.ts)
```

Layout: `src/index.ts` (hooks and tools only, one export), `capsule.ts`, `l0.ts`, `observatory.ts`, `edits.ts`, `config.ts`.

The entry module must export only the plugin. OpenCode's loader treats every export as a plugin and throws on anything else.

## Known limits (v0.1)

- The Hermes Observatory ignores `?scope=` and serves the active Hermes session's capsule. In practice OpenCode usually runs on the L0 fallback. The scope guard prevents poisoning; a scoped Observatory endpoint is planned.
- `experimental.*` hooks may change between OpenCode releases.

## License

MIT
