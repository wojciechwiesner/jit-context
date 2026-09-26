"use strict";
/* Benchmark mode: GAIA cognitive run. Data: /api/snapshot + /api/stream (run.log). */
let runId = params.get("run") || "";
let snap = null, es = null, hideSpill = true, streamRun = null;
const term = makeTerm(2500);
const STAGE_LABEL = {sensory: "SENSORY", plan: "META-PLAN", ego: "EGO", tools: "TOOLS", guard: "LOOP GUARD", sumienie: "CONSCIENCE", rozwaga: "DELIBERATION", fidelity: "FIDELITY", memory: "MEMORY", result: "RESULT"};
const PIPE = [
  ["sensory", 60, 50], ["plan", 170, 50], ["ego", 280, 50], ["tools", 390, 50], ["guard", 500, 50],
  ["sumienie", 500, 140], ["rozwaga", 390, 140], ["fidelity", 280, 140], ["memory", 170, 140], ["result", 60, 140],
];
$("picker-name").textContent = "run";

function drawPipe(cur) {
  const seen = new Set(cur?.stages_seen || []);
  const active = cur && !cur.done ? cur.stage : cur?.done ? "result" : null;
  const pos = Object.fromEntries(PIPE.map(([k, x, y]) => [k, [x, y]]));
  let edges = "", flows = "", nodes = "";
  for (let i = 0; i < PIPE.length - 1; i++) {
    const [a, ax, ay] = PIPE[i], [b, bx, by] = PIPE[i + 1];
    const d = ay === by ? `M${ax + (bx > ax ? 46 : -46)} ${ay} L${bx + (bx > ax ? -46 : 46)} ${by}` : `M${ax + 46} ${ay} C${ax + 90} ${ay} ${bx + 90} ${by} ${bx + 46} ${by}`;
    edges += `<path class="edge ${seen.has(a) && seen.has(b) ? "on" : ""}" d="${d}"/>`;
    if (b === active && seen.has(a)) flows += `<path class="flow" d="${d}"/>`;
  }
  const [tx, ty] = pos.tools, [ex] = pos.ego;  // ego <-> tools back-edge: the inner tool loop
  const loop = `M${tx} ${ty - 16} C${tx} ${ty - 40} ${ex} ${ty - 40} ${ex} ${ty - 16}`;
  edges += `<path class="edge ${seen.has("tools") ? "on" : ""}" d="${loop}" stroke-dasharray="3 4"/>`;
  if (active === "tools") flows += `<path class="flow" d="${loop}"/>`;
  for (const [k, x, y] of PIPE) {
    const cls = k === active ? "active" : seen.has(k) ? "seen" : "";
    nodes += `<g class="node ${cls}"><rect x="${x - 46}" y="${y - 16}" width="92" height="32" rx="9"/><text x="${x}" y="${y + 3.5}">${STAGE_LABEL[k]}</text></g>`;
  }
  $("pipe").innerHTML = `<defs><filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>${edges}${flows}${nodes}` +
    `<text x="560" y="96" fill="#7d8496" font-family="monospace" font-size="9" text-anchor="end">ego ⇄ tools loop (max 15 turns)</text>`;
}

