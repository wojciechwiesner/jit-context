# 2026-11-07 — Feedby as project default, rollout to repos live in last 30 days

## Decisions
| Decision | Why | Alternative rejected |
|---|---|---|
| Feedby project + key created by `jit feedby` via psql over SSH (psql variables) | No service-role key on the mini; Feedby admin has no project-create API for non-UI callers | Raw string-built SQL (injection risk), clicking 16x in admin UI |
| Key format = Feedby `issue-widget-key.ts` (wk_live_ + base64url(32B), sha256 in DB) | Keys indistinguishable from admin-issued ones, revocable in admin UI | Own format |
| Snippet as marker block, commit only mount files | Idempotent re-run, key rotation in place, other dirty work never staged | Full-file rewrite, `git add -A` |
| `verify` probes /v1/widget/suggest with empty body | 401 invalid_widget_key vs 400 invalid_body proves the key without writing feedback | POST real feedback per project |
| Skip dos (CSP script-src 'self'), faktury/thesaiver (already wired), boocco/luna (key points at feedby-demo) | Each needs a product or prod-env decision, not a blind snippet | Force-inject |

## Evidence
- Feedby DB: 16 new projects, 17 active `jit-feedby` keys (db-projects-after.txt).
- `jit feedby verify --live`: 17/17 key accepted, all mounts carry the block, exit 0 (verify-final.txt).
- Pilot E2E: widget rendered on the hub, real report sent through the panel UI, POST /v1/feedback 201,
  row 58e6bad3-881b-4892-811f-077b31dbf106 in project jit-context (pilot-jit-db.txt, screenshot).
- Live hub http://127.0.0.1:8767/hub serves the widget after `jit install` (live page True).
- Builds after injection: firestudio tsc exit 0, theones astro build exit 0 (dist has the script), movus vite build exit 0.
- jit-context: 446 pytest PASS, pushed e7bab8a.

## Lessons / gotchas
- Cloudflare returns 403 error 1010 for the default Python-urllib user agent: always send a named UA.
- The pre-push regression guard checks every `fix(` commit separately: put the test in the same commit.
- Feedby ingest lives on feedby-admin.borg.tools (CORS *); feedby.borg.tools only serves the widget assets.
- Panel is a cross-origin iframe: DOM queries from the host page cannot reach it; use real pointer + Input.insertText.
- A commit in the repo is not a live widget: every app still has to be deployed with its own procedure.
