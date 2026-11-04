// Project Hub page: table of every registered project from GET /api/hub/projects.
// Rendering is pure string building over escaped values (esc), so node tests can run it without a DOM.
"use strict";

const PROJECTS_URL = "/api/hub/projects";
const COCKPIT_PREFIX = "/hub/";
const OBSIDIAN_SCHEME = "obsidian://";
const THEME_KEY = "jit-hub-theme";
const AUTO_REFRESH_MS = 60000;
const MAX_LISTED = 3;
const COLUMNS = 8;
const MINUTE_MS = 60000;
const HOUR_MIN = 60;
const DAY_MIN = 1440;
const FRESHNESS = {
  fresh: ["aktualny", "ok"],
  stale: ["nieaktualny", "warn"],
  never_built: ["nie zbudowano", "none"],
  error: ["błąd budowy", "bad"],
};
const SEVERITY = { high: "wysoki", medium: "średni", low: "niski" };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

function icon(id) {
  return `<svg class="ic" aria-hidden="true"><use href="#${id}"/></svg>`;
}

// {missing: reason} and {error: text} are the API's way to say "no data"; never shown as a number.
function problem(value) {
  if (value && typeof value === "object") {
    if (value.error) return `<span class="bad" title="${esc(value.error)}">błąd: ${esc(value.error)}</span>`;
    if (value.missing) return `<span class="muted" title="${esc(value.missing)}">brak danych</span>`;
  }
  return "";
}

function relTime(iso, now) {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "";
  const minutes = Math.max(0, Math.round((now - at) / MINUTE_MS));
  if (minutes < 1) return "przed chwilą";
  if (minutes < HOUR_MIN) return `${minutes} min temu`;
  if (minutes < DAY_MIN) return `${Math.round(minutes / HOUR_MIN)} godz. temu`;
  const days = Math.round(minutes / DAY_MIN);
  return days === 1 ? "1 dzień temu" : `${days} dni temu`;
}

