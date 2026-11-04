// Hub actions UI: safe markdown, run/poll helpers, the rendered tab and the browser script against a fake DOM.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { collect } = require('./collect');
const { render } = require('./render');
const acts = require('./hub_actions');
const md = require('./safe_markdown');
const { getActionsScript } = require('./client_actions');
const { hubActionsUrl } = require('./render_actions');

const SLUG = 'demo-proj';
const CSRF = 'token-123';
const HOSTILE = '<img src=x onerror=alert(1)><script>alert(2)</script>';
const IDS = ['actions-file-fallback', 'actions-hub-panel', 'actions-fallback-reason', 'action-runs-list', 'action-runs-status',
  'action-confirm-modal', 'action-confirm-title', 'action-confirm-text', 'action-confirm-error', 'action-confirm-run',
  'action-report-viewer', 'action-report-title', 'action-report-meta', 'action-report-body',
  ...acts.HUB_ACTIONS.map(a => 'action-btn-' + a.id)];
const RUN_DONE = { id: '20261104T101010-audit360-abc123', slug: SLUG, action: 'audit360', label: 'Audyt 360', status: 'succeeded',
  created: '2026-11-04T10:10:10+01:00', started: '2026-11-04T10:10:11+01:00', finished: '2026-11-04T10:20:11+01:00',
  cost: 0.0123, usage: { output_tokens: 50 }, report_path: '/hub/reports/demo-proj/2026-11-04-audit360.md', error: null };
const RUN_ACTIVE = { id: '20261104T102000-security-def456', slug: SLUG, action: 'security', label: 'Audyt bezpieczeństwa',
  status: 'running', created: '2026-11-04T10:20:00+01:00', started: '2026-11-04T10:20:01+01:00', cost: null, report_path: null };

class FakeNode {
  constructor(tag, text = '') {
    this.tagName = tag; this.className = ''; this.children = []; this.attrs = {}; this.ownText = text;
    this.hidden = false; this.disabled = false; this.listeners = {}; this.classes = new Set();
    this.classList = { add: c => this.classes.add(c), remove: c => this.classes.delete(c), contains: c => this.classes.has(c) };
  }
  set innerHTML(_) { throw new Error('innerHTML must not be used'); }
  get textContent() { return this.ownText + this.children.map(c => c.textContent).join(''); }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  all() { return [this, ...this.children.flatMap(c => c.all ? c.all() : [])]; }
  find(cls) { return this.all().filter(e => (e.className || '').split(' ').includes(cls)); }
  tags(tag) { return this.all().filter(e => e.tagName === tag); }
}

function fakeDocument(meta = {}) {
  const byId = Object.fromEntries(IDS.map(id => [id, new FakeNode('div')]));
  byId['actions-hub-panel'].hidden = true;
  byId['action-report-viewer'].hidden = true;
  return {
    byId, created: [],
    createElement(tag) { const node = new FakeNode(tag); this.created.push(tag); return node; },
    createTextNode: text => new FakeNode('#text', text),
    getElementById: id => byId[id] || null,
    querySelector: selector => {
      const name = /meta\[name="([^"]+)"\]/.exec(selector)?.[1];
      if (!(name in meta)) return null;
      const node = new FakeNode('meta'); node.attrs.content = meta[name]; return node;
    },
  };
}

function hubMeta() {
  return { 'jit-hub-actions': '/api/hub/actions', 'jit-hub-runs': '/api/hub/runs', 'jit-hub-report': '/api/hub/report',
    'jit-hub-slug': SLUG, 'jit-hub-csrf': CSRF };
}

function runScript({ protocol, meta, responses = [] }) {
  const document = fakeDocument(meta);
  const calls = []; const timers = [];
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    const [status, payload] = responses.shift() || [500, { error: 'no fake response' }];
    return { ok: status >= 200 && status < 300, status, json: async () => payload };
  };
  const sandbox = { document, fetch, AbortSignal, window: { location: { protocol, hash: '' } },
    setTimeout: (fn, ms) => { timers.push(ms); return timers.length; }, clearTimeout: () => {} };
  vm.runInNewContext(getActionsScript(), sandbox);
  return { sandbox, document, calls, timers };
}

