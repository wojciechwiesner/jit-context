# 2026-11-25 — Autocheck implementation + sota-starter Autocheck

## Decisions

| Decision | Why | Alternative rejected |
|---|---|---|
| Reuse the `autocheck-flow` engine (`~/Projects/active/autocheck`) | Engine, Feedby escalation, hub snapshot and 30 min cron already existed and were live | A second autocheck implementation inside jit-context |
| JIT observer reads `audits/*.jsonl`, not `session_overlay.db` | Global overlay DB stopped receiving turn telemetry on 2026-10-16; audits are written every turn (139 in 24 h) | Reading stale SQLite tables |
| SLAs mirror existing jit-context thresholds (10 s hook, 1200 s turn) | One definition of "slow" across turn audit and flow view | New, invented thresholds |
| Per-project probes = `.planning/autocheck/*.hurl`, discovered via the JIT hub registry | Every `jit init` project is in the registry; one cron covers all projects; hurl format already supported | Per-project cron jobs; hand-written `autocheck.json` |
| `jit init` creates only the folder + README, never `autocheck.json` or a guessed URL | No paper certification: status exists only after a real probe run; cockpit says "NIE ZMIERZONO" | Placeholder probe pointing at an unknown port |
| Flow starts at synthetic `probe_started` node | A one-step probe needs an edge, otherwise a dead endpoint looks "ok" | Single-node contracts |
| `autocheck.json` untracked in git | Regenerated every 30 min; tracking it would dirty the repo constantly | Committing the snapshot |

## Evidence

- autocheck: `python3 -m pytest -q tests` 43 passed; Python 3.15 unittest OK; commit `2482e83` (no remote).
- jit-context: `python3.11 -m pytest src/tests -q` 456 passed, 7 skipped, exit 0; CI success on `562ec34`.
- Live: `bash scripts/cron_sync.sh` exit 0; `jit_turn_pipeline` 142 turns, 2 hook SLA breaches, 23 turns > 1200 s;
  `mission_control_hub` ok (p95 4.9 s on `/api/hub/projects`), `observatory_health` ok.
- Negative path: `probe --base-url http://127.0.0.1:9` -> both flows `broken`, `probe_failed` finding, exit 1.
- Headless Chrome DOM: cockpit card shows 3 flows + measurement time; empty project shows "NIE ZMIERZONO";
  `/hub` shows `FLOW: DEGRADED/OK` for jit-context, autocheck, hermes-companion, uni-pro-works.

## Lessons & Gotchas

- The cockpit overview is rendered at build time; time-based UI (STALE) reflects the build moment, and every
  cron sync does not rebuild `state.html` by itself.
- `main()` in `init.py` is also driven by tests with a fake `run_init`; new result keys must be optional there.
- `/api/hub/projects` takes 4–7 s (scans 72 repos); keep its probe SLA at 15 s or the flow flaps.
- `--unipro-ssh local` does not work on the Mac (container lives on borg); use the default `borg-ts`.
