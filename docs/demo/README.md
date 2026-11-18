# Demo clips

Two terminal clips for the top-level README. Both are rebuilt from the scripts in this folder.

| File | What it shows | Source |
| :--- | :--- | :--- |
| `jit-demo.gif` | The same multi-file repair task run in Hermes with JIT off and with JIT on, plus the measured result | `render.py` + `qwen27b.json` |
| `jit-hub.gif` | `jit hub scan`, `list`, `refresh --once`, then `GET /hub` | `hub_demo.py` |

## How the numbers are produced

`measure.py` makes two fresh workspaces from `fixture.py`, a receipt importer split across 5 modules with
4 tests (1 of 4 passes at the start). It runs `jit init .` in each one and then runs Hermes' own agent loop
(`host.py`, `run_agent.AIAgent` with the `file` and `terminal` toolsets, max 7 iterations). Both runs get the
same prompt. The only difference is `ONA_CONTEXT_MODE=active` or `disabled`.

- Each run uses its own `HOME` and `HERMES_HOME`. Your Hermes profile, memory and sessions are not read or changed.
- Model calls go through `gateway.py`, a local recording proxy. It forwards each request to the provider without
  changing the messages. It keeps only metrics: HTTP status, the provider's reported `usage`, request size, the
  number of tool schemas and the `ONA_CONTEXT scope` of the first request. It does not save prompts or keys.
- Checks for a valid A/B: the JIT ON run must carry the project capsule (`scope="receipt-import"`) in its first
  request, the JIT OFF run must carry none, and every call must return HTTP 200 with reported usage. `render.py`
  will not render if any check fails.
- Tests are scored by restoring the original test file and running `unittest`, so an agent cannot raise its own
  score by editing the tests.
- L2, the JEV remote ranker and the Borg classifier are off in both runs (`JIT_L2_ENABLED=0`,
  `JIT_JEV_ENABLED=0`, an unreachable `JIT_LLM_BASE_URL`). The clip measures the local L0/L1 capsule only.

The GIF replays the measured numbers in a terminal. It is not a screen capture of the agent working, and the
header says so.

## Reproduce

```bash
cd docs/demo
# Cloud model (costs tokens; about $0.05 per pair for qwen/qwen3.8-27b on OpenRouter):
python3 -B measure.py --model qwen/qwen3.8-27b --backend openrouter --order on-first --output qwen27b.json
python3 -B render.py --results qwen27b.json   # writes jit-demo.cast + jit-demo.gif
python3 -B hub_demo.py                         # writes jit-hub.cast + jit-hub.gif (no model calls)
# Local models through Ollama (free; also runs the no-tools arm, where the model must return a unified diff):
python3 -B measure.py --model lfm2.5:2.6b-16k --output lfm-local.json
```

Requirements: Hermes Agent checkout at `~/.hermes/hermes-agent` (override with `HERMES_AGENT_SRC` /
`HERMES_AGENT_PYTHON`), `asciinema` 3.x and `agg`. Use `--offline` to check the setup without calling a model.
Offline runs are never results.

## Caveats

N=1 per arm. A single run shows that the setup works and how big the effect is in one case. It is not an
estimate for other runs. Short single-file tasks get a small overhead from the capsule.
