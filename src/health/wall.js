/* Operator Wall renderer. All text goes through textContent (no innerHTML), so source data cannot inject markup. */
const REFRESH_S = 60;
const MAX_TILES = 20;
const KIND_LABEL = {autocheck_edge: "Przepływ", cron_failed: "Cron", blocked_card: "Zablokowane", review: "Do przeglądu", lost_session: "Sesja", feedby_decision: "Decyzja"};
const TYPE_LABEL = {"client-delivery": "Klient", platform: "Infrastruktura", product: "Produkt", experiment: "Eksperyment", dormant: "Uśpiony"};
const FLOW_LABEL = {ok: "OK", degraded: "spowolnione", broken: "zepsute"};
const SOURCE_LABEL = {sessions: "sesje", cron: "cron", autocheck: "przepływy", kanban: "kanban", nodes: "maszyny", charters: "chartery", projects: "projekty"};
const OK_MARK = "M8 12.5l2.7 2.7L16 9.5";
const ALERT_MARK = "M12 7v6M12 16.5v.5";
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

function renderVerdict(d) {
  document.getElementById("verdict").className = `verdict ${d.level}`;
  document.getElementById("v-sentence").textContent = d.verdict;
  document.getElementById("v-mark").setAttribute("d", d.level === "ok" ? OK_MARK : ALERT_MARK);
  renderNow(d);
  const failed = Object.entries(d.sources).filter(([, s]) => !s.ok).map(([n]) => SOURCE_LABEL[n] || n);
  const age = `dane sprzed ${ago(Date.parse(d.generated_at) / 1000).replace(" temu", "")}`;
  document.getElementById("v-age").textContent = failed.length ? `${age} | brak danych: ${failed.join(", ")}` : age;
}

function renderNow(d) {
  const box = document.getElementById("v-now");
  box.hidden = !d.next_action;
  box.replaceChildren();
  if (!d.next_action) return;
  box.append("Teraz: ", h("a", {href: d.next_action.link}, d.next_action.text));
}

function renderNeeds(d) {
  const list = document.getElementById("needs");
  list.replaceChildren();
  if (!d.needs_me.length) list.append(h("li", {class: "empty"}, "Nic nie wymaga Twojej uwagi."));
  for (const item of d.needs_me) {
    const where = [item.project, ago(item.since)].filter(Boolean).join(" | ");
    list.append(h("li", {}, h("a", {class: `row k-${item.kind}`, href: item.link},
      h("b", {}, item.what), h("span", {}, `${KIND_LABEL[item.kind]} | ${where}`))));
  }
  const rest = d.needs_me_total - d.needs_me.length;
  if (rest > 0) list.append(h("li", {class: "more"}, `+ ${rest} więcej`));
}

function tileBody(p) {
  if (!p.charter_known) return [h("div", {class: "goal nodata"}, "brak danych: chartery")];
  if (!p.charter) return [h("div", {class: "goal none"}, "brak chartera")];
  return [h("div", {class: "goal"}, p.charter.goal || "brak celu")];
}

function tileHead(p) {
  const type = p.charter ? h("span", {class: "badge type"}, TYPE_LABEL[p.charter.type] || "bez typu") : null;
  return h("div", {class: "head"}, h("h3", {title: p.title}, p.title), type);
}

function tileMeta(p) {
  const change = p.last_commit ? `zmiana ${ago(p.last_activity)}` : "brak zmian";
  const meta = h("div", {class: "meta"});
  if (p.charter && p.charter.status === "draft") meta.append(h("span", {class: "badge"}, "szkic"));
  meta.append(h("span", {}, change));
  if (p.review_count) meta.append(h("span", {}, `do przeglądu: ${p.review_count}`));
  if (p.blockers) meta.append(h("span", {}, `zablokowane: ${p.blockers}`));
  if (p.autocheck) meta.append(h("span", {class: `badge ${p.autocheck === "ok" ? "ok" : "bad"}`}, `Przepływy: ${FLOW_LABEL[p.autocheck] || "do sprawdzenia"}`));
  for (const who of p.audience) meta.append(h("span", {class: "badge"}, who));
  return meta;
}

function renderProjects(d) {
  const box = document.getElementById("projects");
  box.replaceChildren();
  document.getElementById("proj-count").textContent = `aktywne 7 dni: ${d.projects.length}${d.projects.length > MAX_TILES ? `, widać ${MAX_TILES}` : ""}`;
  for (const p of d.projects.slice(0, MAX_TILES)) {
    const bad = p.autocheck && p.autocheck !== "ok";
    box.append(h("a", {class: `tile${bad ? " bad" : ""}`, href: p.link}, tileHead(p), ...tileBody(p), tileMeta(p)));
  }
}

function stat(label, value, cls) {
  const shown = value === null ? "brak danych" : String(value);
  return h("div", {class: "stat"}, h("span", {}, label), h("strong", {class: value === null ? "nodata" : cls}, shown));
}

function renderMachines(d) {
  const m = d.machines;
  const s = m.sessions;
  const box = document.getElementById("machines");
  box.replaceChildren(
    stat("Sesje w toku", s ? s.running : null, "good"),
    stat("Sesje do przeglądu", s ? s.review : null, ""),
    stat("Sesje nieudane", s ? s.failed + s.lost : null, s && s.failed + s.lost ? "bad" : "good"),
    stat("Crony z błędem 24 h", m.cron_failed_24h, m.cron_failed_24h ? "bad" : "good"),
    stat("Zablokowane karty", m.blocked_cards, m.blocked_cards ? "bad" : "good"),
    nodesBlock(m.nodes));
}

function nodesBlock(nodes) {
  if (!nodes) return h("div", {class: "nodes nodata"}, "Maszyny: brak danych");
  const online = nodes.filter((n) => n.online).length;
  return h("div", {class: "nodes"}, h("span", {}, `Maszyny online: ${online} / ${nodes.length}`),
    nodes.map((n) => h("span", {class: n.online ? "on" : "off"}, `${n.name}: ${n.online ? "online" : "offline"}`)));
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
