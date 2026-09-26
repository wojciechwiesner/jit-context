"use strict";
/* Shared helpers for the JIT Livestream panel (session + benchmark modes).
 * XSS policy: every string that originates from state.db / run.log / res.json / SQLite goes through esc()
 * before it reaches innerHTML; all other interpolated values are numbers computed here. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const pct = (a, b) => (b ? (100 * a) / b : 0);
const fmtK = (n) => (n == null ? "-" : n >= 1e6 ? (n / 1e6).toFixed(2) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n)));
function fmtDur(s) {
  if (s == null || isNaN(s)) return "-";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(x).padStart(2, "0")}s` : `${x}s`;
}
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString("en-GB");
const params = new URLSearchParams(location.search);

function setUrl(key, value) {
  const q = new URLSearchParams(location.search);
  value ? q.set(key, value) : q.delete(key);
  history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : ""));
}
function setStatus(kind, text) {
  const st = $("status");
  st.className = "pill " + kind;
  st.innerHTML = `<i></i>${esc(text)}`;
}
function showError(msg) {
  const e = $("err");
  e.style.display = msg ? "block" : "none";
  e.textContent = msg || "";
}
function ring(id, r, frac) {
  const c = 2 * Math.PI * r;
  $(id).setAttribute("stroke-dasharray", `${Math.max(0, Math.min(1, frac)) * c} ${c}`);
}
function spark(id, vals, color) {
  const el = $(id);
  if (!el) return;
  if (!vals.length) { el.innerHTML = ""; return; }
  const mx = Math.max(...vals) || 1, n = vals.length;
  const pts = vals.map((v, i) => `${(n === 1 ? 50 : (i * 100) / (n - 1)).toFixed(1)},${(32 - (v / mx) * 28).toFixed(1)}`).join(" ");
  el.innerHTML = `<polyline points="0,34 ${pts} 100,34" fill="${color}18" stroke="none"/><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>`;
}
function hbars(id, entries, color, total) {
  const mx = total || Math.max(1, ...entries.map((e) => e[1]));
  $(id).innerHTML = entries.map(([k, v, c]) =>
    `<div class="hb"><span title="${esc(k)}">${esc(k)}</span><div class="bar"><b style="width:${pct(v, mx)}%;background:${c || color}"></b></div><b>${v}</b></div>`,
  ).join("") || `<div class="note">no data yet</div>`;
}
function fillSelect(el, items, current, label) {
  const key = items.map((x) => x.id + (x.live ? "*" : "")).join();
  if (el.dataset.key !== key) {
    el.innerHTML = items.map((x) => `<option value="${esc(x.id)}">${x.live ? "● " : ""}${esc(label(x))}</option>`).join("");
    el.dataset.key = key;
  }
  if (current) el.value = current;
}

/* Shared JIT Context OS telemetry block (L0/L1/L2, capsule vs haystack). */
function renderJit(j, emptyText) {
  if (!(j && j.available && j.turns.length)) {
    for (const id of ["j-l0", "j-l1", "j-l2", "j-av"]) $(id).textContent = "-";
    $("j-av2").textContent = "";
    for (const id of ["sp-l0", "sp-l1", "sp-l2"]) spark(id, [], "#fff");
    $("f-hayv").textContent = $("f-capv").textContent = $("f-crv").textContent = "-";
    $("f-cap").style.width = $("f-cr").style.width = "0%";
    $("src-jit").textContent = (j && j.error) || emptyText;
    return;
  }
  const last = j.turns[j.turns.length - 1];
  $("j-l0").textContent = (last.l0_ms ?? 0).toFixed(2) + " ms";
  $("j-l1").textContent = (last.l1_ms ?? 0).toFixed(2) + " ms";
  $("j-l2").textContent = last.l2_triggered ? fmtK(last.l2_ms) + " ms" : "skipped";
  spark("sp-l0", j.turns.map((t) => t.l0_ms || 0), "#5eead4");
  spark("sp-l1", j.turns.map((t) => t.l1_ms || 0), "#60a5fa");
  spark("sp-l2", j.turns.map((t) => t.l2_ms || 0), "#a78bfa");
  $("j-av").textContent = fmtK(j.agg.avoided);
  $("j-av2").textContent = `${j.agg.n} turns · ${j.agg.cr}% avg`;
  const hay = last.haystack_tokens_est || 1, cap = last.capsule_tokens_est || 0;
  $("f-hayv").textContent = fmtK(hay);
  $("f-capv").textContent = fmtK(cap);
  $("f-cap").style.width = Math.max(1.2, pct(cap, hay)) + "%";
  $("f-cr").style.width = (last.compression_ratio || 0) + "%";
  $("f-crv").textContent = (last.compression_ratio || 0).toFixed(1) + "%";
  $("src-jit").textContent = `${j.turns.length} turns · last ${fmtDur(j.db_age_s)} ago`;
}

/* Concurrency strip: live Hermes sessions (link to session mode) + live benchmark runs. */
function renderStrip(sessions, runs, current) {
  const live = sessions.filter((s) => s.live);
  const ses = live.map((s) =>
    `<a class="chip ${s.id === current.session ? "on" : ""}" href="/live?session=${encodeURIComponent(s.id)}"><i></i><b>${esc(s.project || s.source)} · ${esc(s.id.slice(-6))}</b><span>${esc(s.title || s.model || "")} · ${s.tools} tools</span></a>`);
  const rs = runs.map((r) =>
    `<a class="chip bench ${r.id === current.run ? "on" : ""}" href="/?run=${encodeURIComponent(r.id)}"><i></i><b>${esc(r.id)}</b><span>${esc(r.worker || "-")} · ${r.done}/${r.total} · ${r.done ? pct(r.clean, r.done).toFixed(0) : "-"}%<div class="mini"><u style="width:${pct(r.done, r.total)}%"></u></div></span></a>`);
  $("strip").innerHTML =
    `<span class="lbl">${live.length} live session${live.length === 1 ? "" : "s"}</span>${ses.join("") || `<span class="note" style="margin:0">none active in the last 10 min</span>`}` +
    `<span class="divider"></span><span class="lbl">${runs.length} live benchmark${runs.length === 1 ? "" : "s"}</span>${rs.join("") || `<span class="note" style="margin:0">none</span>`}`;
}

/* Terminal pane with follow-mode, shared by both modes. */
function makeTerm(maxLines = 2500) {
  const term = $("term");
  let follow = true;
  term.addEventListener("scroll", () => {
    const atBottom = term.scrollHeight - term.scrollTop - term.clientHeight < 30;
    if (atBottom !== follow) { follow = atBottom; $("t-follow").textContent = "follow: " + (follow ? "on" : "off"); }
  });
  $("t-follow").onclick = () => { follow = true; term.scrollTop = term.scrollHeight; $("t-follow").textContent = "follow: on"; };
  return {
    clear() { term.innerHTML = ""; },
    append(nodes) {
      const frag = document.createDocumentFragment();
      nodes.forEach((n) => frag.appendChild(n));
      term.appendChild(frag);
      while (term.childElementCount > maxLines) term.firstElementChild.remove();
      if (follow) term.scrollTop = term.scrollHeight;
    },
  };
}
function line(cls, html) {
  const d = document.createElement("div");
  if (cls) d.className = cls;
  d.innerHTML = html || "&nbsp;";
  return d;
}
