// Worktree activity: data from a real tmp repository with two worktrees, and the overview card.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { collect } = require('./collect');
const { render } = require('./render');
const { parsePorcelain } = require('./worktrees');
const { renderOverview } = require('./render_overview');

const GIT_ENV = { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 't@example.test', GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 't@example.test' };

function git(cwd, args, date) {
  const env = date ? { ...GIT_ENV, GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date } : GIT_ENV;
  return execFileSync('git', args, { cwd, env, encoding: 'utf-8' });
}

function commit(cwd, file, subject, date) {
  fs.writeFileSync(path.join(cwd, file), subject);
  git(cwd, ['add', file]);
  git(cwd, ['commit', '-q', '-m', subject], date);
}

function repoWithWorktrees(t) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-wt-')));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const main = path.join(base, 'main');
  fs.mkdirSync(path.join(main, '.planning'), { recursive: true });
  git(main, ['init', '-q', '-b', 'master']);
  commit(main, 'a.txt', 'initial commit', '2026-01-01T10:00:00+00:00');
  git(main, ['worktree', 'add', '-q', '-b', 'feat-alpha', path.join(base, 'wt-alpha')]);
  git(main, ['worktree', 'add', '-q', '-b', 'feat-beta', path.join(base, 'wt-beta')]);
  commit(path.join(base, 'wt-alpha'), 'b.txt', 'alpha work', '2026-02-01T10:00:00+00:00');
  commit(path.join(base, 'wt-beta'), 'c.txt', 'beta <b>work</b>', '2026-03-01T10:00:00+00:00');
  fs.writeFileSync(path.join(base, 'wt-alpha', 'dirty.txt'), 'uncommitted');
  return { base, main };
}

test('worktrees are listed newest first with commit, branch and dirty count', t => {
  const { base, main } = repoWithWorktrees(t);
  const data = collect(main);
  assert.equal(data.worktreesError, null);
  assert.deepEqual(data.worktrees.map(w => w.branch), ['feat-beta', 'feat-alpha', 'master']);
  const [beta, alpha, master] = data.worktrees;
  assert.equal(beta.path, path.join(base, 'wt-beta'));
  assert.equal(beta.last_commit_subject, 'beta <b>work</b>');
  assert.equal(Date.parse(beta.last_commit_at), Date.parse('2026-03-01T10:00:00Z'));
  assert.match(beta.head, /^[0-9a-f]{40}$/);
  assert.equal(beta.dirty_count, 0);
  assert.equal(alpha.dirty_count, 1);
  assert.equal(master.last_commit_subject, 'initial commit');
  assert.equal(data.newestActivity.branch, 'feat-beta');
  assert.equal(data.newestActivity.head, beta.head);
});

test('overview renders the Galezie robocze card with escaped branch data', t => {
  const { main } = repoWithWorktrees(t);
  const html = render(collect(main));
  assert.match(html, /<h2>Gałęzie robocze<\/h2>/);
  assert.match(html, /feat-alpha/);
  assert.match(html, /feat-beta/);
  assert.match(html, /beta &lt;b&gt;work&lt;\/b&gt;/);
  assert.match(html, /1 zmian/);
});

test('non-git project has no worktrees and no card', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-nogit-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const data = collect(root);
  assert.deepEqual(data.worktrees, []);
  assert.equal(data.newestActivity, null);
  assert.doesNotMatch(render(data), /Gałęzie robocze/);
});

test('porcelain parser handles detached and bare entries', () => {
  const entries = parsePorcelain('worktree /r\nbare\n\nworktree /r/wt\nHEAD abc\ndetached\n\n');
  assert.equal(entries.length, 2);
  assert.equal(entries[0].bare, true);
  assert.equal(entries[1].detached, true);
  assert.equal(entries[1].branch, null);
  assert.equal(entries[1].head, 'abc');
});

test('card shows at most 8 worktrees and collapses the rest', () => {
  const worktrees = Array.from({ length: 10 }, (_, i) => ({ path: `/p/${i}`, branch: `b-${i}`, head: 'f'.repeat(40), last_commit_at: null, last_commit_subject: null, dirty_count: 0, error: null }));
  const data = { state: { phase: '', doneCount: 0, totalCount: 0, raw: '', reportedProgress: null, milestones: [] }, git: {}, architectureMeta: { source: '' }, architecture: '', worktrees, worktreesError: null };
  const html = renderOverview(data);
  const [visible, collapsed] = html.split('<details>');
  assert.equal((visible.match(/class="worktree"/g) || []).length, 8);
  assert.match(collapsed, /Pozostałe \(2\)/);
  assert.match(collapsed, /b-9/);
});
