// Regression coverage for document-first cockpit rendering.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { collect } = require('./collect');
const { render } = require('./render');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-test-'));
  fs.mkdirSync(path.join(root, '.planning'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}
function put(root, file, text) { fs.writeFileSync(path.join(root, file), text); }

test('GSD state remains readable without STATE checkboxes', t => {
  const root = fixture(t);
  put(root, '.planning/STATE.md', '---\nstatus: completed\n---\n## Project State\n**Current focus:** Edge agent fixes\nPhase: 8.2 of 11\nStatus: shipped\nProgress: 98%\n## Decisions\nKeep deterministic execution.');
  const data = collect(root);
  assert.equal(data.state.phase, 'Edge agent fixes');
  assert.match(data.state.raw, /Keep deterministic execution/);
  assert.match(render(data), /id="pane-overview"/);
  assert.match(render(data), /Keep deterministic execution/);
});

test('ROADMAP supplies tasks and partial phases without inventing completion', t => {
  const root = fixture(t);
  put(root, '.planning/STATE.md', '## Project State\nStatus: in progress');
  put(root, '.planning/ROADMAP.md', '## Phases\n- [x] Phase 1: Compiler\n- [~] Phase 2: Composition\n- [ ] Phase 3: Monitoring');
  const data = collect(root);
  assert.equal(data.state.totalCount, 3);
  assert.equal(data.state.doneCount, 1);
  assert.equal(data.state.partialCount, 1);
  assert.equal(data.state.milestones.length, 3);
  assert.equal(data.state.allTasks[1].source, '.planning/ROADMAP.md');
});

test('starter architecture is replaced by a sourced documentation diagram', t => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, 'docs'));
  put(root, '.planning/ARCHITECTURE.mmd', 'graph TD\nUI["UI / Web Client"] --> API');
  put(root, 'docs/02_architecture.md', '# Architecture\n```mermaid\nflowchart LR\n Hub --> Insight\n Insight --> Registry\n```');
  const data = collect(root);
  assert.match(data.architecture, /Hub --> Insight/);
  assert.equal(data.architectureMeta.source, 'docs/02_architecture.md');
  assert.doesNotMatch(data.architecture, /UI \/ Web Client/);
});

test('rendered UI is emoji-free and JSON cannot terminate script tags', t => {
  const root = fixture(t);
  put(root, '.planning/STATE.md', '## State 🚀\n- [ ] Fix 📋 </script><img src=x onerror=alert(1)>');
  const html = render(collect(root));
  assert.doesNotMatch(html, /[\p{Extended_Pictographic}\p{Regional_Indicator}\uFE0F]/u);
  assert.doesNotMatch(html, /<img src=x/);
  const scripts = [...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)];
  for (const [, code] of scripts) {
    if (code.trim().startsWith('{')) JSON.parse(code);
    // Parse only: fixture JavaScript is compiled, never executed.
    else new Function(code);
  }
});

test('result file presence is not a runtime PASS certificate', t => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, '.planning/orchestration'));
  put(root, '.planning/orchestration/TASK-W1.md', '# Pending feature');
  put(root, '.planning/orchestration/RESULT-W2.md', '# Findings\nNot tested.');
  const data = collect(root);
  assert.notEqual(data.orchestration.results.W2.status, 'PASS');
  const html = render(data);
  assert.doesNotMatch(html, /ZWERYFIKOWANYCH FAL|Wynik PASS/);
});

test('credentials from local file render in overview, blocked when state.html is tracked', t => {
  const root = fixture(t);
  put(root, '.planning/STATE.md', '## Project State\n**Current focus:** demo');
  put(root, '.planning/credentials.local.json', JSON.stringify([{ label: 'Demo', url: 'https://x.test', user: 'zarzad', pass: 'S3cret-pass' }]));
  let html = render(collect(root));
  assert.match(html, /S3cret-pass/);
  assert.match(html, /zarzad/);
  const { execFileSync } = require('node:child_process');
  execFileSync('git', ['init', '-q', root]);
  put(root, '.planning/state.html', 'x');
  execFileSync('git', ['-C', root, 'add', '-f', '.planning/state.html']);
  html = render(collect(root));
  assert.doesNotMatch(html, /S3cret-pass/);
  assert.match(html, /śledzony przez gita/);
});

test('credentials resolved from env file', t => {
  const root = fixture(t);
  put(root, 'deploy.env', 'U=wojciech\nP="from-env-77"\n');
  put(root, '.planning/credentials.local.json', JSON.stringify([{ label: 'Env', env_file: path.join(root, 'deploy.env'), user_var: 'U', pass_var: 'P' }]));
  const html = render(collect(root));
  assert.match(html, /from-env-77/);
  assert.match(html, /wojciech/);
});

test('links from .planning/links.json render as grouped clickable addresses', t => {
  const root = fixture(t);
  put(root, '.planning/STATE.md', '## Project State\n**Current focus:** demo');
  put(root, '.planning/links.json', JSON.stringify([
    { group: 'Demo', label: 'Start', url: 'https://demo.test/', note: 'basic auth' },
    { group: 'Landingi', label: 'Form', url: 'https://l.test/form' },
  ]));
  const html = render(collect(root));
  assert.match(html, /<h2>Adresy<\/h2>/);
  assert.match(html, /href="https:\/\/demo\.test\/"/);
  assert.match(html, /Landingi/);
  put(root, '.planning/links.json', '{bad');
  assert.match(render(collect(root)), /links\.json nie jest poprawnym JSON/);
});
