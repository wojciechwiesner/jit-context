// Mission Control panel renderers. Pure functions: data in, HTML string out.
// Shapes follow docs/MISSION_CONTROL.md (ProjectDetail, SessionRow).
"use strict";

const MC = {};

MC.esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

MC.ago = (unixSeconds) => {
  if (!unixSeconds) return "-";
  const diff = Math.max(0, Date.now() / 1000 - unixSeconds);
  if (diff < 60) return Math.round(diff) + "s";
  if (diff < 3600) return Math.round(diff / 60) + "m";
  if (diff < 86400) return Math.round(diff / 3600) + "h";
  return Math.round(diff / 86400) + "d";
};

MC.toUnix = (value) => {
  if (!value) return null;
  if (typeof value === "number") return value;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms / 1000;
};

function block(title, inner, badge = "") {
  return `<div class="block"><h3>${MC.esc(title)}${badge}</h3><div class="in">${inner}</div></div>`;
}

function kpi(label, value, tone) {
  return `<div class="kpi ${tone}"><div class="k">${MC.esc(label)}</div><div class="v">${MC.esc(value)}</div></div>`;
}

MC.sessionItem = (session, activeId) => {
  const title = session.title || "(bez tytułu)";
  const on = session.id === activeId ? "on" : "";
  const live = session.live ? "live" : "";
  return `<li><button class="${on}" data-session="${MC.esc(session.id)}">
    <div class="s-top"><span class="dot ${live}"></span>${MC.esc(session.source || "-")}
      <span class="when">${session.live ? "LIVE" : MC.ago(session.last_activity || session.started_at)}</span></div>
    <div class="s-title">${MC.esc(title)}</div>
    <div class="s-sub">${MC.esc(session.model || "-")} · ${session.messages ?? 0} msg · ${session.tools ?? 0} tools</div>
  </button></li>`;
};

MC.statusTab = (p) => {
  const st = p.state || {};
  const blockers = st.blockers || [];
  const kpis = `<div class="kpis">${kpi("Otwarte", st.open_count ?? 0, st.open_count ? "info" : "")}${
    kpi("Blokery", blockers.length, blockers.length ? "bad" : "ok")}${kpi("Sesje 7d", p.sessions_7d ?? 0, "")}</div>`;
  const blockersHtml = blockers.length
    ? block("Blokery", `<ul class="list bad">${blockers.map((b) => `<li>${MC.blockerText(b)}</li>`).join("")}</ul>`) : "";
  const open = (st.open || []).map((t) =>
    `<li><span class="sec">${MC.esc(t.section || "")}</span>${MC.esc(t.text)}</li>`).join("");
  const openHtml = block("Otwarte zadania", open ? `<ul class="list">${open}</ul>` : `<div class="note">Brak otwartych zadań w STATE.md</div>`);
  return kpis + blockersHtml + openHtml + MC.commitsBlock(p) + MC.checksBlock(p) + MC.deployBlock(p);
};

MC.commitsBlock = (p) => {
  const log = (p.git && p.git.log) || [];
  if (!log.length) return "";
  const rows = log.map((c) => `<div class="commit"><code>${MC.esc(c.hash)}</code><span>${MC.esc(c.msg)}</span><span>${MC.esc(c.ago)}</span></div>`).join("");
  const dirty = p.git.dirty_count ? `<span class="badge stale">${p.git.dirty_count} zmian</span>` : "";
  return block(`Git · ${p.git.branch || "-"}`, rows, dirty);
};

MC.checksBlock = (p) => {
  const checks = p.checks || [];
  if (!checks.length) return "";
  const rows = checks.map((c) => `<div class="check"><span class="st ${c.ok ? "ok" : "bad"}">${c.ok ? "OK" : "FAIL"}</span><span>${MC.esc(c.name)}${c.detail ? ` <span class="note">${MC.esc(c.detail)}</span>` : ""}</span></div>`).join("");
  return block("Autocheck", rows);
};