function renderScore(r) {
  $("s-clean").textContent = r.done ? pct(r.clean, r.done).toFixed(1) + "%" : "-";
  $("s-done").textContent = `${r.done} / ${r.total}`;
  $("s-cleann").textContent = `${r.clean} · ${pct(r.clean, r.done).toFixed(1)}%`;
  $("s-ver").textContent = `${r.verified} · ${pct(r.verified, r.done).toFixed(1)}%`;
  $("s-fail").textContent = r.done - r.clean;
  $("s-avg").textContent = fmtDur(r.avg_s);
  $("s-apierr").textContent = r.api_errors;
  ring("r-clean", 66, r.done ? r.clean / r.done : 0);
  ring("r-ver", 52, r.done ? r.verified / r.done : 0);
  ring("r-prog", 38, r.total ? r.done / r.total : 0);
  $("src-res").textContent = `${r.run_id} · commit ${r.provenance?.git_commit || "-"}`;
  $("levels").innerHTML = ["1", "2", "3"].map((l) => {
    const v = r.per_level[l]; if (!v || !v.planned) return "";
    return `<div class="lvrow"><b>L${l}</b><div class="bar"><b style="width:${pct(v.done, v.planned)}%;background:#232a38"></b><b style="width:${pct(v.clean, v.planned)}%;background:#2f8f5c"></b><b style="width:${pct(v.verified, v.planned)}%;background:var(--grn)"></b></div><span style="color:var(--mut);text-align:right">${v.clean}/${v.done}<span style="color:var(--dim)"> of ${v.planned}</span></span></div>`;
  }).join("");
  const T = r.tasks, n = T.length;
  if (!n) { $("traj").innerHTML = ""; return; }
  let c = 0, v = 0, bars = "";
  const cl = [], vl = [], mxD = Math.max(...T.map((t) => t.duration)) || 1;
  T.forEach((t, i) => {
    c += t.verdict !== "fail"; v += t.verdict === "verified";
    const x = n === 1 ? 150 : (i * 300) / (n - 1);
    cl.push(`${x.toFixed(1)},${(88 - (c / (i + 1)) * 84).toFixed(1)}`);
    vl.push(`${x.toFixed(1)},${(88 - (v / (i + 1)) * 84).toFixed(1)}`);
    const h = (t.duration / mxD) * 40, w = Math.max(1, 300 / n - 1);
    bars += `<rect x="${((i * 300) / n).toFixed(1)}" y="${92 - h}" width="${w.toFixed(1)}" height="${h}" fill="${t.verdict === "fail" ? "#7f1d1d88" : "#2a3040"}"/>`;
  });
  $("traj").innerHTML = `${bars}<line x1="0" x2="300" y1="46" y2="46" stroke="#1d222c" stroke-dasharray="2 3"/><polyline points="${cl.join(" ")}" fill="none" stroke="#86efac" stroke-width="1.5" vector-effect="non-scaling-stroke"/><polyline points="${vl.join(" ")}" fill="none" stroke="#4ade80" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
}

function renderCurrent(r) {
  const cur = r.current;
  drawPipe(r.finished ? null : cur);
  $("src-cur").textContent = r.run_id + "/run.log";
  if (!cur) return;
  const lvl = (r.plan.find((p) => p.id.startsWith(cur.task_id)) || {}).level || "?";
  $("c-idx").textContent = `${cur.index}/${cur.total}`;
  $("c-id").textContent = cur.task_id;
  $("c-lvl").textContent = "L" + lvl;
  $("c-stage").textContent = r.finished ? "done" : STAGE_LABEL[cur.stage] || cur.stage;
  $("c-q").textContent = cur.question;
  $("c-turn").textContent = cur.turns;
  $("c-turns").innerHTML = Array.from({length: 15}, (_, i) => `<i class="${i < cur.turns ? (i >= 13 ? "x" : i >= 11 ? "w" : "u") : ""}"></i>`).join("");
}

function renderMatrix(r) {
  const byId = Object.fromEntries(r.tasks.map((t) => [t.id, t]));
  const cur = r.current, curId = cur && !cur.done && !r.finished ? cur.task_id : null;
  $("matrix").innerHTML = r.plan.map((p, i) => {
    const t = byId[p.id];
    const cls = t ? t.verdict : curId && p.id.startsWith(curId) ? "cur" : "l" + p.level;
    return `<div class="cell ${cls} ${t && t.file ? "f" : ""}" data-i="${i}"></div>`;
  }).join("");
  $("src-plan").textContent = `${r.plan.length} tasks · L1 ${r.per_level["1"].planned} · L2 ${r.per_level["2"].planned} · L3 ${r.per_level["3"].planned}`;
  const reasonColor = (k) => (k === "GATE_PASSED" ? "var(--grn)" : k.includes("FORCED") ? "var(--amb)" : "var(--red)");
  hbars("gates", Object.entries(r.reasons).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k.replace("GATE_", "").replace("FORCED_BY_BUDGET", "budget").replace("UNGROUNDED", "ungrounded").toLowerCase(), v, reasonColor(k)]), "var(--cyan)", r.done);
  hbars("tools", Object.entries(r.tools).sort((a, b) => b[1] - a[1]).slice(0, 7), "var(--blu)");
}

function renderCognition(r, jev) {
  $("duel").innerHTML = r.rozwaga.slice(-6).reverse().map((d) =>
    `<div><span class="${d.choice === 0 ? "win" : ""}" title="${esc(d.a)}">${esc(d.a)}</span><em>vs</em><span class="${d.choice === 1 ? "win" : ""}" title="${esc(d.b)}">${esc(d.b)}</span><small>${esc(d.method)}</small></div>`,
  ).join("") || `<div class="note">none yet – deliberation only fires when the conscience gate does not verify</div>`;
  hbars("guards", [["nudge", r.guards.nudge || 0, "var(--amb)"], ["force_answer", r.guards.force_answer || 0, "var(--red)"]], "var(--amb)");
  hbars("mem", Object.entries(r.memory?.outcomes || {}).map(([k, v]) => [k.toLowerCase(), v, k === "VERIFIED" ? "var(--grn)" : "var(--red)"]), "var(--grn)");
  if (jev?.available) {
    hbars("jev", Object.entries(jev.scores || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, +v.toFixed(2), "var(--vio)"]), "var(--vio)", 1);
    $("jev-meta").textContent = `${jev.model} · HTTP ${jev.http_status} · ${Math.round(jev.latency_ms)} ms · ${jev.fallback_used ? "fallback" : "remote"} · ${fmtDur(jev.age_s)} ago`;
  } else {
    $("jev").innerHTML = `<div class="note">no JEV report</div>`;
  }
}

function render(s) {
  snap = s;
  const r = s.run;
  fillSelect($("picker"), s.runs, r?.run_id, (x) => x.id);
  renderStrip(s.hermes_sessions || [], s.live_runs, {run: r?.run_id});
  if (!r) { setStatus("stale", "NO RUNS"); return; }
  if (r.run_id !== streamRun) connect(r.run_id);
  const stalled = !r.finished && r.log_age_s > 600;
  setStatus(r.finished ? "done" : stalled ? "stale" : "live", r.finished ? "FINISHED" : stalled ? "STALLED" : "LIVE");
  $("hmeta").innerHTML = `<span>worker <b>${esc(r.worker || r.provenance?.worker_model || "-")}</b></span><span>mode <b>${esc(r.mode || "-")}</b></span>` +
    `<span>elapsed <b>${fmtDur(r.elapsed_s)}</b></span><span>eta <b>${r.finished ? "0" : fmtDur(r.eta_s)}</b></span><span>last write <b>${fmtDur(r.log_age_s)} ago</b></span>`;
  renderScore(r);
  renderCurrent(r);
  renderMatrix(r);
  renderCognition(r, s.jev);
  renderJit(s.jit, "no JIT telemetry");
  if (s.jit?.available) $("src-jit").textContent = `session ${s.jit.session} · ${fmtDur(s.jit.db_age_s)} ago`;
}

$("matrix").addEventListener("mousemove", (e) => {
  const c = e.target.closest(".cell"), tip = $("tip");
  if (!c || !snap?.run) { tip.style.display = "none"; return; }
  const p = snap.run.plan[+c.dataset.i], t = snap.run.tasks.find((x) => x.id === p.id);
  tip.innerHTML = t
    ? `<b>#${+c.dataset.i + 1} · L${esc(t.level)} · ${esc(t.verdict.toUpperCase())}</b><br>${esc(t.question)}<br><br>answer: <b>${esc(t.answer)}</b><br>truth: ${esc(t.gt)}<br>${esc(t.gate)} · ${esc(t.reason)}<br>${t.duration}s · ${t.tools} tool calls${t.forced ? " · forced" : ""}${t.rozwaga ? " · deliberation" : ""}`
    : `<b>#${+c.dataset.i + 1} · L${esc(p.level)}</b> · ${esc(p.id.slice(0, 8))}<br>pending`;
  tip.style.display = "block";
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 380) + "px";
  tip.style.top = Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 10) + "px";
});
$("matrix").addEventListener("mouseleave", () => { $("tip").style.display = "none"; });

