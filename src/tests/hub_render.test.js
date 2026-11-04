// String tests of the hub page renderer (src/health/hub.js), no DOM needed. Run by test_hub_page.py.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const hub = require(path.join(__dirname, "..", "health", "hub.js"));

const NOW = Date.parse("2026-11-04T12:00:00Z");
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;

function row(slug, at, extra = {}) {
  return {
    slug, path: `/p/${slug}`,
    freshness: { status: "fresh", built_at: "2026-11-04T11:00:00" },
    last_activity: { at, branch: "main", sha: "abc1234", subject: `work on ${slug}` },
    open_tasks: { count: 2, items: ["H14 hub ui", "H15 chat"] },
    blockers: { count: 0, items: [] },
    tokens_7d: { total_tokens: 1234567, days_with_data: 3, since: "2026-10-29" },
    top_suggestion: { id: "stale_state", severity: "high", summary: "STATE.md jest stary", action: "Zaktualizuj STATE.md", evidence: [] },
    worktrees: { count: 0, items: [] },
    dossier: { name: slug, note: `projects/${slug}.md`, source: "nazwa katalogu", uri: `obsidian://open?vault=Wojciech&file=projects%2F${slug}.md` },
    ...extra,
  };
}

const WORKTREE = {
  path: "/p/alpha-wt-hub", branch: "feat/project-hub", head: "deadbeef", detached: false,
  last_commit: { at: "2026-11-04T10:00:00Z", sha: "def5678", subject: "feat(hub): api" },
};

test("renders every column, links and Polish labels", () => {
  const html = hub.renderRows([row("alpha", "2026-11-04T11:30:00Z")], { query: "", sort: "activity", now: NOW });
  assert.match(html, /alpha/);
  assert.match(html, /aktualny/);
  assert.match(html, /30 min temu/);
  assert.match(html, /main · abc1234/);
  assert.match(html, /1 234 567/);
  assert.match(html, /wysoki/);
  assert.match(html, /Zalecenie: Zaktualizuj STATE.md/);
  assert.match(html, /href="\/hub\/alpha"/);
  assert.match(html, /href="obsidian:\/\/open\?vault=Wojciech&amp;file=projects%2Falpha.md"/);
  assert.match(html, /href="file:\/\/\/p\/alpha"/);
  assert.match(html, /<use href="#i-cockpit"\/>/);
  assert.doesNotMatch(html, EMOJI);
});

test("escapes model and file text instead of injecting markup", () => {
  const evil = row("x", "2026-11-04T11:00:00Z", {
    top_suggestion: { severity: "low", summary: "<img src=x onerror=alert(1)>", action: "\"><script>", evidence: [] },
    open_tasks: { count: 1, items: ["<b>bold</b>"] },
  });
  const html = hub.renderRows([evil], { query: "", sort: "activity", now: NOW });
  assert.doesNotMatch(html, /<img|<script|<b>/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test("missing and error values are shown as such, never as zero", () => {
  const html = hub.renderRows([row("m", "2026-11-04T11:00:00Z", {
    tokens_7d: { missing: "brak pliku stats" },
    top_suggestion: { error: "nieczytelny plik" },
    blockers: { missing: "brak pliku .planning/STATE.md" },
    freshness: { status: "never_built" },
  })], { query: "", sort: "activity", now: NOW });
  assert.match(html, /brak danych/);
  assert.match(html, /błąd: nieczytelny plik/);
  assert.match(html, /nie zbudowano/);
  assert.doesNotMatch(html, />0</);
  assert.match(hub.suggestionCell(null), /brak sugestii/);
});

test("sorts by last activity (newest first, missing last) and by name", () => {
  const rows = [row("b", "2026-11-01T00:00:00Z"), row("c", null, { last_activity: { missing: "brak" } }), row("a", "2026-11-03T00:00:00Z")];
  assert.deepEqual(hub.sortRows(rows, "activity").map(r => r.slug), ["a", "b", "c"]);
  assert.deepEqual(hub.sortRows(rows, "name").map(r => r.slug), ["a", "b", "c"].sort());
  const html = hub.renderRows(rows, { query: "", sort: "activity", now: NOW });
  assert.ok(html.indexOf("/p/a") < html.indexOf("/p/b") && html.indexOf("/p/b") < html.indexOf("/p/c"));
});

test("worktrees are grouped under their repo: collapsed, expanded, and found by search", () => {
  const repo = row("alpha", "2026-11-04T11:00:00Z", { worktrees: { count: 1, items: [WORKTREE] } });
  const other = row("beta", "2026-11-04T09:00:00Z");
  const collapsed = hub.renderRows([repo, other], { query: "", sort: "activity", now: NOW });
  assert.match(collapsed, /worktree: 1/);
  assert.match(collapsed, /aria-expanded="false"/);
  assert.doesNotMatch(collapsed, /class="wt"/);
  const expanded = hub.renderRows([repo, other], { query: "", sort: "activity", now: NOW, expanded: new Set(["alpha"]) });
  const wtAt = expanded.indexOf('class="wt"');
  assert.ok(wtAt > expanded.indexOf("/p/alpha") && wtAt < expanded.indexOf("/p/beta"));
  assert.match(expanded, /feat\/project-hub/);
  const searched = hub.renderRows([repo, other], { query: "project-hub", sort: "activity", now: NOW });
  assert.match(searched, /class="wt"/);
  assert.doesNotMatch(searched, /\/p\/beta/);
});

test("search filters projects, empty states are explicit", () => {
  const rows = [row("alpha", "2026-11-04T11:00:00Z"), row("beta", "2026-11-04T10:00:00Z")];
  const html = hub.renderRows(rows, { query: "BET", sort: "activity", now: NOW });
  assert.match(html, /\/p\/beta/);
  assert.doesNotMatch(html, /\/p\/alpha/);
  assert.match(hub.renderRows(rows, { query: "zzz", sort: "activity", now: NOW }), /Żaden projekt nie pasuje/);
  assert.match(hub.renderRows([], { query: "", sort: "activity", now: NOW }), /Rejestr nie zawiera projektów/);
});

test("a broken project row shows its error and a non-obsidian dossier uri is not linked", () => {
  const html = hub.renderRows([{ slug: "bad", path: "/p/bad", error: "OSError: boom" }], { query: "", sort: "activity", now: NOW });
  assert.match(html, /Błąd odczytu projektu: OSError: boom/);
  const links = hub.linksCell(row("j", "2026-11-04T11:00:00Z", { dossier: { uri: "javascript:alert(1)" } }));
  assert.doesNotMatch(links, /javascript:/);
  assert.match(links, /Brak danych o dossier/);
});

test("footer counts projects and worktrees and names the registry", () => {
  const payload = { generated_at: NOW / 1000, registry: "/tmp/reg.json", projects: [row("a", "2026-11-04T11:00:00Z", { worktrees: { count: 2, items: [] } })] };
  assert.match(hub.summaryLine(payload, NOW), /^projekty: 1, worktree: 2 · rejestr: \/tmp\/reg.json · dane z 2026-11-04T12:00:00.000Z \(przed chwilą\)$/);
});

test("the page script fetches the projects API", () => {
  assert.equal(hub.PROJECTS_URL, "/api/hub/projects");
});