// STATE.md blockers come either as plain strings or as table rows: [id, what, impact, owner].
MC.blockerText = (b) => {
  if (!Array.isArray(b)) return MC.esc(b);
  const [id, ...rest] = b;
  return `<span class="sec">${MC.esc(id)}</span>${rest.map(MC.esc).join(" · ")}`;
};

MC.deployBlock = (p) => {
  const deploy = p.deploy || [];
  if (!deploy.length) return "";
  const rows = deploy.map((d) => {
    const probe = d.probe && d.probe.code ? `<span class="badge">${MC.esc(d.probe.code)}</span>` : "";
    const link = d.url ? `<a href="${MC.esc(d.url)}" target="_blank" rel="noopener">${MC.esc(d.url)}</a>` : MC.esc(d.host || "-");
    return `<div class="kv"><span>${MC.esc(d.name || "target")}</span><b>${link} ${probe}</b>${d.note ? `<span></span><b class="note">${MC.esc(d.note)}</b>` : ""}</div>`;
  }).join("");
  return block("Deploy", rows);
};

MC.diagramShell = (p) => {
  const d = p.diagram || {};
  if (!d.mermaid) return `<div class="empty">Brak diagramu dla tego projektu.</div>`;
  const badge = `<span class="badge ${d.source === "auto" ? "auto" : "file"}">${d.source === "auto" ? "auto z repo" : "ARCHITECTURE.mmd"}</span>`;
  const note = d.note ? `<div class="note">${MC.esc(d.note)}</div>` : "";
  return `<div class="toolbar">${badge}<span class="sp"></span><button class="btn" id="diagram-zoom">Pełna szerokość</button></div>
    ${note}<div class="diagram" id="diagram-canvas"><div class="note">Renderowanie…</div></div>
    <details><summary>Źródło Mermaid</summary><pre class="src">${MC.esc(d.mermaid)}</pre></details>`;
};

MC.infoTab = (p, sessionsCount) => {
  const ob = p.obsidian || {};
  const obUnix = MC.toUnix(ob.mtime);
  const lastCommit = MC.toUnix(p.last_commit && p.last_commit.iso);
  const stale = obUnix && lastCommit && lastCommit - obUnix > 86400;
  const freshness = !ob.exists ? `<span class="badge stale">brak notatki</span>`
    : `<span class="badge ${stale ? "stale" : "fresh"}">${stale ? "wymaga aktualizacji" : "zsynchronizowany"}</span>`;
  const ssot = `<div class="kv"><span>notatka</span><b>${ob.uri ? `<a href="${MC.esc(ob.uri)}">otwórz w Obsidian</a>` : "-"}</b>
    <span>zmieniona</span><b>${obUnix ? MC.ago(obUnix) + " temu" : "-"}</b>
    <span>ostatni commit</span><b>${lastCommit ? MC.ago(lastCommit) + " temu" : "-"}</b></div>`;
  const dossier = p.dossier || {};
  const last = `<div class="kv"><span>sesja</span><b>${MC.esc(dossier.last_session || "-")}</b><span>cel</span><b>${MC.esc(dossier.goal || "-")}</b></div>`;
  const thoughts = (p.thoughts || []).map((t) => `<li>${MC.esc(t)}</li>`).join("");
  const st = p.state || {};
  const paths = `<div class="kv"><span>repo</span><b>${MC.esc(p.path)}</b><span>STATE.md</span><b>${st.exists ? `${MC.esc(st.updated || "-")} (${st.age_days ?? "?"} d)` : "brak"}</b>
    <span>sesje w historii</span><b>${sessionsCount}</b></div>`;
  return block("Obsidian SSOT", ssot, freshness) + block("Ostatnia sesja JIT", last)
    + (thoughts ? block("Thoughts (advisory)", `<ul class="list">${thoughts}</ul>`) : "") + block("Ścieżki", paths);
};

window.MC = MC;
