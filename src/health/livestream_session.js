"use strict";
/* Session mode: live view of any Hermes session (normal tasks). Data: /api/session + /api/session/stream (state.db). */
let sessionId = params.get("session") || "";
let showResults = true, es = null, streamSid = null;
const term = makeTerm(3000);
const TOOL_COLORS = ["#5eead4", "#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#4ade80", "#fb923c", "#38bdf8", "#c084fc", "#94a3b8"];
const toolColor = (() => { const m = {}; let i = 0; return (t) => (t === "user" ? "#f472b6" : (m[t] ??= TOOL_COLORS[i++ % TOOL_COLORS.length])); })();
toolColor("user");

/* ---- orbit: the agent as a star, tools as planets sized by usage, recent calls as comets ---- */
function drawOrbit(st) {
  const tools = Object.entries(st.tools).slice(0, 10);
  const cx = 300, cy = 108, rx = 232, ry = 78;
  const total = tools.reduce((a, [, v]) => a + v, 0) || 1;
  const recent = st.timeline.slice(-28).filter((t) => t.tool !== "user");
  const lastTool = recent.length ? recent[recent.length - 1].tool : null;
  let planets = "", comets = "";
  const pos = {};
  tools.forEach(([name, v], i) => {
    const ang = (i / tools.length) * Math.PI * 2 - Math.PI / 2;  // evenly spaced on one ellipse: no collisions
    const x = cx + Math.cos(ang) * rx, y = cy + Math.sin(ang) * ry;
    const r = 4 + Math.sqrt(v / total) * 17, c = toolColor(name), hot = name === lastTool;
    pos[name] = [x, y, r];
    const below = Math.sin(ang) >= -0.2, ly = below ? y + r + 13 : y - r - 7;
    planets += `<g><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(r + 7).toFixed(1)}" fill="${c}" opacity="${hot ? 0.25 : 0.06}"/>` +
      `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${c}" opacity="${hot ? 1 : 0.8}" ${hot ? 'filter="url(#glow2)"' : ""}/>` +
      `<text x="${x.toFixed(1)}" y="${ly.toFixed(1)}" fill="${hot ? "#fff" : "#9aa3b5"}" stroke="#0c0e12" stroke-width="3" paint-order="stroke" font-family="monospace" font-size="9.5" text-anchor="middle">${esc(name)} <tspan fill="#5d6475">${v}</tspan></text></g>`;
  });
  recent.forEach((t, i) => {
    const p = pos[t.tool]; if (!p) return;
    const [x, y, r] = p, d = Math.hypot(x - cx, y - cy) || 1;
    const ex = x - ((x - cx) / d) * (r + 2), ey = y - ((y - cy) / d) * (r + 2);  // stop at the planet rim
    const bend = (i % 2 ? 1 : -1) * 18;
    const mx = (cx + ex) / 2 - ((ey - cy) / d) * bend, my = (cy + ey) / 2 + ((ex - cx) / d) * bend;
    const newest = i === recent.length - 1;
    comets += `<path d="M${cx} ${cy} Q${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}" fill="none" stroke="${toolColor(t.tool)}" stroke-opacity="${(0.06 + (i / recent.length) * 0.55).toFixed(2)}" stroke-width="${newest ? 2 : 1}" ${newest && st.live ? 'class="flow"' : ""}/>`;
  });
  const core = st.live ? "#5eead4" : "#4a5061";
  $("orbit").innerHTML = `<defs><radialGradient id="star"><stop offset="0" stop-color="${core}" stop-opacity=".85"/><stop offset="1" stop-color="${core}" stop-opacity="0"/></radialGradient><filter id="glow2" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>` +
    `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="none" stroke="#1a1f29" stroke-dasharray="2 5"/><ellipse cx="${cx}" cy="${cy}" rx="${rx * 0.45}" ry="${ry * 0.45}" fill="none" stroke="#141820" stroke-dasharray="2 6"/>` +
    `${comets}<circle cx="${cx}" cy="${cy}" r="30" fill="url(#star)"/><circle cx="${cx}" cy="${cy}" r="9" fill="${core}" ${st.live ? 'class="core-beat"' : ""}/>` +
    `<text x="${cx}" y="${cy + 4}" dy="24" fill="#e7e9ee" stroke="#0c0e12" stroke-width="4" paint-order="stroke" font-family="monospace" font-size="10" font-weight="700" text-anchor="middle">${esc((st.meta.model || "agent").slice(0, 22))}</text>${planets}`;
  $("src-orbit").textContent = `${total} tool calls · ${tools.length} tools · comets = last ${recent.length} calls`;
}

