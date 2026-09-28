# JIT Context OS for Agent Zero (v0.4.1)

Agent Zero plugin for [JIT Context](https://github.com/wojciechwiesner/jit-context):
3-tier memory cascade (L0/L1/L2), JEV shadow judge, distill/eviction layer and a
live chat status bar, in one self-contained plugin (Apache-2.0).

> **Source of truth:** this plugin lives in
> [`wojciechwiesner/jit-context`](https://github.com/wojciechwiesner/jit-context)
> under `integrations/agent-zero/`. The
> [`jit-context-os`](https://github.com/wojciechwiesner/jit-context-os) repository
> is an automatic read-only mirror with the plugin at its root, as the Agent Zero
> Plugin Hub requires. Please star, open issues and send PRs in `jit-context`.

## Install

Pick one:

1. **One line, every agent host on the machine** (Claude Code, Hermes, OpenCode, Agent Zero):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/wojciechwiesner/jit-context/master/install.sh | bash -s -- --only agent-zero
   ```
   It finds a local Agent Zero checkout (or `A0_DIR`) or a running Agent Zero
   container, copies the plugin to `usr/plugins/jit_context`, keeps the plugin's
   `data/`, and runs `execute.py` (idempotent setup and self-test). Restart Agent Zero afterwards.
2. **Agent Zero UI, install from git:** `https://github.com/wojciechwiesner/jit-context-os`
3. **Agent Zero UI, install from ZIP:** download `jit_context-<version>.zip` from the
   [releases](https://github.com/wojciechwiesner/jit-context/releases) (tags `a0-v*`).

Do not give Agent Zero the `jit-context` root URL: the plugin is nested there,
and the loader expects `plugin.yaml` at the plugin root.

Keep runtime `data/`, `config.json` and secrets out of version control. Configure
the JEV API credential through the host configuration or environment.

## Verification in the monorepo

The Python core and this adapter both have a `tests` package, so run the suites separately:

```bash
python3 -m pytest src/tests -q
python3 -m pytest integrations/agent-zero/tests -q
```

`python3 integrations/agent-zero/execute.py` initializes a database at the
plugin's `data/` path; use a temporary copy for an isolated smoke test.
Production rollout notes: [`docs/plans/2026-09-24-agent-zero-integration.md`](https://github.com/wojciechwiesner/jit-context/blob/master/docs/plans/2026-09-24-agent-zero-integration.md).

In the Hermes CLI, `jit mode active`, `jit jev status` and `jit doctor` inspect
Hermes's JIT/JEV runtime, not this plugin.

## Citation

DOI [10.5281/zenodo.22649542](https://doi.org/10.5281/zenodo.22649542)