function cockpitHtml(t, hubSlug) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-actions-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, '.planning'));
  const data = collect(root);
  data.hubSlug = hubSlug;
  return render(data);
}

test('safe markdown: hostile HTML stays text, structure becomes DOM, only http(s) links survive', () => {
  const doc = fakeDocument();
  const box = new FakeNode('div');
  const report = ['# Audyt 360: demo', '', HOSTILE, '', '## Ryzyka', '- **Wysokie** ryzyko w `src/app.py:12`',
    '- [źródło](https://example.com/a) i [zły](javascript:alert(1))', '1. pierwszy', '2. drugi', '', '```bash', 'rm -rf <dir>', '```',
    '> cytat', '---', '| Plik | Ocena |', '|---|---|', '| a.py | <b>dobra</b> |', 'rakieta \u{1F680} start'].join('\n');
  assert.equal(md.renderSafeMarkdown(doc, box, report), 10);
  assert.deepEqual(box.children.map(c => c.tagName), ['h2', 'p', 'h3', 'ul', 'ol', 'pre', 'blockquote', 'hr', 'table', 'p']);
  assert.equal(box.children[1].textContent, HOSTILE);
  for (const tag of ['img', 'script', 'b']) assert.equal(doc.created.includes(tag), false, tag);
  assert.equal(box.tags('strong')[0].textContent, 'Wysokie');
  assert.equal(box.tags('code')[0].textContent, 'src/app.py:12');
  const links = box.tags('a');
  assert.equal(links.length, 1);
  assert.deepEqual(links[0].attrs, { href: 'https://example.com/a', target: '_blank', rel: 'noopener noreferrer' });
  assert.match(box.children[3].textContent, /zły \(javascript:alert\(1\)\)/);
  assert.equal(box.children[5].textContent, 'rm -rf <dir>');
  assert.deepEqual(box.tags('th').map(c => c.textContent), ['Plik', 'Ocena']);
  assert.equal(box.tags('td')[1].textContent, '<b>dobra</b>');
  assert.equal(box.children[9].textContent, 'rakieta  start');
  md.renderSafeMarkdown(doc, box, '');
  assert.equal(box.children.length, 0);
});

test('markdown blocks: lists split by kind, paragraphs join lines, unclosed fence keeps the text', () => {
  const blocks = md.mdBlocks('linia a\nlinia b\n- x\n- y\n1) z\n```\nkod');
  assert.deepEqual(blocks, [{ type: 'paragraph', text: 'linia a linia b' }, { type: 'list', ordered: false, items: ['x', 'y'] },
    { type: 'list', ordered: true, items: ['z'] }, { type: 'code', lang: '', text: 'kod' }]);
});

test('poll delay: fast while a run is active, slow when idle, backoff after failures', () => {
  assert.equal(acts.nextPollDelay([RUN_ACTIVE, RUN_DONE], 0), acts.ACTIONS_ACTIVE_POLL_MS);
  assert.equal(acts.nextPollDelay([RUN_DONE], 0), acts.ACTIONS_IDLE_POLL_MS);
  assert.equal(acts.nextPollDelay([], 0), acts.ACTIONS_IDLE_POLL_MS);
  assert.equal(acts.nextPollDelay([], 1), 2 * acts.ACTIONS_ACTIVE_POLL_MS);
  assert.equal(acts.nextPollDelay([], 10), acts.ACTIONS_MAX_BACKOFF_MS);
  assert.deepEqual(acts.activeActionIds([RUN_ACTIVE, RUN_DONE, { ...RUN_ACTIVE, status: 'queued' }]), ['security']);
});

