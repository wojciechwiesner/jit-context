// Hub actions client: runs list via GET <runs>?slug= with adaptive polling, POST <actions> after a confirm
// dialog, report viewer via GET <report>?run=. Runs only when the hub served the page; never renders HTML from
// a run or a report and never invents a status: request failures are shown as errors with their reason.
const { actionsHelpersSource } = require('./hub_actions');
const { markdownHelpersSource } = require('./safe_markdown');

const ACTIONS_REQUEST_TIMEOUT_MS = 20000;
const CSRF_HEADER = 'X-JIT-Hub-CSRF';

function getActionsScript() {
  return `
const ACTIONS_REQUEST_TIMEOUT_MS = ${ACTIONS_REQUEST_TIMEOUT_MS};
${actionsHelpersSource()}
${markdownHelpersSource()}
const hubActions = { config: readHubActionsConfig(document), runs: [], failures: 0, timer: null, delay: null,
  started: false, polling: false, pending: null, posting: false };
hubActions.mode = actionsMode(window.location.protocol, hubActions.config);
function actionsEl(id) { return document.getElementById(id); }
function showActionsMode() {
  if (hubActions.mode === 'hub') {
    actionsEl('actions-file-fallback').hidden = true;
    actionsEl('actions-hub-panel').hidden = false;
  } else if (hubActions.mode === 'unavailable') {
    actionsEl('actions-fallback-reason').textContent = 'Ta strona nie pochodzi z huba (brak konfiguracji akcji w nagłówku), więc nie uruchamia akcji. Otwórz akcje w hubie.';
  }
}
async function actionsFetchJson(url, options) {
  const response = await fetch(url, Object.assign({ cache: 'no-store', signal: AbortSignal.timeout(ACTIONS_REQUEST_TIMEOUT_MS) }, options || {}));
  let payload = null;
  try { payload = await response.json(); } catch (error) { payload = { error: 'HTTP ' + response.status + ', odpowiedź nie jest JSON' }; }
  return { status: response.status, ok: response.ok, payload: payload || {} };
}
function renderActionRuns() {
  const list = actionsEl('action-runs-list');
  list.textContent = '';
  if (!hubActions.runs.length) list.appendChild(runTextNode(document, 'p', 'muted', 'Brak uruchomień dla tego projektu. Wybierz akcję powyżej.'));
  hubActions.runs.forEach(run => list.appendChild(createRunNode(document, run)));
  const busy = activeActionIds(hubActions.runs);
  HUB_ACTIONS.forEach(action => { const button = actionsEl('action-btn-' + action.id); if (button) button.disabled = busy.indexOf(action.id) >= 0; });
}
function scheduleActionPoll() {
  if (hubActions.timer) clearTimeout(hubActions.timer);
  hubActions.delay = nextPollDelay(hubActions.runs, hubActions.failures);
  hubActions.timer = setTimeout(pollActionRuns, hubActions.delay);
}
function runsStatusText(payload) {
  const parts = ['Odświeżono ' + new Date().toLocaleTimeString('pl-PL'), 'aktywne: ' + activeActionIds(hubActions.runs).length];
  if (payload.max_concurrent) parts.push('limit równoległych: ' + payload.max_concurrent);
  if (payload.unreadable) parts.push('nieczytelne pliki uruchomień: ' + payload.unreadable);
  return parts.join(' · ');
}
async function pollActionRuns() {
  if (hubActions.mode !== 'hub' || hubActions.polling) return;
  hubActions.polling = true;
  const url = hubActions.config.runs + '?slug=' + encodeURIComponent(hubActions.config.slug);
  const status = actionsEl('action-runs-status');
  try {
    const reply = await actionsFetchJson(url);
    if (!reply.ok) throw new Error(reply.payload.error || 'HTTP ' + reply.status);
    hubActions.runs = Array.isArray(reply.payload.runs) ? reply.payload.runs : [];
    hubActions.failures = 0;
    renderActionRuns();
    status.textContent = runsStatusText(reply.payload);
  } catch (error) {
    hubActions.failures += 1;
    status.textContent = 'Nie wczytano listy uruchomień z ' + url + ': ' + error.message + '. Lista poniżej może być nieaktualna; ponowię za ' + Math.round(nextPollDelay(hubActions.runs, hubActions.failures) / 1000) + ' s.';
  }
  hubActions.polling = false;
  scheduleActionPoll();
}
function askActionRun(actionId) {
  if (hubActions.mode !== 'hub') return;
  hubActions.pending = actionId;
  actionsEl('action-confirm-title').textContent = 'Uruchomić: ' + actionLabel(actionId) + '?';
  actionsEl('action-confirm-text').textContent = actionConfirmText(actionId, hubActions.config.slug);
  const error = actionsEl('action-confirm-error');
  error.hidden = true; error.textContent = '';
  actionsEl('action-confirm-run').disabled = false;
  actionsEl('action-confirm-modal').classList.add('open');
}
function closeActionConfirm(event) {
  if (event && event.target && event.target.id !== 'action-confirm-modal') return;
  actionsEl('action-confirm-modal').classList.remove('open');
  hubActions.pending = null;
}
async function postActionRun(actionId) {
  try {
    return await actionsFetchJson(hubActions.config.actions, { method: 'POST',
      headers: { 'Content-Type': 'application/json', '${CSRF_HEADER}': hubActions.config.csrf },
      body: JSON.stringify({ slug: hubActions.config.slug, action: actionId }) });
  } catch (error) {
    return { ok: false, status: 0, payload: { error: 'Błąd połączenia z hubem: ' + error.message } };
  }
}
async function confirmActionRun() {
  const actionId = hubActions.pending;
  if (!actionId || hubActions.posting) return;
  hubActions.posting = true;
  const button = actionsEl('action-confirm-run');
  button.disabled = true; button.textContent = 'Uruchamiam…';
  const reply = await postActionRun(actionId);
  hubActions.posting = false; button.textContent = 'Uruchom model';
  if (reply.ok) { closeActionConfirm(); return pollActionRuns(); }
  const error = actionsEl('action-confirm-error');
  const prefix = reply.status === 409 ? 'Ta akcja już czeka albo trwa dla tego projektu. ' : '';
  error.textContent = prefix + (reply.status ? 'HTTP ' + reply.status + ': ' : '') + (reply.payload.error || 'brak opisu błędu');
  error.hidden = false;
  button.disabled = reply.status === 409;
  return pollActionRuns();
}
async function openRunReport(runId) {
  const viewer = actionsEl('action-report-viewer'); const body = actionsEl('action-report-body'); const meta = actionsEl('action-report-meta');
  viewer.hidden = false; body.textContent = '';
  actionsEl('action-report-title').textContent = 'Raport';
  meta.textContent = 'Wczytuję raport…';
  const url = hubActions.config.report + '?run=' + encodeURIComponent(runId);
  try {
    const reply = await actionsFetchJson(url);
    if (!reply.ok) throw new Error(reply.payload.error || 'HTTP ' + reply.status);
    const run = reply.payload.run || {};
    actionsEl('action-report-title').textContent = (run.label || actionLabel(run.action)) + ' · ' + runStatusLabel(run.status);
    meta.textContent = [runMetaText(run), 'plik: ' + reply.payload.path].concat(run.obsidian_path ? ['kopia: ' + run.obsidian_path] : []).join(' · ');
    renderSafeMarkdown(document, body, reply.payload.markdown || '');
  } catch (error) {
    meta.textContent = 'Nie wczytano raportu z ' + url + ': ' + error.message;
  }
  if (typeof viewer.scrollIntoView === 'function') viewer.scrollIntoView({ block: 'start' });
}
function closeRunReport() {
  actionsEl('action-report-viewer').hidden = true;
  actionsEl('action-report-body').textContent = '';
}
function handleRunsListClick(event) {
  const button = event.target && event.target.closest ? event.target.closest('.run-report-btn') : null;
  if (button) openRunReport(button.getAttribute('data-run-id'));
}
function loadHubActions() {
  if (hubActions.started) return; hubActions.started = true;
  showActionsMode();
  if (hubActions.mode !== 'hub') return;
  actionsEl('action-runs-list').addEventListener('click', handleRunsListClick);
  if (window.location.hash === ACTIONS_TAB_HASH && typeof switchTab === 'function') switchTab('actions');
  return pollActionRuns();
}
if (typeof document.addEventListener === 'function') document.addEventListener('DOMContentLoaded', loadHubActions);
`;
}

module.exports = { getActionsScript, ACTIONS_REQUEST_TIMEOUT_MS };