/* ---- rhythm: one tick per event across the session timeline, prompts as tall pink bars ---- */
function drawRhythm(st) {
  const tl = st.timeline; if (!tl.length) { $("rhythm").innerHTML = ""; return; }
  const t0 = tl[0].ts, t1 = Math.max(tl[tl.length - 1].ts, t0 + 1);
  let ticks = "";
  for (const e of tl) {
    const x = ((e.ts - t0) / (t1 - t0)) * 598 + 1;
    ticks += e.tool === "user"
      ? `<rect x="${x.toFixed(1)}" y="2" width="2" height="60" fill="#f472b6" opacity=".9"/>`
      : `<rect x="${x.toFixed(1)}" y="22" width="1.2" height="36" fill="${toolColor(e.tool)}" opacity=".7"/>`;
  }
  $("rhythm").innerHTML = `<line x1="0" x2="600" y1="58" y2="58" stroke="#1d222c"/>${ticks}`;
  const seen = [...new Set(tl.map((e) => e.tool))].slice(0, 6);
  $("rhythm-legend").innerHTML = seen.map((t) => `<span><i style="background:${toolColor(t)}"></i>${esc(t)}</span>`).join("") +
    `<span style="margin-left:auto">${clock(t0)} → ${clock(t1)}</span>`;
}

/* ---- per-turn JIT: capsule tokens (bars) vs hook latency (line), one column per user turn ---- */
function drawTurns(j) {
  const el = $("turns");
  if (!(j && j.available && j.turns.length)) { el.innerHTML = ""; $("turns-legend").textContent = ""; return; }
  const T = j.turns, n = T.length, w = 600 / n;
  const mxCap = Math.max(...T.map((t) => t.capsule_tokens_est || 0), 1), mxMs = Math.max(...T.map((t) => t.hook_total_ms || 0), 1);
  let bars = "", pts = [];
  T.forEach((t, i) => {
    const h = ((t.capsule_tokens_est || 0) / mxCap) * 64, x = i * w;
    bars += `<rect x="${(x + 1).toFixed(1)}" y="${(70 - h).toFixed(1)}" width="${Math.max(1, w - 2).toFixed(1)}" height="${h.toFixed(1)}" rx="1.5" fill="${t.l2_triggered ? "#a78bfa" : "#5eead4"}" opacity="${t.degraded ? 0.35 : 0.75}"/>`;
    pts.push(`${(x + w / 2).toFixed(1)},${(70 - ((t.hook_total_ms || 0) / mxMs) * 60).toFixed(1)}`);
  });
  el.innerHTML = `${bars}<polyline points="${pts.join(" ")}" fill="none" stroke="#fbbf24" stroke-width="1.4" vector-effect="non-scaling-stroke"/>`;
  $("turns-legend").innerHTML = `<span><i style="background:#5eead4"></i>capsule tokens</span><span><i style="background:#a78bfa"></i>turn with L2</span><span><i style="background:#fbbf24"></i>hook latency (max ${fmtK(mxMs)} ms)</span><span style="margin-left:auto">max ${fmtK(mxCap)} tok</span>`;
}

/* ---- autochecker: per-turn score bars, alignment chain of the last turn, jitjevmods backlog ---- */
function renderAudit(a) {
  const turns = (a && a.turns) || [], mods = (a && a.mods) || [];
  const color = (s) => (s >= 85 ? "#4ade80" : s >= 60 ? "#fbbf24" : "#f87171");
  $("a-scores").innerHTML = turns.map((t, i) =>
    `<i class="${i === turns.length - 1 ? "last" : ""}" style="height:${Math.max(6, t.score)}%;background:${color(t.score)}" title="${esc(t.turn)} · score ${t.score} · ${t.findings.map((f) => f.key).join(", ") || "clean"}"></i>`,
  ).join("") || `<div class="note" style="margin:0">no audited turns yet – the checker runs after each finished turn</div>`;
  const last = turns[turns.length - 1];
  if (last) {
    const c = last.chain, row = (k, v, missing) => `<span>${k}</span><b class="${v ? "" : "miss"}" title="${esc(v)}">${esc(v || missing)}</b>`;
    $("a-chain").innerHTML =
      row("project", c.project_goal, "no Active Goal in STATE.md") + row("prompt", c.prompt, "-") +
      row("capsule", c.capsule_goal, c.capsule_retained ? "no goal in capsule" : "not retained (backfill)") +
      row("spec", c.spec, "no spec / criteria") + row("output", c.output, "-") +
      `<span>harness</span><b>${last.harness.tool_calls} calls · ${last.harness.errors} errors · ${fmtDur(last.harness.duration_s)} · score ${last.score}</b>` +
      `<span></span><div class="findings">${last.findings.map((f) => `<span class="sev ${esc(f.severity)}" title="${esc(f.evidence)}">${esc(f.key)}</span>`).join("") || `<span class="sev done">clean</span>`}</div>`;
    $("src-audit").textContent = `${turns.length} turns · last ${clock(last.ts)}`;
  } else {
    $("a-chain").innerHTML = "";
    $("src-audit").textContent = "no audits for this session";
  }
  $("a-open").textContent = `${a ? a.open : 0} open`;
  $("a-mods").innerHTML = mods.slice(0, 8).map((m) =>
    `<div class="mod" title="${esc(m.proposal)}"><span class="sev ${m.status === "open" ? esc(m.severity) : "done"}">${esc(m.status === "open" ? m.severity : m.status)}</span><b>${esc(m.title)}</b><em>${m.count}x</em></div>`,
  ).join("") || `<div class="note" style="margin:0">backlog empty</div>`;
  $("a-path").textContent = a ? a.mods_path.replace(/^\/Users\/[^/]+/, "~") : "";
}

