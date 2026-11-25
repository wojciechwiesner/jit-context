# 2026-11-25 — hook latency threshold deploy + sota-starter shim

## Decisions

| Decision | Why | Alternative rejected |
|---|---|---|
| Hook latency audit alert at 10 s (was 600 ms) | 600 ms flagged normal L2-capable turns (506 alerts); it is an advisory audit threshold, not a timeout | Keeping 600 ms and profiling first (deferred, still open) |
| sota-starter `build_state_template.js` = thin shim to repo generator | Vendored `cockpit/` drifted (no `worktrees.js`) and crashed with MODULE_NOT_FOUND; plan step 2 of Project Hub cutover | Re-copying cockpit/ into the template (would drift again) |
| No `.planning/autocheck.json` written | Other projects' files come from real flow probes; a hand-written file would be paper certification | Static placeholder flows |
| `jit cockpit untrack` skipped | `state.html` already gitignored and untracked | Running it anyway |

## Evidence

- `python3.11 -m pytest src/tests -q`: 453 passed, 7 skipped, exit 0.
- Commits `b7e8ef8` (fix) and `857767c` (manifest/state) pushed to origin/master; CI Tests success on `b7e8ef8`.
- `jit install` exit 0; Hermes plugin -> `ona-context-b7e8ef8-20261125-190806`, release contains `HOOK_LATENCY_ALERT_SECONDS = 10`.
- Mission Control kickstarted, cwd = new release; `/hub` 200, `/api/hub/projects` 72 projects; hub-refresher kickstarted.
- Shim rebuild exit 0 for `jit-context` and `hermes-companion`; headless DOM of state.html contains `b7e8ef8` and new links.

## Lessons & Gotchas

- `launchctl bootstrap` is blocked inside the Hermes gateway shell; `kickstart -k` works for already loaded agents.
- `jit install` does not restart the Hermes gateway; the gateway process keeps its imported modules until restarted.
- Vendored copies of the cockpit drift silently; keep one generator and point everything else at it.
