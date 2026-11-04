// Freshness UX: build stamp, newer-worktree notice, hub link for file:// and version polling only over http(s).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { collect } = require('./collect');
const { render } = require('./render');
const fresh = require('./freshness');

const BUILT_AT = '2026-11-04T09:30:00.000Z';
const SOURCE_AT = '2026-11-04T08:00:00+00:00';

function tmpDir(t, prefix) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function cockpitData(t, worktrees = []) {
  const root = tmpDir(t, 'cockpit-fresh-');
  fs.mkdirSync(path.join(root, '.planning'));
  const data = collect(root);
  data.generatedAt = BUILT_AT;
  data.git = { isRepo: true, branch: 'feat/project-hub', log: [{ hash: 'abc1234', msg: 'm', iso: SOURCE_AT }], dirty: [] };
  data.worktrees = worktrees;
  return data;
}

function worktree(branch, at, subject = 'work') {
  return { path: `/tmp/${branch}`, branch, head: 'f'.repeat(40), last_commit_at: at, last_commit_subject: subject };
}

test('header shows build time, source branch and sha', t => {
  const html = render(cockpitData(t));
  const expected = `Zbudowano: ${fresh.formatTime(BUILT_AT)}, źródło: feat/project-hub @ abc1234`;
  assert.equal(fresh.buildStampText(cockpitData(t)), expected);
  assert.ok(html.includes(`id="build-stamp">${expected}</span>`));
});

test('header names a missing repository or commit instead of guessing', t => {
  const data = cockpitData(t);
  data.git = { isRepo: false, branch: 'brak gita', log: [] };
  assert.match(fresh.buildStampText(data), /źródło: brak repozytorium git$/);
  data.git = { isRepo: true, branch: 'main', log: [] };
  assert.match(fresh.buildStampText(data), /źródło: main @ bez commita$/);
});

test('notice appears only when a worktree has a newer commit than the source', t => {
  const older = worktree('old-branch', '2026-11-03T10:00:00+00:00');
  const same = worktree('feat/project-hub', SOURCE_AT);
  assert.equal(fresh.newerWorktree(cockpitData(t, [same, older])), null);
  assert.equal(render(cockpitData(t, [same, older])).includes('freshness-notice"'), false);

  const newer = worktree('feat/<x>', '2026-11-04T09:00:00+00:00', 'newer <b>commit</b>');
  const newest = worktree('feat/newest', '2026-11-04T09:10:00+00:00');
  const data = cockpitData(t, [same, newer, newest, older]);
  assert.equal(fresh.newerWorktree(data).branch, 'feat/newest');
  const notice = fresh.renderNewerNotice(cockpitData(t, [same, newer]));
  assert.match(notice, /class="freshness-notice"/);
  assert.match(notice, /feat\/&lt;x&gt;/);
  assert.match(notice, /newer &lt;b&gt;commit&lt;\/b&gt;/);
  assert.ok(notice.includes(fresh.formatTime('2026-11-04T09:00:00+00:00')));
  assert.match(render(data), /id="freshness-notice"/);
});

test('non-git project never shows the notice', t => {
  const data = cockpitData(t, [worktree('x', '2030-01-01T00:00:00Z')]);
  data.git = { isRepo: false, branch: 'brak gita', log: [] };
  assert.equal(fresh.renderNewerNotice(data), '');
});

