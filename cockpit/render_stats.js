// "Statystyki" tab: measured usage (inline SVG bars), observational JIT on/off, last controlled A/B, suggestions.
// Input: data.stats = { path, data, missing, error } from ./stats. Missing values are shown as missing, never as 0.
const { esc } = require('./html');

const DAY_MS = 86400000;
const MAX_CHART_DAYS = 31;
const CHART = { width: 640, height: 150, padX: 8, top: 18, bottom: 22, gap: 2, minBar: 2, gapMark: 2 };
const PERCENT = 100;
const SEVERITY = { high: ['wysoki', 'pill-red'], medium: ['średni', 'pill-amber'], low: ['niski', ''] };
const EVIDENCE_KIND = { file: 'plik', command: 'polecenie', value: 'wartość' };
const COMPARE_METRICS = [['tokens_per_turn', 'Tokeny na turę', 'int'], ['cache_read_share', 'Udział cache-read', 'pct'],
  ['turns_per_session', 'Tury na sesję-dzień', 'dec'], ['tool_errors_per_session', 'Błędy narzędzi na sesję', 'dec']];
const AB_METRICS = [['total_tokens', 'Tokeny razem', 'int'], ['num_turns', 'Tury', 'dec'], ['wall_s', 'Czas [s]', 'dec'],
  ['cost_usd', 'Koszt [USD]', 'usd']];
const STYLE = '<style>.stats-grid{display:grid;gap:16px}.stats-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:10px 0}.stats-kpi{border:1px solid var(--border);border-radius:6px;padding:8px 10px}.stats-kpi strong{display:block;font-size:16px}.stats-kpi small{opacity:.75}.stats-chart{width:100%;height:auto}.stats-bar{fill:#9ab99f}.stats-gap{fill:#3a403c}.stats-axis{fill:#9aa59e;font-size:10px}.stats-table{width:100%;border-collapse:collapse;font-size:12px}.stats-table th,.stats-table td{text-align:left;padding:5px 6px;border-top:1px solid var(--border)}.stats-sugg{padding:10px 0;border-top:1px solid var(--border)}.stats-sugg:first-of-type{border-top:0}.stats-sugg ul{margin:4px 0 0 18px}.pill-red{color:#e0aaa1;background:#3a2624}</style>';

function isNum(v) { return typeof v === 'number' && Number.isFinite(v); }
function fmt(value, kind = 'int') {
  if (!isNum(value)) return 'brak danych';
  if (kind === 'pct') return `${(value * PERCENT).toFixed(1)}%`;
  if (kind === 'usd') return `$${value.toFixed(2)}`;
  if (kind === 'dec') return value.toLocaleString('pl-PL', { maximumFractionDigits: 1 });
  return Math.round(value).toLocaleString('pl-PL');
}
function signed(value, kind) { return isNum(value) && value > 0 ? `+${fmt(value, kind)}` : fmt(value, kind); }
function when(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? String(iso || 'brak daty') : d.toLocaleString('pl-PL'); }
function notice(text) { return `<div class="notice">${esc(text)}</div>`; }
function card(eyebrow, title, body, pill = '') {
  return `<section class="card"><div class="card-heading"><div><span class="eyebrow">${esc(eyebrow)}</span><h2>${esc(title)}</h2></div>${pill}</div>${body}</section>`;
}
function pill(text, tone = '') { return `<span class="pill ${tone}">${esc(text)}</span>`; }
function problem(section, what) {
  if (section === undefined) return notice(`Brak sekcji ${what} w pliku statystyk.`);
  if (section && section.missing) return notice(`${what}: ${section.missing}`);
  if (section && section.error) return notice(`${what}: błąd odczytu: ${section.error}`);
  return null;
}

