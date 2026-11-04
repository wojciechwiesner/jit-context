// Stats tab: rendering from fixture JSON (with and without A/B, low n), the stats file loader, and a full build.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderStatsTab, dayList } = require('./render_stats');
const { collectStats } = require('./stats');

const metric = (median, n) => ({ median, n });
const group = (n, tokens) => ({ n, sources: { claude: n }, metrics: { tokens_per_turn: metric(tokens, n), cache_read_share: metric(0.5, n), turns_per_session: metric(n ? 4 : null, n), tool_errors_per_session: metric(null, 0) } });
const day = (d, total, cost = null) => ({ day: d, input_tokens: total / 2, output_tokens: total / 4, cache_read_tokens: total / 8, cache_write_tokens: total / 8, total_tokens: total, sessions: 2, turns: 5, capsules: 1, capsule_tokens: 400, cost_usd: cost, cost_sessions: cost === null ? 0 : 1, sources: ['claude'] });
const arm = (tokens, n) => ({ total_tokens: metric(tokens, n), num_turns: metric(3, n), wall_s: metric(12.5, n), cost_usd: metric(null, 0), errors: 0 });

function fixture({ withAb }) {
  return {
    schema: 1, slug: 'demo', project_path: '/tmp/demo', generated_at: '2026-11-04T10:00:00+01:00', window_days: 30,
    since: '2026-10-06', until: '2026-11-04', usage_db: '/tmp/hub/usage.sqlite', collect_errors: {},
    usage: { days: [day('2026-10-20', 8000), day('2026-11-03', 16000, 0.42)], totals: { input_tokens: 12000, output_tokens: 6000, cache_read_tokens: 3000, cache_write_tokens: 3000, total_tokens: 24000, sessions: 4, turns: 10, capsules: 2, cost_sessions: 1, cost_usd: 0.42, active_days: 2 }, cost_sources: ['hermes'] },
    comparison: { label: 'obserwacja, nie eksperyment', low_n_label: 'za mało danych', min_group_n: 20, unit: 'sesja-dzień', jit_on: group(3, 1500), jit_off: group(2, 2100), enough_data: false, warning: 'za mało danych', definitions: { tokens_per_turn: 'tokeny / tury' } },
    ab: withAb ? { batch_id: 'b20261101', date: '2026-11-01T09:00:00+0100', model: 'sonnet', head: 'abcdef1234', calls: 12, errors: 1, tasks: 3, runs: 2, arms: { on: arm(9000, 5), off: arm(9400, 6) }, paired_on_minus_off: { total_tokens: metric(-400, 5), num_turns: metric(0, 5), wall_s: metric(-1.5, 5), cost_usd: metric(null, 0) } } : null,
    suggestions: { rules_checked: 12, suggestions: [{ id: 'state_stale', severity: 'high', summary: 'STATE.md <b>stary</b>', action: 'Zaktualizuj STATE.md', evidence: [{ kind: 'file', ref: '.planning/STATE.md', value: '6.1 d' }] }], skipped: [{ id: 'usage_spike', reason: 'brak poprzedniego tygodnia' }], errors: [] },
  };
}

const wrap = doc => ({ stats: { path: '/tmp/hub/stats/demo.json', data: doc, missing: null, error: null } });

test('stats tab renders usage bars, totals, cost, comparison with n and low-n label, A/B and suggestions', () => {
  const html = renderStatsTab(wrap(fixture({ withAb: true })));
  assert.equal((html.match(/class="stats-bar"/g) || []).length, 2);
  assert.equal((html.match(/class="stats-gap"/g) || []).length, 28);
  assert.match(html, /<svg class="stats-chart"[^>]*role="img"/);
  assert.match(html, /2026-11-03: 16[\s ]?000 tokenów/);
  assert.match(html, /\$0\.42/);
  assert.match(html, /obserwacja, nie eksperyment/);
  assert.match(html, /za mało danych: potrzeba co najmniej 20/);
  assert.match(html, /JIT włączony \(n=3\)/);
  assert.match(html, /JIT wyłączony \(n=2\)/);
  assert.match(html, /Ostatni test A\/B/);
  assert.match(html, /sonnet/);
  assert.match(html, /-400/);
  assert.match(html, /n=5 par/);
  assert.match(html, /wysoki/);
  assert.match(html, /\.planning\/STATE\.md/);
  assert.match(html, /STATE\.md &lt;b&gt;stary&lt;\/b&gt;/);
  assert.match(html, /usage_spike/);
  assert.doesNotMatch(html, /oszczędzon|saved/i);
});

