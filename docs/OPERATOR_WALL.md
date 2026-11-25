# Operator Wall

One always-on second-screen page for the operator: what needs me, how active projects stand, whether machines
and agents work. Served by the Mission Control server (default `:8767`).

| Route | What |
|---|---|
| `GET /wall` | 1920x1080 page, no scroll, refreshes every 60 s |
| `GET /api/mc/wall` | JSON contract below (read-only; DOS will consume it) |
| `POST /api/mc/charters/approve` | approve charter drafts (Origin + CSRF guarded like the hub POSTs) |

## `GET /api/mc/wall`

```json
{"generated_at": "ISO-8601 UTC",
 "verdict": "8 rzeczy czeka na Ciebie. 42 sesje do przeglądu, najstarsza 6 dni. Przepływy OK.",
 "level": "ok | warn | bad",
 "next_action": {"text": "", "link": "", "kind": "", "since": 0},  // = needs_me[0], rendered as "Teraz: ..."
 "needs_me": [{"kind": "autocheck_edge|cron_failed|blocked_card|review|lost_session|feedby_decision",
               "what": "...", "project": "slug or board", "since": 1795575657.6, "link": "/mc?project=slug"}],
 "needs_me_total": 8,
 "projects": [{"slug": "", "title": "", "link": "", "charter": {"status": "", "type": "", "goal": "", "audience": []} ,
               "charter_known": true, "last_commit": {}, "last_activity": 0, "review_count": 0, "blockers": 0,
               "autocheck": "ok|null", "audience": []}],
 "machines": {"sessions": {"running": 0, "review": 0, "failed": 0, "lost": 0},
              "cron_failed_24h": 0, "blocked_cards": 0, "nodes": [{"name": "", "online": true, "detail": ""}]},
 "charters": {"draft": 0, "approved": 0, "drafts": []},
 "sources": {"sessions|cron|autocheck|kanban|nodes|charters|projects": {"ok": true, "age_s": 0.0, "error": null}}}
```

- Verdict is deterministic (no LLM). `needs_me` is capped at 5, ranked: failing autocheck edge, failed cron (24 h),
  blocked kanban board, oldest review session, lost session. Blocked kanban cards are grouped into one row per board.
  The "N rzeczy" count excludes review sessions and Feedby decisions (each has its own clause).
  Feedby board cards wait for the owner by design: shown as "N zgłoszeń Feedby czeka na Twoją decyzję" and ranked
  below review. `needs_me` shows up to 7 rows.
- `projects` = Mission Control projects with a commit in the last 7 days. Projects sharing a git remote URL are one
  tile (shortest slug wins, others listed in `mirrors`). Charters match by normalised slug (lowercase, no leading `_`,
  `_` == `-`).
- Every source fails open: its `sources.<name>` becomes `{ok:false, error:"brak danych: ..."}`, its data is
  `null`/empty and the page says "brak danych" instead of a false OK.
- Sources: `~/.hermes/state/code-dispatch/*/meta.json`, `~/.hermes/cron/executions.db` (read-only),
  `autocheck_flows.json`, `hermes kanban` (cached 120 s, stale-while-revalidate), `worker-dispatch status`
  (cached 300 s), `~/.hermes/state/jit-hub/charters/<slug>.json`. Override the root with `JIT_WALL_HERMES_HOME`.

## `POST /api/mc/charters/approve`

Body `{"slugs": ["faktury"], "audience": {"faktury": ["me", "dominik"]}}`. Audience entries must be `me` or one of the
charter's `audience_candidates[].who`. The whole batch is validated first (unknown slug -> 404, bad shape/audience -> 400,
nothing written); then each draft gets `status:"approved"`, `approved_at`, the chosen `audience`, written atomically
(tmp + rename). Non-draft charters are returned under `skipped`. Missing/wrong `Origin` or CSRF token -> 403.
