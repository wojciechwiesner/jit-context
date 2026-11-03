# Project Hub: always-fresh cockpits, measured JIT impact, project chat and actions

Status: plan, executed by the agentic loop in `../jit-context-wt-hub` (branch `feat/project-hub`).
Owner decision 2026-11-03: works globally for every project where `jit init` ran.

## Why

- Cockpits (`.planning/state.html`) refresh only on a commit in the same checkout. Work done in worktrees,
  edits of STATE.md without a commit and tracked cockpits (jit-context itself) leave the page stale.
- Token "savings" shown today are not measured (no paired baseline). The owner wants real numbers per project.
- Cockpit chat works only for projects registered by hand in `~/.hermes/state/project-cockpit/runtime.json`
  (one project today), so in most projects it says the bridge is not configured.
- No single place lists every project with `jit init`; Mission Control (`/mc`, port 8767) lists 144 folders
  under `~/Projects/active`, worktrees included, with no grouping.

## Decisions

| Decision | Why | Rejected |
|---|---|---|
| Vendor the cockpit generator into the repo (`cockpit/`) | versioned, tested by the gate, installed by `jit install`; launchd cannot run code under `~/Documents` (TCC) | keep editing `sota-starter` in place (no git, no rollback) |
| Registry `~/.hermes/state/jit-hub/projects.json`, filled by `jit init` + `jit hub scan` | "every project with jit init" needs an explicit list; worktrees map to their main repo | scan all of `~/Projects/active` (144 entries, mostly worktrees) |
| Refresher daemon (launchd, every 60 s, signature based) | rebuilds only when HEADs or planning files change, covers worktrees and uncommitted STATE.md edits | rebuild on a timer regardless of change; commit hooks only |
| Tracked cockpits are never rewritten in the repo; the hub keeps its own copy | no dirty trees, no surprise diffs; `jit cockpit untrack` is explicit | silently `git rm --cached` |
| Hub = extension of Mission Control server (8767) | one local service, existing access guard, no new port | a new server and port |
| Stats split into three honest layers: usage (measured), observational JIT on/off (labelled, n shown), controlled A/B (`jit bench ab`, manual, costs tokens) | the owner requires zero projections; savings are claimed only from A/B | one "saved tokens" number |
| Suggestions = deterministic rules with evidence; LLM text only on demand and labelled advisory | facts first, no hallucinated advice | LLM-only suggestions |
| Chat and actions run from the hub (same origin, CSRF token); file:// cockpits link to the hub | no secrets embedded in HTML files, works for every registered project | token in each state.html |
| Actions (audit 360, security, market, monetization) = headless `claude -p` with read-only tools, max 2 concurrent, report saved to hub state + Obsidian | real agentic research with web access, no code edits, cost is visible | running them inside the chat request |

## Phases and tasks (loop queue `.planning/orchestration/QUEUE.md`)

A. Freshness: H1 vendor generator, H2 registry, H3 refresher, H4 worktree activity, H5 freshness UX,
   H6 launchd installer, H7 `jit cockpit untrack`.
B. Measurement: H8 usage collectors, H9 observational comparison, H10 `jit bench ab`, H11 suggestions,
   H12 stats tab.
C. Hub, chat, actions: H13 hub API, H14 hub UI, H15 chat backend, H16 chat UI, H17 action runs backend,
   H18 actions UI.
D. H19 docs + end-to-end script.

## Not done by the loop (operator cutover after merge)

1. Full gate + runtime UAT on the branch, merge to master, push, `jit install`.
2. `sota-starter/build_state_template.js` becomes a thin shim that calls the installed repo generator.
3. Load the refresher launchd agent, run `jit hub scan`, check every registered cockpit rebuilds.
4. `jit cockpit untrack` for jit-context (owner confirmation: it removes a tracked file from the index).
5. Browser verification of hub, stats tab, chat (real model reply) and one real action run on a small project.
6. First real `jit bench ab` run only on owner request (costs tokens).

## Definition of done (whole plan)

- Every registered project cockpit is at most 2 minutes behind its newest change, worktrees included,
  proven by editing STATE.md in a worktree and watching the hub version change.
- Stats tab shows measured usage per project; savings appear only from an A/B run, with date and n.
- Chat answers in at least three different projects in the browser with a real model response.
- Each of the four actions produced a report from a real run on one project.
- Hub lists every project from the registry, worktrees grouped under their repo.