test('without A/B the tab says exactly what is missing', () => {
  const html = renderStatsTab(wrap(fixture({ withAb: false })));
  assert.match(html, /Brak przebiegów A\/B dla projektu demo/);
  assert.match(html, /jit bench ab demo --yes/);
  assert.match(html, /za mało danych/);
});

test('empty and broken sections show what is missing, never zeros', () => {
  const doc = fixture({ withAb: false });
  doc.usage = { days: [], totals: {}, cost_sources: ['hermes'] };
  doc.comparison = { missing: 'brak magazynu zużycia /tmp/hub/usage.sqlite' };
  doc.suggestions = { error: 'RuntimeError: boom' };
  doc.collect_errors = { claude: ['bad line'] };
  const html = renderStatsTab(wrap(doc));
  assert.match(html, /Brak zapisanych danych o zużyciu projektu demo w dniach 2026-10-06 – 2026-11-04/);
  assert.match(html, /brak magazynu zużycia/);
  assert.match(html, /Sugestie: błąd odczytu: RuntimeError: boom/);
  assert.match(html, /Kolektor claude: bad line/);
  assert.doesNotMatch(html, /class="stats-bar"/);
  assert.match(renderStatsTab({}), /nie dołączył sekcji stats/);
  assert.match(renderStatsTab({ stats: { path: null, data: null, missing: 'Projekt nie jest w rejestrze hubu', error: null } }), /nie jest w rejestrze/);
});

test('dayList covers the 30-day window inclusively', () => {
  const days = dayList('2026-10-06', '2026-11-04');
  assert.equal(days.length, 30);
  assert.equal(days[0], '2026-10-06');
  assert.equal(days[29], '2026-11-04');
});

function tmpDir(t, prefix) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

test('collectStats reads <hub dir>/stats/<slug>.json and reports a missing or broken file', t => {
  const hub = tmpDir(t, 'cockpit-stats-');
  const env = { JIT_HUB_DIR: hub };
  assert.match(collectStats(null, env).missing, /rejestrze hubu/);
  const missing = collectStats('demo', env);
  assert.equal(missing.data, null);
  assert.ok(missing.missing.includes(path.join(hub, 'stats', 'demo.json')));
  fs.mkdirSync(path.join(hub, 'stats'));
  fs.writeFileSync(path.join(hub, 'stats', 'demo.json'), '{not json');
  assert.match(collectStats('demo', env).error, /Niepoprawny plik statystyk/);
  fs.writeFileSync(path.join(hub, 'stats', 'demo.json'), JSON.stringify(fixture({ withAb: true })));
  assert.equal(collectStats('demo', env).data.slug, 'demo');
});

test('the generator puts the stats tab into the cockpit from the hub stats file', t => {
  const hub = tmpDir(t, 'cockpit-stats-hub-');
  const project = tmpDir(t, 'cockpit-stats-proj-');
  fs.mkdirSync(path.join(project, '.planning'));
  fs.writeFileSync(path.join(project, '.planning', 'STATE.md'), '# State\n\n## Tasks\n- [ ] H12 stats\n');
  fs.mkdirSync(path.join(hub, 'stats'));
  fs.writeFileSync(path.join(hub, 'stats', 'demo.json'), JSON.stringify(fixture({ withAb: true })));
  const out = path.join(hub, 'cockpit.html');
  execFileSync('node', [path.join(__dirname, 'build_state_template.js'), project, '--out', out, '--hub-slug', 'demo'],
    { env: { ...process.env, JIT_HUB_DIR: hub, HOME: hub }, encoding: 'utf-8' });
  const html = fs.readFileSync(out, 'utf-8');
  assert.match(html, /data-tab="stats"/);
  assert.match(html, /id="pane-stats"/);
  assert.match(html, /Statystyki/);
  assert.match(html, /class="stats-bar"/);
  assert.match(html, /b20261101/);
});
