/* Operator Wall renderer. All text goes through textContent (no innerHTML), so source data cannot inject markup. */
const REFRESH_S = 60;
const MAX_TILES = 20;
const MAX_CARDS = 6;
const KIND_LABEL = {autocheck_edge: "Przepływ", cron_failed: "Cron", blocked_card: "Zablokowane", review: "Do przeglądu", lost_session: "Sesja", feedby_decision: "Decyzja"};
const TYPE_LABEL = {"client-delivery": "Klient", platform: "Infrastruktura", product: "Produkt", experiment: "Eksperyment", dormant: "Uśpiony"};
const FLOW_LABEL = {ok: "OK", degraded: "spowolnione", broken: "zepsute"};
const SOURCE_LABEL = {sessions: "sesje", cron: "cron", autocheck: "przepływy", kanban: "kanban", nodes: "maszyny", charters: "chartery", projects: "projekty"};
let wall = null;
let countdown = REFRESH_S;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v; else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined) el.append(kid);
  return el;
}

function ago(epoch) {
  if (!epoch) return "brak daty";
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min temu`;
  if (s < 86400) return `${Math.round(s / 3600)} h temu`;
  return `${Math.round(s / 86400)} dni temu`;
}

const CHEVRON = "M9 6l6 6-6 6";

function chevron() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", "18"); svg.setAttribute("height", "18"); svg.setAttribute("class", "chev");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  for (const [k, v] of Object.entries({d: CHEVRON, fill: "none", stroke: "currentColor", "stroke-width": "1.75", "stroke-linecap": "round", "stroke-linejoin": "round"})) path.setAttribute(k, v);
  svg.append(path);
  return svg;
}

function dot(level) { return h("span", {class: `dot ${level || ""}`, "aria-hidden": "true"}); }

function renderVerdict(d) {
  document.getElementById("verdict").className = `verdict ${d.level}`;
  document.getElementById("v-sentence").textContent = d.verdict;
  renderNow(d);
  const failed = Object.entries(d.sources).filter(([, s]) => !s.ok).map(([n]) => SOURCE_LABEL[n] || n);
  const age = `dane sprzed ${ago(Date.parse(d.generated_at) / 1000).replace(" temu", "")}`;
  document.getElementById("v-age").textContent = failed.length ? `${age} | brak danych: ${failed.join(", ")}` : age;
}

function renderNow(d) {
  const box = document.getElementById("v-now");
  box.hidden = !d.next_action;
  if (!d.next_action) return;
  document.getElementById("v-now-text").textContent = d.next_action.text;
  document.getElementById("v-now-link").setAttribute("href", d.next_action.link);
}

function renderNeeds(d) {
  const list = document.getElementById("needs");
  list.replaceChildren();
  if (!d.needs_me.length) list.append(h("li", {class: "empty"}, "Nic nie wymaga Twojej uwagi."));
  for (const item of d.needs_me) {
    const where = [item.project, ago(item.since)].filter(Boolean).join(", ");
    list.append(h("li", {}, h("a", {class: "row", href: item.link}, dot(item.kind === "review" || item.kind === "feedby_decision" ? "warn" : "bad"),
      h("div", {class: "main"}, h("b", {}, item.what), h("small", {}, `${KIND_LABEL[item.kind]}, ${where}`)), chevron())));
  }
  const rest = d.needs_me_total - d.needs_me.length;
  if (rest > 0) list.append(h("li", {class: "more"}, `+ ${rest} więcej`));
}

function projectState(p) {
  if (p.autocheck && p.autocheck !== "ok") return ["bad", `Przepływy: ${FLOW_LABEL[p.autocheck] || "do sprawdzenia"}`];
  if (p.blockers) return ["bad", `Zablokowane: ${p.blockers}`];
  if (p.review_count) return ["warn", `Do przeglądu: ${p.review_count}`];
  if (p.charter && p.charter.status === "draft") return ["warn", "Szkic chartera"];
  if (p.charter_known && !p.charter) return ["warn", "Brak chartera"];
  return ["ok", p.last_commit ? `Zmiana ${ago(p.last_activity)}` : "Brak zmian"];
}

function projectCard(p, [level], insight) {
  const goal = !p.charter_known ? h("div", {class: "goal nodata"}, "brak danych: chartery")
    : h("div", {class: "goal"}, p.charter ? (p.charter.goal || "brak celu") : "brak chartera");
  const kind = p.charter ? (TYPE_LABEL[p.charter.type] || "bez typu") : "";
  return h("a", {class: "tile", href: p.link}, h("div", {class: "state"}, dot(level), h("h3", {title: p.title}, p.title)),
    h("div", {class: "insight"}, insight), goal, h("div", {class: "kind"}, kind));
}

function projectRow(p, [level], insight) {
  return h("li", {}, h("a", {href: p.link, title: insight}, dot(level), h("span", {class: "txt"}, h("span", {class: "name"}, p.title), h("small", {}, insight))));
}

function renderProjects(d) {
  const box = document.getElementById("projects");
  const shown = d.projects.slice(0, MAX_TILES);
  document.getElementById("proj-count").textContent = `aktywne 7 dni: ${d.projects.length}${d.projects.length > MAX_TILES ? `, widać ${MAX_TILES}` : ""}`;
  const now = Date.now() / 1000;
  const topReview = Math.max(0, ...shown.map((p) => p.review_count));
  const withState = shown.map((p) => [p, projectState(p), projectInsight(p, now, topReview > 0 && p.review_count === topReview)]);
  const attention = withState.filter(([, st]) => st[0] !== "ok").slice(0, MAX_CARDS);
  const calm = withState.filter((x) => !attention.includes(x));
  box.replaceChildren(h("div", {class: "cards"}, attention.map(([p, st, ins]) => projectCard(p, st, ins))));
  if (calm.length) box.append(h("div", {class: "calm-title"}, "Pozostałe"), h("ul", {class: "calm"}, calm.map(([p, st, ins]) => projectRow(p, st, ins))));
}

function statRow(label, value, level, insight) {
  const shown = value === null ? "brak danych" : String(value);
  return h("li", {}, h("div", {class: "row"}, dot(value === null ? "warn" : level),
    h("div", {class: "main"}, label, insight ? h("small", {class: "ins"}, insight) : null),
    h("span", {class: `val${value === null ? " nodata" : ""}`}, shown)));
}

function renderMachines(d) {
  const m = d.machines;
  const s = m.sessions;
  const failed = s ? s.failed + s.lost : null;
  const tip = machineInsights(m, Date.now() / 1000);
  const box = document.getElementById("machines");
  box.replaceChildren(
    statRow("Sesje w toku", s ? s.running : null, "ok", tip.running),
    statRow("Sesje do przeglądu", s ? s.review : null, s && s.review ? "warn" : "ok", tip.review),
    statRow("Sesje nieudane", failed, failed ? "bad" : "ok", tip.failed),
    statRow("Crony z błędem 24 h", m.cron_failed_24h, m.cron_failed_24h ? "bad" : "ok", tip.cron),
    statRow("Zablokowane karty", m.blocked_cards, m.blocked_cards ? "bad" : "ok", tip.cards),
    ...nodeRows(m));
}

function nodeRows(m) {
  if (!m.nodes) return [statRow("Maszyny", null, "warn", "Brak danych o maszynach.")];
  return m.nodes.map((n) => h("li", {}, h("div", {class: "row"}, dot(n.online ? "ok" : "bad"),
    h("div", {class: "main"}, n.name, h("small", {class: "ins"}, nodeInsight(n, m))), h("span", {class: "val"}, n.online ? "online" : "offline"))));
}

function renderSources(d) {
  const box = document.getElementById("sources");
  box.replaceChildren();
  for (const [name, s] of Object.entries(d.sources)) {
    const text = s.ok ? `${SOURCE_LABEL[name] || name}: ok` : `${SOURCE_LABEL[name] || name}: ${s.error}`;
    box.append(h("div", {class: s.ok ? "" : "err"}, text));
  }
}

function renderCharters(d) {
  const c = d.charters;
  const text = `Chartery: ${c.draft} do zatwierdzenia, ${c.approved} zatwierdzonych`;
  document.getElementById("charters-text").textContent = d.sources.charters.ok ? text : d.sources.charters.error;
  document.getElementById("charters-open").hidden = !c.draft;
}

function render(d) {
  wall = d;
  renderVerdict(d); renderNeeds(d); renderProjects(d); renderMachines(d); renderSources(d); renderCharters(d);
  if (window.WallReview) window.WallReview.update(d.charters.drafts);
}

async function load() {
  try {
    const res = await fetch("/api/mc/wall", {cache: "no-store"});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch (err) {
    document.getElementById("v-sentence").textContent = `brak danych: ${err.message}`;
    document.getElementById("verdict").className = "verdict bad";
  }
  countdown = REFRESH_S;
}

setInterval(() => {
  countdown -= 1;
  document.getElementById("v-tick").textContent = `${countdown} s`;
  if (countdown <= 0) load();
}, 1000);
load();
