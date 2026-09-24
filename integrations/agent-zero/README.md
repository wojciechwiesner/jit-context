# Agent Zero adapter (v0.4.0)

This directory is the self-contained Agent Zero plugin, imported from the public
[`jit-context-os` v0.4.0 release](https://github.com/wojciechwiesner/jit-context-os/releases/tag/v0.4.0).
It contains its own `plugin.yaml`, hook extensions, JEV bridge, API/UI assets and
Apache-2.0 `LICENSE`. The root `jit-context` Python core is a separate runtime
(currently v0.2.11, MIT); the plugin does not become the root pip package or
inherit its version merely by living in this monorepo.

## Installation in Agent Zero

The Agent Zero plugin loader expects `plugin.yaml` at the installed plugin root.
Do not hand the GitHub Plugin Hub the monorepo root URL: the plugin is nested.
On the Agent Zero host, clone the repository and install only this directory:

```bash
git clone --depth 1 https://github.com/wojciechwiesner/jit-context.git /tmp/jit-context
# Back up any existing /a0/usr/plugins/jit_context and its data/ before replacing it.
mkdir -p /a0/usr/plugins/jit_context
cp -R /tmp/jit-context/integrations/agent-zero/. /a0/usr/plugins/jit_context/
python3 /a0/usr/plugins/jit_context/execute.py
```

The repository alone does not activate the plugin. Production installation
and its verification are recorded in
[`docs/plans/2026-09-24-agent-zero-integration.md`](../../docs/plans/2026-09-24-agent-zero-integration.md).
To avoid mixing stale files on an already-populated install, back up and replace
the plugin directory during a scheduled deployment. Keep runtime `data/`,
`config.json`, and secrets outside version control. Configure the JEV API
credential through the host configuration/environment, not this repository.

## Verification in this repository

Run the suites separately because both the Python core and this adapter have a
Python `tests` package:

```bash
python3 -m pytest src/tests -q
python3 -m pytest integrations/agent-zero/tests -q
```

`python3 integrations/agent-zero/execute.py` initializes a database at the
plugin's `data/` path; use a temporary copy for an isolated smoke test.

In the Hermes CLI, `jit mode active`, `jit jev status`, and `jit doctor` inspect
Hermes's installed JIT/JEV runtime, not Agent Zero's plugin. A successful JEV
probe proves API reachability and ordering in that invocation, not a measured
token reduction for every turn.