test('run row: status label, meta with cost and tokens, error as text, report button only with a report', () => {
  const doc = fakeDocument();
  const done = acts.createRunNode(doc, RUN_DONE);
  assert.equal(done.find('run-status')[0].textContent, 'gotowe');
  assert.match(done.find('run-meta')[0].textContent, /koszt: 0\.0123 USD · tokeny wyjściowe: 50$/);
  assert.equal(done.find('run-report-btn')[0].getAttribute('data-run-id'), RUN_DONE.id);
  const failed = acts.createRunNode(doc, { ...RUN_DONE, status: 'failed', report_path: null, cost: null, error: HOSTILE });
  assert.equal(failed.find('run-error')[0].textContent, HOSTILE);
  assert.equal(failed.find('run-report-btn').length, 0);
  assert.match(failed.find('run-meta')[0].textContent, /koszt: brak danych/);
  assert.equal(acts.createRunNode(doc, RUN_ACTIVE).find('run-meta')[0].textContent.includes('koszt'), false);
  assert.equal(acts.runStatusLabel('weird'), 'weird');
  assert.match(acts.actionConfirmText('market', SLUG), /Badanie rynku.*uruchomi model.*demo-proj.*zużyje tokeny/);
});

test('config from meta tags; mode depends on protocol', () => {
  assert.deepEqual(acts.readHubActionsConfig(fakeDocument(hubMeta())),
    { actions: '/api/hub/actions', runs: '/api/hub/runs', report: '/api/hub/report', slug: SLUG, csrf: CSRF });
  assert.equal(acts.readHubActionsConfig(fakeDocument({ 'jit-hub-slug': SLUG, 'jit-hub-csrf': CSRF })), null);
  assert.equal(acts.actionsMode('file:', { actions: 'x' }), 'file');
  assert.equal(acts.actionsMode('http:', { actions: 'x' }), 'hub');
  assert.equal(acts.actionsMode('https:', null), 'unavailable');
});

test('rendered tab: four action buttons, cost warning in the confirm dialog, hub link, scripts share one scope', t => {
  const html = cockpitHtml(t, SLUG);
  for (const action of acts.HUB_ACTIONS) {
    assert.ok(html.includes(`id="action-btn-${action.id}" data-action="${action.id}"`), action.id);
    assert.ok(html.includes(`<span>${action.label}</span>`), action.label);
  }
  assert.ok(html.includes('data-tab="actions"'));
  assert.ok(html.includes('<div id="actions-hub-panel" hidden>'));
  assert.match(html, /id="action-confirm-cost">Uruchamia model i może kosztować tokeny/);
  assert.ok(html.includes(`id="actions-open-hub" href="${hubActionsUrl(SLUG)}"`));
  assert.equal(hubActionsUrl(SLUG), `http://127.0.0.1:8767/hub/${SLUG}#actions`);
  for (const id of IDS) assert.ok(html.includes(`id="${id}"`), id);
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  assert.doesNotThrow(() => new vm.Script(scripts.join('\n;\n')));
  assert.ok(cockpitHtml(t, null).includes('Projekt nie jest w rejestrze huba (jit init albo jit hub scan), więc hub nie ma dla niego akcji.'));
});

test('file:// cockpit keeps the hub button and never calls fetch', async () => {
  const { sandbox, document, calls } = runScript({ protocol: 'file:', meta: {} });
  await sandbox.loadHubActions();
  sandbox.askActionRun('audit360');
  await sandbox.confirmActionRun();
  assert.equal(calls.length, 0);
  assert.equal(document.byId['actions-hub-panel'].hidden, true);
  assert.equal(document.byId['action-confirm-modal'].classList.contains('open'), false);
});

