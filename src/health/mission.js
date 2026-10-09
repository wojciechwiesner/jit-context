// Mission Control controller: URL state, polling, wiring panels together.
// innerHTML safety: every dynamic value goes through MC.esc (mission_panels.js);
// diagram SVG comes from Mermaid with securityLevel "strict" (labels sanitized).
"use strict";

const POLL_MS = 15000;
const MERMAID_SRC = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js";
const $ = (id) => document.getElementById(id);

const ui = { project: null, session: null, tab: "status", hours: 168, allSessions: false };
let projectDetail = null;
let sessions = [];
let mermaidReady = null;

function readUrl() {
  const q = new URLSearchParams(location.search);
  ui.project = q.get("project");
  ui.session = q.get("session");
  ui.tab = q.get("tab") || "status";
}

function writeUrl() {
  const q = new URLSearchParams();
  if (ui.project) q.set("project", ui.project);
  if (ui.session) q.set("session", ui.session);
  if (ui.tab !== "status") q.set("tab", ui.tab);
  history.replaceState(null, "", "/mc" + (q.toString() ? "?" + q : ""));
}

async function getJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `${url} -> HTTP ${res.status}`);
  return body;
}

function showError(err) {
  const banner = $("error-banner");
  banner.textContent = err ? String(err.message || err) : "";
  banner.classList.toggle("on", Boolean(err));
}

async function loadProjects() {
  const { projects } = await getJson("/api/mc/projects");
  if (!ui.project && projects.length) ui.project = projects[0].slug;
  $("project-select").innerHTML = projects.map((p) =>
    `<option value="${MC.esc(p.slug)}" ${p.slug === ui.project ? "selected" : ""}>${MC.esc(p.slug)}${p.blockers ? " · " + p.blockers + " blok." : ""}</option>`).join("");
}

async function loadSessions() {
  const project = ui.allSessions ? "" : encodeURIComponent(ui.project || "");
  const data = await getJson(`/api/mc/sessions?project=${project}&hours=${ui.hours}&limit=60`);
  sessions = data.sessions.sort((a, b) => (b.live - a.live) || ((b.last_activity || 0) - (a.last_activity || 0)));
  if (!ui.session && sessions.length) selectSession(sessions[0].id);
  renderSessions();
}

function renderSessions() {
  $("session-list").innerHTML = sessions.length ? sessions.map((s) => MC.sessionItem(s, ui.session)).join("")
    : `<li class="empty">Brak sesji z cwd w tym projekcie w wybranym okresie. Zaznacz „wszystkie projekty”.</li>`;
  const current = sessions.find((s) => s.id === ui.session);
  const pill = $("live-pill");
  pill.className = "pill " + (current && current.live ? "live" : "idle");
  pill.innerHTML = `<i></i>${current && current.live ? "LIVE" : "IDLE"}`;
  $("stream-meta").textContent = current ? `${current.id} · ${current.model || "-"}` : ui.session || "-";
}

function selectSession(id) {
  if (id === ui.session && $("stream-frame").src.includes("/live")) return;
  ui.session = id;
  const url = "/live?session=" + encodeURIComponent(id || "");
  $("stream-frame").src = url;
  $("stream-open").href = url;
  writeUrl();
  renderSessions();
}

async function loadProject() {
  if (!ui.project) return;
  projectDetail = await getJson("/api/mc/project?slug=" + encodeURIComponent(ui.project));
  renderProject();
}

function renderProject() {
  const p = projectDetail;
  if (!p) return;
  $("tab-status").innerHTML = MC.statusTab(p);
  $("tab-info").innerHTML = MC.infoTab(p, sessions.length);
  const cockpit = $("tab-cockpit");
  const wanted = p.cockpit_url || "";
  if (cockpit.dataset.src !== wanted) {
    cockpit.dataset.src = wanted;
    cockpit.innerHTML = wanted ? `<iframe title="Cockpit projektu" src="${MC.esc(wanted)}"></iframe>`
      : `<div class="empty">Brak .planning/state.html — uruchom generator kokpitu.</div>`;
  }
  const diagramKey = p.slug + ":" + ((p.diagram && p.diagram.mermaid) || "").length;
  if ($("tab-diagram").dataset.key !== diagramKey) {
    $("tab-diagram").dataset.key = diagramKey;
    $("tab-diagram").innerHTML = MC.diagramShell(p);
    renderDiagram();
  }
}

