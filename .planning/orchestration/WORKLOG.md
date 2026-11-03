# Project Hub work log (append only)

## 2026-11-03T16:45:00+01:00 · setup · DONE
- files: docs/plans/2026-11-03-project-hub.md, .planning/orchestration/{QUEUE,BRIEF,WORKLOG}.md, scripts/hub_gate.sh
- tests: scripts/hub_gate.sh -> baseline (see loop.log)
- decisions: branch feat/project-hub from master 93e1814 + test fix 1a9b3f5; loop never pushes or installs
- gaps: none

## 2026-11-03T23:55:00+01:00 · H1 · DONE
- files: cockpit/build_state_template.js, cockpit/package.json, cockpit/run_tests.js, cockpit/render_plan.js,
  cockpit/cockpit.test.js, cockpit/client.js (removed), cockpit/render_tasks.js (removed), src/config.py,
  src/l1/cockpit_sync.py, src/init.py, src/health/mission_data.py, src/tests/test_cockpit_builder.py,
  .planning/state.html, CHANGELOG.md
- tests: scripts/hub_gate.sh -> pytest 272 passed, 7 skipped; node --test cockpit/ 8 pass 0 fail
- decisions: sources were already copied by the operator (8603329); builder required ./cockpit/* (sota-starter
  layout), now ./collect and ./render. Node 22 runs `node --test cockpit/` as a module, so package.json "main"
  points to run_tests.js, which loads every *.test.js. config.cockpit_builder(): $JIT_COCKPIT_BUILDER, else
  <repo>/cockpit; a runtime snapshot (only src/ is copied) reads DEPLOYED_FROM.txt to find the repo, so the
  next `jit install` keeps post-commit rebuilds working. Mission Control finds export.js beside the builder or
  in cockpit/ (old layout via the override). client.js and render_tasks.js were not required anywhere (render.js
  uses client_workspace.js and render_plan.js): removed instead of splitting dead code; the done-task tick is an
  SVG now; the emoji test fixture uses \u{...} escapes. .planning/state.html (tracked) was regenerated outside
  this task at 23:28; committed as is because the gate needs a clean tree and reverting would discard it.
- gaps: `jit install` still snapshots only src/ (cockpit/ resolved from the source checkout, not copied);
  cockpit/server.py, install_runtime.py, test_server.py were vendored but are not run by any gate.
