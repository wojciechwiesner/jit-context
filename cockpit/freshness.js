// Freshness UX: build stamp in the header, notice about newer worktree commits, hub link or version polling.
// The cockpit is one static file opened either as file:// or served by the hub, so the http/file decision is
// made in the browser: polling runs only over http(s), file:// shows a link to the always-fresh hub copy.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { esc } = require('./html');

const HUB_ORIGIN = 'http://127.0.0.1:8767';
const POLL_INTERVAL_MS = 30000;
const HUB_LINK_LABEL = 'Otwórz w hubie (zawsze aktualne)';
const REGISTRY_FILE = 'projects.json';

function formatTime(iso) {
  const ms = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(ms) ? 'brak daty' : new Date(ms).toLocaleString('pl-PL');
}

function buildSource(data) {
  const head = (data.git && data.git.log && data.git.log[0]) || null;
  return { isRepo: Boolean(data.git && data.git.isRepo), branch: data.git ? data.git.branch : null,
    sha: head ? head.hash : null, committedAt: head ? head.iso : null };
}

function buildStampText(data) {
  const source = buildSource(data);
  const origin = source.isRepo ? `${source.branch || 'HEAD'} @ ${source.sha || 'bez commita'}` : 'brak repozytorium git';
  return `Zbudowano: ${formatTime(data.generatedAt)}, źródło: ${origin}`;
}

// Newest worktree whose last commit is strictly newer than the commit the cockpit was built from.
function newerWorktree(data) {
  const source = buildSource(data);
  if (!source.isRepo) return null;
  const sourceMs = source.committedAt ? Date.parse(source.committedAt) : -Infinity;
  const newer = (data.worktrees || []).filter(w => {
    const ms = w.last_commit_at ? Date.parse(w.last_commit_at) : NaN;
    return !Number.isNaN(ms) && ms > sourceMs;
  });
  newer.sort((a, b) => Date.parse(b.last_commit_at) - Date.parse(a.last_commit_at));
  return newer[0] || null;
}

function hubUrl(slug) {
  return `${HUB_ORIGIN}/hub/${encodeURIComponent(slug)}`;
}

function renderFreshnessStamp(data) {
  const link = data.hubSlug
    ? `<a class="btn hub-link" id="hub-open-link" href="${esc(hubUrl(data.hubSlug))}" hidden>${HUB_LINK_LABEL}</a>`
    : '<span class="pill" id="hub-open-link" hidden>Projekt poza rejestrem huba (jit hub scan)</span>';
  return `<span class="pill mono build-stamp" id="build-stamp">${esc(buildStampText(data))}</span>`
    + `<span class="source-meta" id="hub-version-status" role="status"></span>${link}`;
}

function renderNewerNotice(data) {
  const worktree = newerWorktree(data);
  if (!worktree) return '';
  const branch = worktree.branch || (worktree.detached ? 'odłączony HEAD' : 'gałąź nieznana');
  const subject = worktree.last_commit_subject ? `: ${worktree.last_commit_subject}` : '';
  return `<div class="freshness-notice" role="status" id="freshness-notice">Nowszy commit w gałęzi roboczej `
    + `<strong class="mono">${esc(branch)}</strong> (${esc(formatTime(worktree.last_commit_at))})${esc(subject)}. `
    + `Ten widok zbudowano ze źródła ${esc(buildSource(data).branch || 'HEAD')} i nie zawiera tej zmiany.</div>`;
}

// Registry slug for the hub URL: explicit value from the refresher, else a lookup by path in projects.json.
function resolveHubSlug(root, worktrees, explicit, env = process.env) {
  if (explicit) return explicit;
  const hubDir = env.JIT_HUB_DIR || path.join(env.HERMES_HOME || path.join(os.homedir(), '.hermes'), 'state', 'jit-hub');
  let projects;
  try {
    projects = JSON.parse(fs.readFileSync(path.join(hubDir, REGISTRY_FILE), 'utf-8')).projects;
  } catch {
    return null;
  }
  const real = p => { try { return fs.realpathSync(p); } catch { return path.resolve(p); } };
  const candidates = new Set([real(root), ...(worktrees || []).slice(0, 1).map(w => real(w.path))]);
  const entry = Array.isArray(projects) ? projects.find(p => p && p.path && candidates.has(real(p.path))) : null;
  return entry ? entry.slug : null;
}

function getFreshnessScript() {
  return `
(function () {
  var POLL_MS = ${POLL_INTERVAL_MS};
  var data = JSON.parse(document.getElementById('cockpit-data-json').textContent);
  var protocol = window.location.protocol;
  if (protocol === 'file:') {
    var link = document.getElementById('hub-open-link');
    if (link) link.hidden = false;
    return;
  }
  if (protocol !== 'http:' && protocol !== 'https:') return;
  var status = document.getElementById('hub-version-status');
  function setStatus(text) { if (status) status.textContent = text; }
  var match = window.location.pathname.match(/^\\/hub\\/([^/]+)/);
  var slug = match ? decodeURIComponent(match[1]) : data.hubSlug;
  if (!slug) { setStatus('Brak sluga projektu w hubie: automatyczne odświeżanie wyłączone'); return; }
  var url = window.location.origin + '/api/hub/version?slug=' + encodeURIComponent(slug);
  var baseline = null;
  function versionKey(payload) {
    if (payload && typeof payload.version === 'string') return payload.version;
    if (!payload || (payload.signature == null && payload.built_at == null)) return null;
    return JSON.stringify([payload.signature, payload.built_at]);
  }
  function check() {
    fetch(url, { cache: 'no-store' }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    }).then(function (payload) {
      var key = versionKey(payload);
      if (key === null) throw new Error('odpowiedź bez wersji');
      if (baseline === null) baseline = key;
      else if (key !== baseline) { window.location.reload(); return; }
      setStatus('');
    }).catch(function (error) { setStatus('Hub: nie sprawdzono wersji (' + error.message + ')'); });
  }
  check();
  setInterval(check, POLL_MS);
})();
`;
}

module.exports = { POLL_INTERVAL_MS, HUB_LINK_LABEL, buildStampText, newerWorktree, hubUrl, renderFreshnessStamp,
  renderNewerNotice, resolveHubSlug, getFreshnessScript, formatTime };
