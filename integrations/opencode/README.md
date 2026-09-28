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
| Unit tests (`bun test`) | 15 pass, including timeout fail-open and cross-scope rejection |

## A/B test: same task, with and without the plugin

`bench/ab.py` runs one OpenCode task in the same repo, with the same model (gpt-5.5, OpenCode 1.17.8), with the plugin and with `opencode run --pure` (external plugins disabled). Runs alternate between the two variants, 4 per variant. All metrics come from `--format json` runtime events.

Task: *"Where is the payment webhook handled, what is the current blocker, and which env var must hold the webhook secret?"* The fixture repo hides the handler behind a non-obvious route (`/integrations/incoming`) and records the blocker in `.planning/STATE.md`. The env var decision exists only as an observation recorded by an earlier session, not anywhere in the code.

| Median of 4 runs | With plugin | Without (`--pure`) |
|---|---|---|
| Wall time | **8.6 s** | 42.4 s |
| Tool calls | **0** | 14.5 |
| LLM steps | **1** | 6.5 |
| Input tokens (incl. cache reads) | **29,600** | 196,779 |
| Correct file | 4/4 | 4/4 |
| Correct env var | **4/4** | 0/4 (guesses `STRIPE_WEBHOOK_SECRET` or `UNKNOWN`) |

How to read it: this is a single task designed to need memory, not a general benchmark. The code-only question (which file) is answered correctly without the plugin too, just about 5x slower and with about 6.6x more input tokens. The decision recorded in an earlier session cannot be recovered from the code at all, and without the plugin the agent invents a plausible wrong value. That second case is the main point of the plugin.

Reproduce: `bun run build && bash bench/setup-fixture.sh && python3 bench/ab.py 4`. The plugin talks to a dead Observatory port, so this measures the pure local L0 path. Your model and provider will change the absolute numbers.

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

- The Hermes Observatory is queried with `?project=` and returns the newest session of that project. The scope guard remains as defence against older Observatory builds that ignore the parameter.
- `experimental.*` hooks may change between OpenCode releases.

## License

MIT