function groupDigits(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function freshnessCell(f) {
  if (!f) return '<span class="muted">brak danych</span>';
  const [label, tone] = FRESHNESS[f.status] || [f.status || "nieznany", "none"];
  const title = f.error ? `Błąd: ${f.error}` : f.built_at ? `Zbudowano: ${f.built_at}` : "Kokpit nie był jeszcze budowany przez hub";
  return `<span class="badge ${tone}" title="${esc(title)}"><i></i>${esc(label)}</span>`;
}

function activityCell(a, now) {
  const issue = problem(a);
  if (issue || !a) return issue || '<span class="muted">brak danych</span>';
  return `<span title="${esc(a.at)}">${esc(relTime(a.at, now))}</span>`
    + `<span class="sub mono">${icon("i-branch")} ${esc(a.branch)} · ${esc(a.sha)}</span>`
    + `<span class="sub">${esc(a.subject)}</span>`;
}

function countCell(listing, warnWhenAny) {
  const issue = problem(listing);
  if (issue || !listing) return issue || '<span class="muted">brak danych</span>';
  const tone = listing.count === 0 ? "zero" : warnWhenAny ? "warn" : "";
  const items = (listing.items || []).slice(0, MAX_LISTED).map(item => `<li title="${esc(item)}">${esc(item)}</li>`).join("");
  return `<span class="cnt ${tone}">${esc(listing.count)}</span>${items ? `<ul class="items">${items}</ul>` : ""}`;
}

function tokensCell(t) {
  const issue = problem(t);
  if (issue || !t) return issue || '<span class="muted">brak danych</span>';
  const title = `Dni z danymi: ${t.days_with_data} od ${t.since}`;
  return `<span class="cnt" title="${esc(title)}">${esc(groupDigits(t.total_tokens))}</span>`;
}

function suggestionCell(s) {
  if (s === null) return '<span class="muted">brak sugestii</span>';
  const issue = problem(s);
  if (issue || !s) return issue || '<span class="muted">brak danych</span>';
  const sev = SEVERITY[s.severity] || s.severity || "";
  return `<div class="sugg"><span class="sev ${esc(s.severity)}">${esc(sev)}</span>${esc(s.summary)}`
    + `<span class="sub">Zalecenie: ${esc(s.action)}</span></div>`;
}

function folderHref(path) {
  return "file://" + String(path).split("/").map(encodeURIComponent).join("/");
}

function linksCell(row) {
  const cockpit = `<a class="link" href="${esc(COCKPIT_PREFIX + encodeURIComponent(row.slug))}" title="Kokpit projektu" aria-label="Kokpit projektu ${esc(row.slug)}">${icon("i-cockpit")}</a>`;
  const uri = row.dossier && typeof row.dossier.uri === "string" && row.dossier.uri.startsWith(OBSIDIAN_SCHEME) ? row.dossier.uri : "";
  const note = uri
    ? `<a class="link" href="${esc(uri)}" title="${esc(`Dossier w Obsidianie: ${row.dossier.note} (${row.dossier.source})`)}" aria-label="Dossier w Obsidianie">${icon("i-note")}</a>`
    : `<span class="link off" title="Brak danych o dossier">${icon("i-note")}</span>`;
  const folder = row.path
    ? `<a class="link" href="${esc(folderHref(row.path))}" title="${esc(`Folder: ${row.path}`)}" aria-label="Folder projektu">${icon("i-folder")}</a>`
    : "";
  return `<div class="links">${cockpit}${note}${folder}</div>`;
}

function worktreeItems(row) {
  const wt = row.worktrees;
  return wt && Array.isArray(wt.items) ? wt.items : [];
}

function projectCell(row, expanded) {
  const wt = row.worktrees;
  let toggle = "";
  if (wt && wt.count > 0) {
    toggle = `<button class="wt-toggle" data-slug="${esc(row.slug)}" aria-expanded="${expanded}">${icon("i-chevron")} worktree: ${esc(wt.count)}</button>`;
  } else if (problem(wt)) {
    toggle = `<span class="sub">worktree: ${problem(wt)}</span>`;
  }
  return `<span class="name">${esc(row.slug)}</span><span class="path">${esc(row.path)}</span>${toggle}`;
}

function worktreeRow(wt, now) {
  const commit = wt.last_commit || {};
  const when = problem(commit) || `<span title="${esc(commit.at)}">${esc(relTime(commit.at, now))}</span><span class="sub">${esc(commit.sha)} ${esc(commit.subject)}</span>`;
  const branch = wt.detached ? `odłączony HEAD ${esc(String(wt.head || "").slice(0, 7))}` : esc(wt.branch);
  return `<tr class="wt"><td colspan="2"><span class="branch">${icon("i-branch")} ${branch}</span><span class="path">${esc(wt.path)}</span></td>`
    + `<td colspan="${COLUMNS - 3}">${when}</td><td><div class="links"><a class="link" href="${esc(folderHref(wt.path))}" title="${esc(`Folder: ${wt.path}`)}" aria-label="Folder worktree">${icon("i-folder")}</a></div></td></tr>`;
}

function projectRow(row, expanded, now) {
  if (row.error) {
    return `<tr><td>${projectCell(row, false)}</td><td colspan="${COLUMNS - 1}"><span class="bad">Błąd odczytu projektu: ${esc(row.error)}</span></td></tr>`;
  }
  return `<tr><td>${projectCell(row, expanded)}</td><td>${freshnessCell(row.freshness)}</td>`
    + `<td>${activityCell(row.last_activity, now)}</td><td class="num">${countCell(row.open_tasks, false)}</td>`
    + `<td class="num">${countCell(row.blockers, true)}</td><td class="num">${tokensCell(row.tokens_7d)}</td>`
    + `<td>${suggestionCell(row.top_suggestion)}</td><td>${linksCell(row)}</td></tr>`;
}

function activityTime(row) {
  const at = row.last_activity && Date.parse(row.last_activity.at);
  return Number.isFinite(at) ? at : -Infinity;
}

function commitTime(wt) {
  const at = wt.last_commit && Date.parse(wt.last_commit.at);
  return Number.isFinite(at) ? at : -Infinity;
}

function sortRows(rows, sort) {
  const byName = (a, b) => String(a.slug).localeCompare(String(b.slug));
  const copy = rows.slice();
  return sort === "name" ? copy.sort(byName) : copy.sort((a, b) => (activityTime(b) - activityTime(a)) || byName(a, b));
}

function matches(text, query) {
  return String(text ?? "").toLowerCase().includes(query);
}

// One entry per visible project: the row plus the worktrees to show (all when expanded, only matches on search).
function filterRows(rows, query) {
  const q = String(query || "").trim().toLowerCase();
  return rows.map(row => {
    const own = !q || [row.slug, row.path, row.last_activity && row.last_activity.branch, row.dossier && row.dossier.name].some(v => matches(v, q));
    const hits = q ? worktreeItems(row).filter(wt => matches(wt.branch, q) || matches(wt.path, q)) : [];
    return own || hits.length ? { row, hits, searched: Boolean(q) } : null;
  }).filter(Boolean);
}

function renderRows(rows, state) {
  const now = state.now ?? Date.now();
  const visible = filterRows(sortRows(rows, state.sort), state.query);
  if (!rows.length) return `<tr><td colspan="${COLUMNS}" class="empty">Rejestr nie zawiera projektów. Uruchom jit init w projekcie albo jit hub scan.</td></tr>`;
  if (!visible.length) return `<tr><td colspan="${COLUMNS}" class="empty">Żaden projekt nie pasuje do wyszukiwania.</td></tr>`;
  return visible.map(({ row, hits, searched }) => {
    const open = state.expanded && state.expanded.has(row.slug);
    const shown = (open ? worktreeItems(row) : searched ? hits : []).slice().sort((a, b) => commitTime(b) - commitTime(a));
    return projectRow(row, Boolean(open || shown.length), now) + shown.map(wt => worktreeRow(wt, now)).join("");
  }).join("");
}

function summaryLine(payload, now) {
  const rows = payload.projects || [];
  const worktrees = rows.reduce((sum, row) => sum + ((row.worktrees && row.worktrees.count) || 0), 0);
  const at = payload.generated_at ? new Date(payload.generated_at * 1000).toISOString() : "";
  return `projekty: ${rows.length}, worktree: ${worktrees} · rejestr: ${payload.registry || "nieznany"} · dane z ${at || "brak czasu"} (${relTime(at, now) || "brak"})`;
}

// ---- browser wiring ----
const view = { payload: null, query: "", sort: "activity", expanded: new Set() };

function paint() {
  const rows = (view.payload && view.payload.projects) || [];
  document.getElementById("hub-rows").innerHTML = renderRows(rows, { query: view.query, sort: view.sort, expanded: view.expanded });
  if (view.payload) document.getElementById("hub-foot").textContent = summaryLine(view.payload, Date.now());
}

function showError(text) {
  const banner = document.getElementById("hub-error");
  banner.textContent = text || "";
  banner.hidden = !text;
}

async function load() {
  const meta = document.getElementById("hub-meta");
  meta.textContent = "ładowanie";
  try {
    const res = await fetch(PROJECTS_URL, { cache: "no-store", headers: { Accept: "application/json" } });
    const body = await res.json().catch(() => null);
    if (!res.ok || !body || !Array.isArray(body.projects)) {
      throw new Error(`${PROJECTS_URL}: HTTP ${res.status} ${(body && body.error) || "niepoprawna odpowiedź"}`);
    }
    view.payload = body;
    showError("");
    meta.textContent = `odświeżono ${new Date().toLocaleTimeString("pl-PL")}`;
  } catch (err) {
    showError(`Nie udało się pobrać listy projektów: ${err.message}`);
    meta.textContent = "błąd";
  }
  paint();
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode: theme is not remembered */ }
}

function wire() {
  document.getElementById("hub-search").addEventListener("input", e => { view.query = e.target.value; paint(); });
  document.getElementById("hub-sort").addEventListener("change", e => { view.sort = e.target.value; paint(); });
  document.getElementById("hub-refresh").addEventListener("click", load);
  document.getElementById("hub-theme").addEventListener("click", toggleTheme);
  document.getElementById("hub-rows").addEventListener("click", e => {
    const button = e.target.closest(".wt-toggle");
    if (!button) return;
    const slug = button.dataset.slug;
    if (view.expanded.has(slug)) view.expanded.delete(slug); else view.expanded.add(slug);
    paint();
  });
  document.addEventListener("keydown", e => {
    if ((e.key === "r" || e.key === "R") && !e.metaKey && !e.ctrlKey && e.target.tagName !== "INPUT") load();
  });
  load();
  setInterval(load, AUTO_REFRESH_MS);
}

if (typeof document !== "undefined") wire();
if (typeof module !== "undefined" && module.exports) {
  module.exports = { esc, relTime, freshnessCell, tokensCell, suggestionCell, linksCell, filterRows, sortRows, renderRows, summaryLine, PROJECTS_URL };
}