function dayList(since, until) {
  const out = [];
  const end = Date.parse(`${until}T00:00:00Z`);
  for (let t = Date.parse(`${since}T00:00:00Z`); t <= end && out.length < MAX_CHART_DAYS; t += DAY_MS) {
    out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

function dayTitle(day, rec) {
  if (!rec) return `${day}: brak zapisanych danych`;
  const cost = isNum(rec.cost_usd) ? `, koszt ${fmt(rec.cost_usd, 'usd')}` : '';
  return `${day}: ${fmt(rec.total_tokens)} tokenów, sesje-dni ${rec.sessions}, tury ${rec.turns}${cost}`;
}

function usageChart(usage, since, until) {
  const days = dayList(since, until);
  if (!days.length) return notice(`Niepoprawny zakres dat statystyk: ${since} – ${until}.`);
  const byDay = new Map(usage.days.map(d => [d.day, d]));
  const max = Math.max(0, ...usage.days.map(d => d.total_tokens || 0));
  const base = CHART.height - CHART.bottom;
  const plot = base - CHART.top;
  const slot = (CHART.width - 2 * CHART.padX) / days.length;
  const bars = days.map((day, i) => {
    const rec = byDay.get(day);
    const x = (CHART.padX + i * slot + CHART.gap / 2).toFixed(1);
    const w = Math.max(1, slot - CHART.gap).toFixed(1);
    if (!rec) return `<rect class="stats-gap" x="${x}" y="${base - CHART.gapMark}" width="${w}" height="${CHART.gapMark}"><title>${esc(dayTitle(day, rec))}</title></rect>`;
    const h = max > 0 && rec.total_tokens > 0 ? Math.max(CHART.minBar, (rec.total_tokens / max) * plot) : 0;
    return `<rect class="stats-bar" x="${x}" y="${(base - h).toFixed(1)}" width="${w}" height="${h.toFixed(1)}"><title>${esc(dayTitle(day, rec))}</title></rect>`;
  }).join('');
  const label = `Tokeny dziennie (Claude Code + Hermes), ${days[0]} – ${days[days.length - 1]}`;
  const axis = `<text class="stats-axis" x="${CHART.padX}" y="12">max ${esc(fmt(max))} tokenów/dzień</text><text class="stats-axis" x="${CHART.padX}" y="${CHART.height - 6}">${esc(days[0])}</text><text class="stats-axis" x="${CHART.width - CHART.padX}" y="${CHART.height - 6}" text-anchor="end">${esc(days[days.length - 1])}</text>`;
  return `<svg class="stats-chart" viewBox="0 0 ${CHART.width} ${CHART.height}" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title>${axis}${bars}</svg>`;
}

function kpi(label, value, hint = '') {
  return `<div class="stats-kpi"><small>${esc(label)}</small><strong>${esc(value)}</strong>${hint ? `<small>${esc(hint)}</small>` : ''}</div>`;
}

function renderUsage(doc) {
  const usage = doc.usage;
  const errors = Object.entries(doc.collect_errors || {}).map(([source, list]) => notice(`Kolektor ${source}: ${(list || []).join('; ')}`)).join('');
  const issue = problem(usage, 'Zużycie');
  if (issue) return card('Pomiar', 'Zużycie tokenów', errors + issue);
  if (!usage.days.length) {
    return card('Pomiar', 'Zużycie tokenów', errors + notice(`Brak zapisanych danych o zużyciu projektu ${doc.slug} w dniach ${doc.since} – ${doc.until} (magazyn ${doc.usage_db}; źródła: Claude Code, Hermes, JIT).`));
  }
  const t = usage.totals;
  const cost = isNum(t.cost_usd)
    ? kpi('Koszt (zapisany)', fmt(t.cost_usd, 'usd'), `z ${t.cost_sessions} sesji-dni Hermesa; Claude Code nie zapisuje kosztu`)
    : kpi('Koszt', 'brak danych', 'koszt zapisują tylko sesje Hermesa');
  const kpis = [kpi('Tokeny razem', fmt(t.total_tokens)), kpi('Input', fmt(t.input_tokens)), kpi('Output', fmt(t.output_tokens)),
    kpi('Cache read', fmt(t.cache_read_tokens)), kpi('Cache write', fmt(t.cache_write_tokens)),
    kpi('Sesje-dni', fmt(t.sessions)), kpi('Tury (Claude Code)', fmt(t.turns)), kpi('Kapsuły JIT', fmt(t.capsules)), cost].join('');
  const body = `${errors}<p class="source-meta">Ostatnie ${doc.window_days} dni, dni z danymi: ${t.active_days}. Słupek = suma input + output + cache-read + cache-write. Dzień bez danych ma tylko kreskę.</p>${usageChart(usage, doc.since, doc.until)}<div class="stats-kpis">${kpis}</div>`;
  return card('Pomiar', 'Zużycie tokenów', body, pill(`${doc.window_days} dni`));
}

function groupCell(group, name, kind) {
  const metric = group && group.metrics ? group.metrics[name] : null;
  if (!metric) return 'brak danych';
  return `${fmt(metric.median, kind)} <small class="muted">(n=${metric.n})</small>`;
}

function renderComparison(doc) {
  const cmp = doc.comparison;
  const issue = problem(cmp, 'Porównanie');
  const heading = ['Obserwacja', 'JIT włączony vs wyłączony'];
  if (issue) return card(...heading, issue);
  const on = cmp.jit_on, off = cmp.jit_off;
  if (!on.n && !off.n) return card(...heading, notice(`Brak sesji projektu ${doc.slug} w dniach ${doc.since} – ${doc.until}, więc nie ma czego porównać.`), pill(cmp.label));
  const warn = cmp.warning ? `<div class="notice">${esc(cmp.warning)}: potrzeba co najmniej ${cmp.min_group_n} w każdej grupie (jest ${on.n} z JIT i ${off.n} bez JIT).</div>` : '';
  const rows = COMPARE_METRICS.map(([name, label, kind]) => `<tr><td>${esc(label)}</td><td>${groupCell(on, name, kind)}</td><td>${groupCell(off, name, kind)}</td></tr>`).join('');
  const defs = Object.entries(cmp.definitions || {}).map(([k, v]) => `<li><span class="mono">${esc(k)}</span>: ${esc(v)}</li>`).join('');
  const body = `${warn}<p class="source-meta">Mediany w grupach. Jednostka: ${esc(cmp.unit)}. Sesje same wybierają grupę, więc to nie jest pomiar oszczędności; oszczędność pokazuje tylko A/B.</p><table class="stats-table"><thead><tr><th>Metryka</th><th>JIT włączony (n=${on.n})</th><th>JIT wyłączony (n=${off.n})</th></tr></thead><tbody>${rows}</tbody></table>${defs ? `<details><summary>Definicje metryk</summary><ul>${defs}</ul></details>` : ''}`;
  return card(...heading, body, pill(cmp.label, 'pill-amber'));
}

function abRow(ab, name, label, kind) {
  const arm = key => (ab.arms && ab.arms[key] && ab.arms[key][name]) || {};
  const pair = (ab.paired_on_minus_off || {})[name] || {};
  return `<tr><td>${esc(label)}</td><td>${fmt(arm('on').median, kind)} <small class="muted">(n=${arm('on').n ?? 0})</small></td><td>${fmt(arm('off').median, kind)} <small class="muted">(n=${arm('off').n ?? 0})</small></td><td><strong>${esc(signed(pair.median, kind))}</strong> <small class="muted">(n=${pair.n ?? 0})</small></td></tr>`;
}

function renderAb(doc) {
  const ab = doc.ab;
  const heading = ['Eksperyment kontrolowany', 'Ostatni test A/B'];
  const issue = problem(ab, 'A/B');
  if (issue) return card(...heading, issue);
  if (ab === null) return card(...heading, notice(`Brak przebiegów A/B dla projektu ${doc.slug}. Uruchom ręcznie: jit bench ab ${doc.slug} --yes (kosztuje tokeny). Bez A/B kokpit nie pokazuje oszczędności.`));
  const delta = (ab.paired_on_minus_off || {}).total_tokens || {};
  const facts = [kpi('Data', when(ab.date)), kpi('Model', ab.model || 'brak danych'), kpi('Wywołania', `${ab.calls}`, `błędy: ${ab.errors}`),
    kpi('Zadania x przebiegi', `${ab.tasks} x ${ab.runs}`), kpi('Mediana różnicy tokenów (JIT - bez JIT)', signed(delta.median, 'int'), `n=${delta.n ?? 0} par`)].join('');
  const rows = AB_METRICS.map(([name, label, kind]) => abRow(ab, name, label, kind)).join('');
  const body = `<div class="stats-kpis">${facts}</div><table class="stats-table"><thead><tr><th>Metryka</th><th>JIT włączony</th><th>JIT wyłączony</th><th>Mediana różnic par</th></tr></thead><tbody>${rows}</tbody></table><p class="source-meta">Partia ${esc(ab.batch_id)}${ab.head ? ` @ ${esc(String(ab.head).slice(0, 7))}` : ''}. Ujemna różnica = mniej z JIT. Nieudane wywołania nie wchodzą do median.</p>`;
  return card(...heading, body, pill(`n=${delta.n ?? 0}`));
}

function suggestionItem(s) {
  const [label, tone] = SEVERITY[s.severity] || [s.severity, ''];
  const evidence = (s.evidence || []).map(e => `<li>${esc(EVIDENCE_KIND[e.kind] || e.kind)} <span class="mono">${esc(e.ref)}</span>: ${esc(e.value)}</li>`).join('');
  return `<div class="stats-sugg"><div>${pill(label, tone)} <strong>${esc(s.summary)}</strong></div><div>Zalecenie: ${esc(s.action)}</div>${evidence ? `<ul>${evidence}</ul>` : '<small class="muted">Brak dowodów w raporcie.</small>'}<small class="muted mono">${esc(s.id)}</small></div>`;
}

function renderSuggestions(doc) {
  const rep = doc.suggestions;
  const heading = ['Reguły deterministyczne', 'Sugestie'];
  const issue = problem(rep, 'Sugestie');
  if (issue) return card(...heading, issue);
  const list = rep.suggestions || [];
  const errors = (rep.errors || []).map(e => notice(`Reguła ${e.id} nie zadziałała: ${e.error}`)).join('');
  const skipped = (rep.skipped || []).length ? `<details><summary>Pominięte reguły (${rep.skipped.length}): brak danych wejściowych</summary><ul>${rep.skipped.map(s => `<li><span class="mono">${esc(s.id)}</span>: ${esc(s.reason)}</li>`).join('')}</ul></details>` : '';
  const items = list.length ? list.map(suggestionItem).join('') : `<p class="muted">Sprawdzono ${esc(rep.rules_checked)} reguł: żadna nie znalazła problemu.</p>`;
  return card(...heading, errors + items + skipped, pill(`${list.length}`));
}

function renderStatsTab(data) {
  const stats = data.stats;
  const heading = ['Hub projektu', 'Statystyki'];
  if (!stats) return card(...heading, notice('Generator kokpitu nie dołączył sekcji stats do danych.'));
  if (stats.error) return card(...heading, notice(stats.error));
  if (!stats.data) return card(...heading, notice(stats.missing || 'Brak danych statystyk.'));
  const doc = stats.data;
  const meta = `<p class="source-meta">Plik: <span class="mono">${esc(stats.path)}</span> · zapisany ${esc(when(doc.generated_at))} · okno ${esc(doc.since)} – ${esc(doc.until)}</p>`;
  return `${STYLE}<div class="stats-grid">${meta}${renderUsage(doc)}${renderComparison(doc)}${renderAb(doc)}${renderSuggestions(doc)}</div>`;
}

module.exports = { renderStatsTab, usageChart, dayList };