function runClient(protocol, { pathname = '/hub/my-proj', hubSlug = 'my-proj', responses = [] } = {}) {
  const calls = { intervals: [], fetches: [], reloads: 0 };
  const elements = { 'hub-open-link': { hidden: true }, 'hub-version-status': { textContent: '' },
    'cockpit-data-json': { textContent: JSON.stringify({ slug: 'x', hubSlug }) } };
  const queue = [...responses];
  const sandbox = {
    window: { location: { protocol, pathname, origin: 'http://127.0.0.1:8767', reload: () => { calls.reloads += 1; } } },
    document: { getElementById: id => elements[id] || null },
    setInterval: (fn, ms) => { calls.intervals.push(ms); calls.tick = fn; },
    fetch: url => {
      calls.fetches.push(url);
      const next = queue.shift() || { status: 200, body: {} };
      return Promise.resolve({ ok: next.status < 400, status: next.status, json: () => Promise.resolve(next.body) });
    },
    JSON, Error, encodeURIComponent, decodeURIComponent,
  };
  vm.runInNewContext(fresh.getFreshnessScript(), sandbox);
  return { calls, elements };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('file:// shows the hub link and never polls', () => {
  const { calls, elements } = runClient('file:');
  assert.deepEqual(calls.intervals, []);
  assert.deepEqual(calls.fetches, []);
  assert.equal(elements['hub-open-link'].hidden, false);
});

test('polling runs every 30 s only over http and https', () => {
  for (const protocol of ['http:', 'https:']) {
    const { calls, elements } = runClient(protocol);
    assert.deepEqual(calls.intervals, [30000]);
    assert.deepEqual(calls.fetches, ['http://127.0.0.1:8767/api/hub/version?slug=my-proj']);
    assert.equal(elements['hub-open-link'].hidden, true);
  }
  const other = runClient('about:');
  assert.deepEqual(other.calls.intervals, []);
  assert.deepEqual(other.calls.fetches, []);
});

test('page reloads when the hub version changes, errors are shown', async () => {
  const v1 = { status: 200, body: { built_at: 'a', signature: 's1' } };
  const v2 = { status: 200, body: { built_at: 'b', signature: 's2' } };
  const { calls, elements } = runClient('http:', { responses: [v1, v1, { status: 503, body: {} }, v2] });
  await settle();
  calls.tick(); await settle();
  assert.equal(calls.reloads, 0);
  calls.tick(); await settle();
  assert.match(elements['hub-version-status'].textContent, /HTTP 503/);
  calls.tick(); await settle();
  assert.equal(calls.reloads, 1);
});

test('rendered cockpit carries the polling script and the hub link', t => {
  const data = cockpitData(t);
  data.hubSlug = 'my-proj';
  const html = render(data);
  assert.ok(html.includes(fresh.getFreshnessScript()));
  assert.match(html, /href="http:\/\/127\.0\.0\.1:8767\/hub\/my-proj" hidden>Otwórz w hubie \(zawsze aktualne\)<\/a>/);
  data.hubSlug = null;
  assert.match(render(data), /Projekt poza rejestrem huba/);
});

test('hub slug comes from --hub-slug or from the registry by path', t => {
  const root = tmpDir(t, 'cockpit-slug-');
  const hubDir = tmpDir(t, 'cockpit-hub-');
  assert.equal(fresh.resolveHubSlug(root, [], 'given'), 'given');
  assert.equal(fresh.resolveHubSlug(root, [], null, { JIT_HUB_DIR: hubDir }), null);
  fs.writeFileSync(path.join(hubDir, 'projects.json'), JSON.stringify({ version: 1, projects: [{ slug: 'reg-slug', path: root }] }));
  assert.equal(fresh.resolveHubSlug(root, [], null, { JIT_HUB_DIR: hubDir }), 'reg-slug');
  assert.equal(fresh.resolveHubSlug('/elsewhere', [{ path: root }], null, { JIT_HUB_DIR: hubDir }), 'reg-slug');
});

test('generator embeds the slug passed with --hub-slug', t => {
  const root = tmpDir(t, 'cockpit-build-');
  const out = path.join(tmpDir(t, 'cockpit-out-'), 'c.html');
  const builder = path.join(__dirname, 'build_state_template.js');
  const env = { ...process.env, JIT_HUB_DIR: tmpDir(t, 'cockpit-hubenv-') };
  execFileSync('node', [builder, root, '--out', out, '--hub-slug', 'from-flag'], { env, stdio: 'pipe' });
  assert.match(fs.readFileSync(out, 'utf-8'), /127\.0\.0\.1:8767\/hub\/from-flag/);
});
