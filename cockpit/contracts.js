// Behavior contracts card: reads .planning/contracts.json written by `autocheck_flow contracts run --write`.
// Shows "when X -> should Y" per contract with violating record ids. No file = not measured, never "ok".
const fs = require('fs');
const path = require('path');
const { esc } = require('./html');

const CONTRACTS_STALE_MS = 2 * 60 * 60 * 1000; // cron runs every 30 min

function collectContracts(root) {
  const planning = path.join(root, '.planning');
  const hasDefinition = fs.existsSync(path.join(planning, 'contracts.yaml'));
  const file = path.join(planning, 'contracts.json');
  if (!fs.existsSync(file)) return { exists: false, hasDefinition, contracts: [] };
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf-8'));
    return {
      exists: true,
      hasDefinition,
      checkedAt: data.checked_at || null,
      overallState: data.overall_state || 'error',
      contracts: Array.isArray(data.contracts) ? data.contracts : [],
    };
  } catch (e) {
    return { exists: false, hasDefinition, contracts: [], error: `contracts.json nieczytelny: ${e.message}` };
  }
}

const STATE_LABEL = { ok: 'OK', violated: 'NARUSZONY', error: 'NIE SPRAWDZONY' };
const STATE_TONE = { ok: 'pill-green', violated: 'pill-red', error: 'pill-amber' };

function renderContractRow(c) {
  const detail = c.state === 'violated'
    ? `${c.violation_count} naruszeń: <span class="mono">${esc((c.sample_ids || []).slice(0, 5).join(', '))}</span>`
    : c.state === 'error' ? esc(c.error || 'błąd sprawdzenia') : `${esc(String(c.duration_ms))} ms`;
  return `<li class="contract-row"><div><strong>${esc(c.when)}</strong><div class="muted">powinno: ${esc(c.then)}</div><small>${detail}</small></div><span class="pill ${STATE_TONE[c.state] || ''}">${STATE_LABEL[c.state] || esc(c.state)}</span></li>`;
}

function renderContracts(contracts) {
  const heading = (pill) => `<div class="card-heading"><div><span class="eyebrow">Czy funkcje robią to, co powinny</span><h2>Kontrakty zachowania</h2></div>${pill}</div>`;
  if (!contracts || !contracts.exists) {
    const hint = contracts && contracts.hasDefinition
      ? 'Plik .planning/contracts.yaml jest, ale nie było jeszcze przebiegu: <span class="mono">python3 -m autocheck_flow contracts run . --write</span>'
      : 'Brak .planning/contracts.yaml (tworzy go <span class="mono">jit init</span>).';
    return `<section class="card">${heading('<span class="pill">NIE ZMIERZONO</span>')}<div class="source-meta">${contracts && contracts.error ? esc(contracts.error) : hint}</div></section>`;
  }
  const checked = contracts.checkedAt ? new Date(contracts.checkedAt) : null;
  const stale = !checked || Number.isNaN(checked.getTime()) || Date.now() - checked.getTime() > CONTRACTS_STALE_MS;
  const when = checked && !Number.isNaN(checked.getTime()) ? checked.toLocaleString('pl-PL') : 'nieznany';
  const overall = contracts.overallState;
  const pill = `<span class="pill ${stale ? 'pill-amber' : STATE_TONE[overall] || ''}">${esc(STATE_LABEL[overall] || overall.toUpperCase())}${stale ? ' · STALE' : ''}</span>`;
  const meta = `<div class="source-meta">Sprawdzone ${esc(when)}${stale ? ' · <strong>nieaktualne (starsze niż 2 h)</strong>' : ''} · ${contracts.contracts.length} kontrakt(ów)</div>`;
  const order = { violated: 0, error: 1, ok: 2 };
  const rows = [...contracts.contracts].sort((a, b) => (order[a.state] ?? 3) - (order[b.state] ?? 3)).map(renderContractRow).join('');
  return `<section class="card">${heading(pill)}${meta}<style>.contract-list{list-style:none;margin:8px 0 0;padding:0}.contract-row{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--border)}.contract-row small{overflow-wrap:anywhere}</style><ul class="contract-list">${rows}</ul></section>`;
}

module.exports = { collectContracts, renderContracts, CONTRACTS_STALE_MS };
