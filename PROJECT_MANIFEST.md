# Project Infrastructure Manifest — jit-context

> Variable names, paths and ports only. Never raw secrets.
> Update on every infra/env change. Global registry: `~/ai/DEPLOYMENT_REGISTRY.md`.

## 1. Deployment

| Parameter | Value |
|---|---|
| Source of truth | `~/Projects/active/jit-context` (GitHub `wojciechwiesner/jit-context`, branch `master`) |
| Deploy mechanism | commit -> `git push origin master` -> `jit install` (all local hosts) |
| Hermes plugin | `~/.hermes/plugins/ona-context` -> `~/.hermes/plugin-releases/ona-context-<sha>-<ts>` (immutable releases) |
| Claude Code runtime | `~/.claude/hooks/jit-*` -> `src-<sha>-<ts>` release |
| OpenCode | `~/.config/opencode/plugins/jit-context.js` (V2 bundle for OpenCode 2.x) |
| Pi | `~/.pi/agent/extensions/jit-context.ts` |
| Agent Zero | `~/Projects/active/agent-zero` (local) + borg container via CI mirror (`agent-zero-mirror.yml`) |
| Other machines | `curl -fsSL https://raw.githubusercontent.com/wojciechwiesner/jit-context/master/install.sh \| bash` |
| CI | `.github/workflows/test.yml`, `agent-zero-mirror.yml`, `agent-zero-release.yml` |

## 2. Processes and Ports (Mac mini, loopback only)

| Service | Port | Manager |
|---|---|---|
| Hermes gateway (loads ona-context plugin) | 127.0.0.1:8642 | launchd `ai.hermes.gateway` |
| Observatory / health | 127.0.0.1:8765 | launchd `ai.hermes.ona-observatory` |
| Mission Control + Project Hub (`/hub`, `/api/hub/projects`) | 127.0.0.1:8767 | launchd `com.theones.jit-mission-control` |
| Hub refresher (`jit hub refresh --interval 60`) | none | launchd `io.theones.jit-hub-refresher` |
| Live stream | `JIT_LIVESTREAM_PORT` | launchd `ai.hermes.jit-livestream` |

After `jit install`, kickstart the daemons, otherwise they keep running from the old release:
`launchctl kickstart -k gui/501/com.theones.jit-mission-control` and `.../io.theones.jit-hub-refresher`.

## 3. State and Data

| Store | Path |
|---|---|
| L0 session overlay (SQLite WAL) | `~/.hermes/state/ona-context/session_overlay.db` |
| JIT context DB | `~/.hermes/state/jit_context.db` (`JIT_DB_PATH`) |
| Mode | `~/.hermes/state/ona-context/mode.json` (`ONA_CONTEXT_MODE`) |
| Hub catalog | `~/.hermes/state/jit-hub/projects.json` |
| Feedby keys | `~/.hermes/state/jit-hub/feedby/keys.json` (chmod 600) |
| Obsidian SSOT | `~/Documents/Wojciech/projects/hermes-jit-context-os-v0.1.md` |
| Backups | `~/backups/jit-context/<timestamp>` |

## 4. Environment Variables (names only)

| Variable | Purpose |
|---|---|
| `ONA_CONTEXT_MODE` | active / shadow / passive / off |
| `JIT_STATE_DIR`, `JIT_DB_PATH`, `HERMES_HOME`, `HERMES_STATE_DB` | State locations (tests must isolate `JIT_STATE_DIR`) |
| `JIT_LLM_BASE_URL`, `JIT_LLM_MODEL`, `JIT_SMALL_MODEL`, `JIT_LOCAL_MODEL` | L2 distillation / local worker models |
| `JEV_OPENROUTER_KEY` | JEV decision engine (OpenRouter) — secret, never commit |
| `BORG_GATEWAY_URL`, `BORG_GATEWAY_KEY` | Borg L2 broker (disabled by default) — secret |
| `BORG_TOOLS_LLM_URL`, `BORG_TOOLS_LLM_TOKEN` | Borg LLM proxy — secret |
| `JIT_HEALTH_HOST`, `JIT_HEALTH_PORT`, `JIT_OBSERVATORY_URL` | Observatory binding |
| `JIT_MC_PROJECTS_ROOT`, `JIT_MC_OBSIDIAN_PROJECTS`, `JIT_MC_TRUSTED_PROXIES` | Mission Control |
| `OBSIDIAN_VAULT`, `PROJECTS_VAULT`, `PROJECTS_WORKSPACE` | Vault / workspace roots |

Secrets live in the host environment (`~/.hermes/.env`) or launchd plists; the repo has no `.env`.

## 5. Verification

- Tests: `python3.11 -m pytest src/tests -q` (repo runner; `~/.jit-context/.venv` has no pytest).
- Health: `jit status`, `jit doctor`, `curl -s http://127.0.0.1:8765/health`.
- Hub: `curl -s http://127.0.0.1:8767/api/hub/projects` + headless DOM dump of `/hub` (client-rendered).

## 6. Gotchas

- Never edit deployed copies (`~/.hermes/plugins/ona-context`, `~/.claude/hooks/jit-*`, Agent Zero container, `jit-context-os` mirror). Fix in this repo only.
- `launchctl bootstrap` is blocked inside the Hermes gateway shell; run it from a separate terminal.
- Gateway needs 15–25 s to warm up after restart; `/health` returns 000 meanwhile.
- macOS `tar` adds AppleDouble `._*` files that break Agent Zero; use `COPYFILE_DISABLE=1`.