test('served from the hub: runs polled, active action disabled, confirm then POST with CSRF, poll slows down', async () => {
  const listing = { runs: [RUN_ACTIVE, RUN_DONE], max_concurrent: 2, unreadable: 0 };
  const queued = { ...RUN_ACTIVE, id: '20261104T103000-market-aaa111', action: 'market', label: 'Badanie rynku', status: 'queued' };
  const { sandbox, document, calls, timers } = runScript({ protocol: 'http:', meta: hubMeta(), responses: [
    [200, listing], [202, { run: queued }], [200, { runs: [queued, RUN_DONE] }], [200, { runs: [RUN_DONE] }]] });
  await sandbox.loadHubActions();
  assert.equal(calls[0].url, `/api/hub/runs?slug=${SLUG}`);
  assert.equal(document.byId['actions-hub-panel'].hidden, false);
  assert.equal(document.byId['action-runs-list'].children.length, 2);
  assert.equal(document.byId['action-btn-security'].disabled, true);
  assert.equal(document.byId['action-btn-audit360'].disabled, false);
  assert.match(document.byId['action-runs-status'].textContent, /aktywne: 1 · limit równoległych: 2/);
  assert.deepEqual(timers, [acts.ACTIONS_ACTIVE_POLL_MS]);

  sandbox.askActionRun('market');
  assert.equal(document.byId['action-confirm-modal'].classList.contains('open'), true);
  assert.match(document.byId['action-confirm-text'].textContent, /uruchomi model.*tokeny/);
  await sandbox.confirmActionRun();
  const post = calls[1];
  assert.equal(post.url, '/api/hub/actions');
  assert.equal(post.options.method, 'POST');
  assert.equal(post.options.headers['X-JIT-Hub-CSRF'], CSRF);
  assert.deepEqual(JSON.parse(post.options.body), { slug: SLUG, action: 'market' });
  assert.equal(document.byId['action-confirm-modal'].classList.contains('open'), false);
  assert.equal(document.byId['action-btn-market'].disabled, true);
  await sandbox.pollActionRuns();
  assert.equal(document.byId['action-btn-market'].disabled, false);
  assert.equal(timers.at(-1), acts.ACTIONS_IDLE_POLL_MS);
});

test('409 and failed polls are shown as errors, never as a fake status', async () => {
  const { sandbox, document, timers } = runScript({ protocol: 'https:', meta: hubMeta(), responses: [
    [200, { runs: [] }], [409, { error: 'Badanie rynku dla demo-proj już trwa' }], [502, { error: 'upstream down' }]] });
  await sandbox.loadHubActions();
  assert.equal(document.byId['action-runs-list'].children[0].textContent, 'Brak uruchomień dla tego projektu. Wybierz akcję powyżej.');
  sandbox.askActionRun('market');
  await sandbox.confirmActionRun();
  const error = document.byId['action-confirm-error'];
  assert.equal(error.hidden, false);
  assert.match(error.textContent, /już czeka albo trwa.*HTTP 409: Badanie rynku dla demo-proj już trwa/);
  assert.match(document.byId['action-runs-status'].textContent, /Nie wczytano listy uruchomień.*upstream down/);
  assert.equal(timers.at(-1), 2 * acts.ACTIONS_ACTIVE_POLL_MS);
});

test('report viewer loads markdown by run id and renders it without HTML; missing report shows the error', async () => {
  const report = { run: RUN_DONE, markdown: `# Raport\n\n${HOSTILE}\n\n- punkt`, path: RUN_DONE.report_path };
  const { sandbox, document, calls } = runScript({ protocol: 'http:', meta: hubMeta(), responses: [
    [200, { runs: [RUN_DONE] }], [200, report], [404, { error: 'uruchomienie x nie ma raportu' }]] });
  await sandbox.loadHubActions();
  const button = document.byId['action-runs-list'].children[0].find('run-report-btn')[0];
  document.byId['action-runs-list'].listeners.click({ target: { closest: () => button } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls[1].url, `/api/hub/report?run=${RUN_DONE.id}`);
  const body = document.byId['action-report-body'];
  assert.equal(document.byId['action-report-viewer'].hidden, false);
  assert.equal(document.byId['action-report-title'].textContent, 'Audyt 360 · gotowe');
  assert.deepEqual(body.children.map(c => c.tagName), ['h2', 'p', 'ul']);
  assert.equal(body.children[1].textContent, HOSTILE);
  assert.match(document.byId['action-report-meta'].textContent, /plik: \/hub\/reports\/demo-proj/);
  await sandbox.openRunReport('x');
  assert.equal(body.children.length, 0);
  assert.match(document.byId['action-report-meta'].textContent, /Nie wczytano raportu.*nie ma raportu/);
  sandbox.closeRunReport();
  assert.equal(document.byId['action-report-viewer'].hidden, true);
});