function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = MERMAID_SRC;
      s.onload = () => {
        window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark" });
        resolve(window.mermaid);
      };
      s.onerror = () => { mermaidReady = null; reject(new Error("Nie udało się załadować Mermaid z CDN")); };
      document.head.appendChild(s);
    });
  }
  return mermaidReady;
}

async function renderDiagram() {
  const canvas = $("diagram-canvas");
  const source = projectDetail && projectDetail.diagram && projectDetail.diagram.mermaid;
  if (!canvas || !source) return;
  try {
    const mermaid = await loadMermaid();
    const { svg } = await mermaid.render("mc-diagram-" + Date.now(), source);
    canvas.innerHTML = svg;
  } catch (err) {
    canvas.innerHTML = `<div><div class="diagram-err">Błąd diagramu: ${MC.esc(err.message || err)}</div><pre>${MC.esc(source)}</pre></div>`;
  }
  const zoom = $("diagram-zoom");
  if (zoom) zoom.onclick = () => canvas.classList.toggle("wide");
}

function setTab(tab) {
  ui.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  ["status", "diagram", "cockpit", "info"].forEach((t) => { $("tab-" + t).hidden = t !== tab; });
  writeUrl();
}

async function refresh(full) {
  const btn = $("refresh-btn");
  btn.classList.add("spin");
  try {
    if (full) await loadProjects();
    await Promise.all([loadSessions(), loadProject()]);
    showError(null);
    $("refresh-meta").textContent = "odświeżono " + new Date().toLocaleTimeString("pl-PL");
  } catch (err) {
    showError(err);
  } finally {
    setTimeout(() => btn.classList.remove("spin"), 800);
  }
}

async function loadUser() {
  try {
    const who = await getJson("/api/mc/whoami");
    $("user-name").textContent = who.user || (who.via === "local" ? "lokalnie" : "-");
    $("user-badge").title = who.via === "sso" ? "Zalogowano przez Borg SSO" : "Dostęp lokalny (loopback)";
  } catch (err) {
    $("user-name").textContent = "-";
  }
}

function bindEvents() {
  $("project-select").onchange = (e) => {
    ui.project = e.target.value;
    ui.session = null;
    writeUrl();
    refresh(false);
  };
  $("session-list").onclick = (e) => {
    const btn = e.target.closest("button[data-session]");
    if (btn) selectSession(btn.dataset.session);
  };
  document.querySelectorAll(".tabs button").forEach((b) => { b.onclick = () => setTab(b.dataset.tab); });
  document.querySelectorAll(".seg button").forEach((b) => {
    b.onclick = () => {
      ui.hours = Number(b.dataset.hours);
      document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
      loadSessions().catch(showError);
    };
  });
  $("all-sessions").onchange = (e) => { ui.allSessions = e.target.checked; loadSessions().catch(showError); };
  $("refresh-btn").onclick = () => refresh(true);
  $("focus-btn").onclick = () => document.querySelector(".mc").classList.toggle("focus");
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,select,textarea")) return;
    if (e.key === "r") refresh(true);
    if (e.key === "f") $("focus-btn").click();
    if (["1", "2", "3", "4"].includes(e.key)) setTab(["status", "diagram", "cockpit", "info"][Number(e.key) - 1]);
  });
}

async function boot() {
  readUrl();
  bindEvents();
  setTab(ui.tab);
  loadUser();
  if (ui.session) selectSession(ui.session);
  await refresh(true);
  setInterval(() => refresh(false), POLL_MS);
}

boot();
