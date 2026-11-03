// Small HTML helpers shared by the core renderer and project modules (.planning/cockpit.module.js).

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Inline `code` and **bold** from markdown, applied after escaping.
function md(text) {
  return esc(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
}

function badge(text, tone = "muted") {
  return `<span class="badge ${tone}">${esc(text)}</span>`;
}

function card(title, body, extra = "") {
  return `<section class="card ${extra}"><h2>${esc(title)}</h2>${body}</section>`;
}

function list(items, empty = "Brak") {
  return items.length ? `<ul>${items.map(i => `<li>${i}</li>`).join("")}</ul>` : `<p class="muted">${esc(empty)}</p>`;
}

// columns: [{label, cell: row => html}]; filterable adds a search box above the table.
function table(columns, rows, { filterable = false, empty = "Brak" } = {}) {
  if (!rows.length) return `<p class="muted">${esc(empty)}</p>`;
  const head = columns.map(c => `<th>${esc(c.label)}</th>`).join("");
  const body = rows.map(r => `<tr>${columns.map(c => `<td>${c.cell(r)}</td>`).join("")}</tr>`).join("");
  const filter = filterable ? `<input class="filter" name="filter" placeholder="Filtruj..." oninput="filterTable(this)">` : "";
  return `${filter}<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function kpi(label, value, tone = "") {
  return `<div class="kpi ${tone}"><div class="kpi-value">${esc(value)}</div><div class="kpi-label">${esc(label)}</div></div>`;
}

function fileLink(absPath, label) {
  return `<a href="file://${encodeURI(absPath)}">${esc(label)}</a>`;
}

function relDays(date, now = new Date()) {
  const days = Math.floor((now - new Date(date)) / 86400000);
  if (Number.isNaN(days)) return "";
  if (days <= 0) return "dziś";
  return days === 1 ? "wczoraj" : `${days} dni temu`;
}

module.exports = { esc, escapeHtml: esc, md, badge, card, list, table, kpi, fileLink, relDays };