function render(d) {
  const st = d.session;
  fillSelect($("picker"), st.sessions || [], st.id, (s) => `${s.project || s.source} · ${s.id}`);
  renderStrip(st.sessions || [], d.live_runs || [], {session: st.id});
  if (!st.available) { setStatus("stale", "NO SESSIONS"); return; }
  if (st.id !== streamSid) connect(st.id);
  const m = st.meta;
  setStatus(st.live ? "live" : m.ended_at ? "done" : "stale", st.live ? "LIVE" : m.ended_at ? "ENDED" : "IDLE");
  $("hmeta").innerHTML = `<span>session <b>${esc(st.id)}</b></span><span>elapsed <b>${fmtDur(st.elapsed_s)}</b></span><span>last activity <b>${fmtDur(st.idle_s)} ago</b></span>`;
  $("s-goal").textContent = st.goal || "-";
  $("s-id").textContent = st.id;
  $("s-proj").textContent = m.cwd ? m.cwd.split("/").pop() : "-";
  $("s-model").textContent = m.model || "-";
  $("s-branch").textContent = m.git_branch || "-";
  $("s-msgs").textContent = m.message_count ?? "-";
  $("s-calls").textContent = m.tool_call_count ?? "-";
  $("s-api").textContent = m.api_call_count ?? "-";
  $("s-tok").textContent = `${fmtK(m.input_tokens)} / ${fmtK(m.output_tokens)}`;
  $("s-cache").textContent = fmtK(m.cache_read_tokens);
  $("s-act").textContent = m.last_activity_description || (st.live ? "working" : "-");
  $("src-meta").textContent = `${m.source || "-"} · started ${m.started_at ? clock(m.started_at) : "-"}`;
  drawOrbit(st);
  drawRhythm(st);
  const root = (m.cwd || "").replace(/\/$/, "") + "/", home = "/Users/" + ((m.cwd || "").split("/")[2] || "") + "/";
  const short = (p) => (p.startsWith(root) ? p.slice(root.length) : p.startsWith(home) ? "~/" + p.slice(home.length) : p.replace(/^~\//, "~/"));
  $("files").innerHTML = st.files.slice(0, 6).map((f) => `<div><span title="${esc(f.path)}">${esc(short(f.path))}</span><em>${f.reads}r · <b>${f.writes}w</b></em></div>`).join("") || `<div class="note">no file tools yet</div>`;
  hbars("tools", Object.entries(st.tools).slice(0, 4).map(([k, v]) => [k, v, toolColor(k)]), "var(--blu)");
  renderJit(d.jit, "no JIT telemetry for this session");
  drawTurns(d.jit);
  renderAudit(d.audit);
  $("jit-note").textContent = d.jit && d.jit.available
    ? `overlay ${d.jit.session} · ${d.jit.overlay_active} active overlay facts · degraded turns ${d.jit.agg.degraded || 0}`
    : "JIT hooks did not record turn telemetry for this session (plugin off, cron/gateway session, or no turns yet).";
}

/* ---- terminal feed from state.db ---- */
function feedNode(it) {
  const ts = `<span class="ts">${clock(it.ts)}</span>`;
  if (it.kind === "user") return line("user", `${ts}<b>you</b>  ${esc(it.text)}`);
  if (it.kind === "say") return line("say", `${ts}${esc(it.text)}`);
  if (it.kind === "call") return line("call", `${ts}<span style="color:${toolColor(it.tool)}">▸</span> <em>${esc(it.tool)}</em>  ${esc(it.text)}`);
  if (!showResults) return null;
  return line("result" + (it.ok ? "" : " bad"), `↳ ${esc(it.tool)} · ${fmtK(it.chars)} chars  ${esc(it.text)}`);
}
function connect(sid) {
  if (es) es.close();
  streamSid = sid;
  $("t-state").textContent = "connecting…";
  es = new EventSource("/api/session/stream?session=" + encodeURIComponent(sid));
  const push = (items) => term.append(items.map(feedNode).filter(Boolean));
  es.addEventListener("reset", (e) => { const d = JSON.parse(e.data); term.clear(); push(d.items); $("t-state").textContent = `streaming · ${d.session}`; $("src-log").textContent = `SSE · state.db · ${d.session}`; });
  es.addEventListener("items", (e) => { push(JSON.parse(e.data).items); $("t-state").textContent = "live · " + new Date().toLocaleTimeString("en-GB"); });
  es.onerror = () => { $("t-state").textContent = "disconnected – retrying"; };
}
$("t-results").onclick = () => { showResults = !showResults; $("t-results").textContent = "results: " + (showResults ? "shown" : "hidden"); connect(streamSid); };
$("picker").onchange = (e) => { sessionId = e.target.value; setUrl("session", sessionId); connect(sessionId); poll(); };

async function poll() {
  try {
    const res = await fetch("/api/session" + (sessionId ? "?session=" + encodeURIComponent(sessionId) : ""), {cache: "no-store"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.status);
    showError("");
    render(data);
  } catch (err) { showError("session: " + err.message); }
}
poll();
setInterval(poll, 3000);
