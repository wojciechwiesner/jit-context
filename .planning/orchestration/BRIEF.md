# Worker brief: jit-context Project Hub

You are an autonomous coding worker in the jit-context repository (git worktree `jit-context-wt-hub`,
branch `feat/project-hub`). Nobody answers questions: decide, document the decision in the work log, continue.

**Task: {{TASK_ID}} — {{TASK_TEXT}}**

## Read first (in this order, keep it short)
1. `docs/plans/2026-11-03-project-hub.md` (the plan, decisions table).
2. `.planning/orchestration/QUEUE.md` (what earlier tasks built; reuse their modules).
3. `.planning/orchestration/WORKLOG.md` (last 60 lines).
4. Only the source files your task touches. Find code with grep; do not read the whole repo.

## Hard rules
- Solve only this task. No drive-by refactors or renames.
- Python 3.11+ (Homebrew). Code that runs from git hooks must also import on macOS system python 3.9
  (`from __future__ import annotations`, no `match`, no `X | Y` at runtime).
- New Python modules go under `src/` (package `hub/` for hub logic). Each file < 300 lines, functions < 50 lines.
  Type hints on public functions. English identifiers, comments and commit messages; Polish only in UI text and
  generated reports.
- UI: no emoji anywhere (labels, reports, model output shown in UI); SVG icons only. Render model or file text
  with textContent or an escaping helper, never raw innerHTML.
- Never touch: `~/Documents/Wojciech/templates/sota-starter/` (read-only source for H1), `~/.hermes/plugins`,
  `~/.claude`, `~/Library/LaunchAgents` (tests use a tmp HOME), any other repository, any live database except
  reading. Tests must not write to the real `~/.hermes` or `~/Documents`: monkeypatch HOME / env paths.
- No network or model calls in tests: use fake servers and fake commands on PATH.
- Never fabricate data or fallback answers: missing data is shown as missing, upstream errors as errors.
- No secrets in git. Do not read `.env` files.
- Exactly ONE commit for the task (`type(scope): summary` + bullet list), message ends with:
  `Developed by Wojciech Wiesner wojciech@theones.io -= join.theones.io =- be The One Who Is Many -`
- Add a line under `## [Unreleased]` in CHANGELOG.md (Added/Changed/Fixed) in the same commit.
- Never push, deploy, `git reset --hard`, `git clean`, rebase, or switch branches. Do not edit QUEUE.md.
- Leave the working tree clean after your commit (the gate checks it).

## Definition of done (the loop checks it, not you)
`scripts/hub_gate.sh` must pass: full pytest suite (python3.11), `node --test cockpit/` when that dir exists,
Ruff syntax checks, file size limit for files you added, no emoji in UI files, clean tree, a new commit.
Run it yourself before committing.

## Work log
Append to `.planning/orchestration/WORKLOG.md` (append only, include it in your commit):
```
## <ISO8601> · {{TASK_ID}} · DONE
- files: <list>
- tests: <command> -> <result line>
- decisions: <short, why>
- gaps: <what is still not covered, or "none">
```

## Last line of your output
`TASK {{TASK_ID}} DONE <short-sha>` or `TASK {{TASK_ID}} BLOCKED <reason>`
