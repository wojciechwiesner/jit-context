# Mission Control — unified live window (spec)

One window that shows, side by side: the live Hermes session stream, the project cockpit
(state, blockers, diagram), session history for that project and the important facts.
Served by the existing livestream server (`health.livestream`, port 8766), reachable
locally and from outside via `https://live.borg.tools` behind Borg SSO.

## Why here

The livestream server already owns read-only access to `~/.hermes/state.db` and the JIT
telemetry. Adding a second server would duplicate that and add one more launchd job.
Mission Control is a new route plus a few read-only API endpoints on the same server.

## Routes (all GET, all read-only)

| Route | Returns |
|---|---|
| `/mc` | `mission.html` (Mission Control shell) |
| `/static/mission.css`, `/static/mission.js`, `/static/mission_panels.js` | assets (whitelisted) |
| `/api/mc/projects` | `{"projects": [ProjectSummary]}` sorted by `last_activity` desc |
| `/api/mc/project?slug=<slug>` | `ProjectDetail` or 404 `{"error": ...}` |
| `/api/mc/sessions?project=<slug>&hours=<int, default 168>&limit=<int, default 40>` | `{"sessions": [SessionRow]}` |
| `/cockpit/<slug>` | that project's `.planning/state.html` as `text/html` (404 if missing) |
| `/api/mc/whoami` | `{"user": "<email or null>", "via": "local" or "sso"}` |

Existing routes (`/live`, `/api/session`, `/api/session/stream`, ...) are unchanged.

## Data shapes

```
ProjectSummary = {slug, path, title, branch, last_commit: {hash, msg, iso} | null,
                  open_tasks: int, blockers: int, sessions_7d: int,
                  last_activity: float (unix ts; max of last commit and last session)}

ProjectDetail = ProjectSummary + {
  state: {exists, updated, age_days, open: [{section, text}], open_count, done_count, blockers: [str]},
  thoughts: [str], deploy: [obj], checks: [{name, ok, detail}],
  git: {branch, dirty_count, log: [{hash, msg, ago, iso}]},
  obsidian: {exists, mtime, uri},
  diagram: {source: "file" | "auto", mermaid: str, note: str},
  cockpit_url: "/cockpit/<slug>" | null,
  dossier: {last_session: str | null, goal: str | null}   # parsed from the Obsidian note
}

SessionRow = {id, title, source, model, started_at, last_activity, messages, tools,
              live: bool, live_url: "/live?session=<id>"}
```

Cockpit data comes from the canonical generator
(`~/Documents/Wojciech/templates/sota-starter/cockpit/collect.js`) via a small Node
export script, so Mission Control and `state.html` never disagree.

Sessions are matched to a project by `sessions.cwd` (exact path or a subdirectory).

## Diagram (the bug this fixes)

`collect.js` hides any `ARCHITECTURE.mmd` that still contains the starter template node
`UI / Web Client`; 87 of 90 projects still have that template, so their cockpits show no
diagram at all. Mission Control never hides it:

- real `ARCHITECTURE.mmd` -> `source: "file"`;
- template or missing -> `source: "auto"`: a deterministic diagram built from the repo
  (docker-compose services, `apps/*` / `packages/*`, top-level code dirs, detected stack:
  Next.js, FastAPI, Postgres, Supabase, Redis, Prisma), with `note` saying it is generated.

One implementation: `~/Documents/Wojciech/templates/sota-starter/cockpit/arch.js`, used by
`collect.js`. It fixes every project's `state.html` and Mission Control (which reads
cockpit data through `collect.js`) at the same time. `ARCHITECTURE.mmd` files are never
rewritten automatically.

## Layout (Mission Control UI)

Dark, dense, same palette as the livestream panel (`livestream.css` variables), 100vh,
no page scroll, panels scroll internally, SVG icons only, zero emoji.

```
+--------------------------------------------------------------------------------+
| brand | project switcher | session switcher | LIVE pill | user (SSO) | refresh |
+------------+-----------------------------------------------+-------------------+
| SESSIONS   |  LIVE STREAM (iframe /live?session=<id>)      | PROJECT           |
| history of |                                               | tabs: Status |    |
| the chosen |                                               | Diagram | Cockpit |
| project,   |                                               | | Info            |
| live first |                                               |                   |
+------------+-----------------------------------------------+-------------------+
```

- Left rail: session history for the selected project (live sessions pinned on top,
  then by recency), click = load that session in the stream.
- Centre: the existing livestream page embedded, no re-implementation.
- Right: Status (KPIs open/blockers/sessions, blockers list, open tasks, deploy, checks,
  last commits), Diagram (Mermaid 11, rendered client side, source badge file/auto),
  Cockpit (iframe of `/cockpit/<slug>`), Info (Obsidian SSOT freshness, thoughts,
  dossier last session, paths).
- State in URL: `/mc?project=<slug>&session=<id>&tab=<status|diagram|cockpit|info>`.
- Polls `/api/mc/projects` and the session list every 15 s.

## Security

- Server binds `0.0.0.0:8766` so borg nginx can reach it over Tailscale.
- Requests from loopback are allowed. Requests from any other address are allowed only
  when the peer IP is in `JIT_MC_TRUSTED_PROXIES` (default `100.118.47.46`, borg) AND the
  request carries `X-Forwarded-Email` / `X-Auth-Request-Email` set by the SSO snippet, or
  the borg break-glass header path. Everything else gets 403.
- `/cockpit/<slug>` resolves `slug` against the project list only (no path traversal).
- Public entry: `https://live.borg.tools` -> borg nginx (`snippets/sso.conf` +
  `sso-location.conf`, oauth2-proxy-borg :8105, cookie domain `.borg.tools`) ->
  `http://100.118.237.121:8766`, buffering off for SSE.

## Acceptance

1. `python3 -m pytest src/tests -q` green, including `test_mission_control.py`.
2. `/mc` renders in headless Chrome: 3 columns, session list non-empty, stream iframe
   loaded, Diagram tab contains an `<svg>` for a template project and for a real one,
   zero console errors.
3. `https://live.borg.tools/mc` without a cookie -> 302 to `sso.borg.tools`.
4. Direct LAN request to `192.168.100.18:8766` -> 403.