function classify(raw) {
  // Runner log tags are Polish domain names; display them in English without touching the raw log.
  const l = (hideSpill ? raw.replace(/ \(spill: [^)]*\)/, "") : raw)
    .replace("[Rozwaga]", "[Deliberation]").replace("[Sumienie Gate]", "[Conscience Gate]").replace("Sumienie ", "Conscience ");
  if (/^=+$/.test(l.trim())) return line("sep", "");
  if (l.includes("COGNITIVE TASK") || l.startsWith("Starting ")) return line("hd", esc(l));
  if (l.includes("--> RESULT: [VERIFIED_PASS]") || l.includes("--> RESULT: [CLEAN_PASS]")) return line("ok", esc(l));
  if (l.includes("--> RESULT: [FAIL]")) return line("bad", esc(l));
  if (/API error|Traceback|Error:/.test(l)) return line("err", esc(l));
  if (l.includes("Loop Guard")) return line("guard", esc(l));
  if (l.includes("[Deliberation]")) return line("roz", esc(l));
  if (l.includes("Conscience") || l.includes("Gate:") || l.includes("Fidelity")) return line("gate", esc(l));
  if (l.includes("[Experience Ingest]")) return line("mem", esc(l));
  if (/^Q: |^GT: /.test(l)) return line("q", esc(l));
  const m = l.match(/^(\s*\[Turn \d+\] Tool: )(\w+)(.*)$/);
  if (m) return line("tool", esc(m[1]) + "<em>" + esc(m[2]) + "</em>" + esc(m[3]));
  return line("", esc(l));
}
function connect(forRun) {
  if (es) es.close();
  streamRun = forRun || runId || null;
  $("t-state").textContent = "connecting…";
  es = new EventSource("/api/stream" + (streamRun ? "?run=" + encodeURIComponent(streamRun) : ""));
  es.addEventListener("reset", (e) => { const d = JSON.parse(e.data); streamRun = d.run; term.clear(); term.append(d.lines.map(classify)); $("t-state").textContent = `streaming · ${d.run}`; $("src-log").textContent = `SSE · ${d.run}/run.log`; });
  es.addEventListener("lines", (e) => { term.append(JSON.parse(e.data).lines.map(classify)); $("t-state").textContent = "live · " + new Date().toLocaleTimeString("en-GB"); });
  es.onerror = () => { $("t-state").textContent = "disconnected – retrying"; };
}
$("t-compact").onclick = () => { hideSpill = !hideSpill; $("t-compact").textContent = "spill paths: " + (hideSpill ? "hidden" : "shown"); connect(streamRun); };
$("picker").onchange = (e) => { runId = e.target.value; setUrl("run", runId); connect(runId); poll(); };

async function poll() {
  try {
    const res = await fetch("/api/snapshot" + (runId ? "?run=" + encodeURIComponent(runId) : ""), {cache: "no-store"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.status);
    showError("");
    render(data);
  } catch (err) { showError("snapshot: " + err.message); }
}
drawPipe(null);
connect();
poll();
setInterval(poll, 3000);
