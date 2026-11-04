// Hub actions helpers shared by the generator (node) and the browser script (injected with Function#toString).
// Names are prefixed (actions/run) because every cockpit script shares one global scope with the chat script.
// Run rows are built with textContent only; nothing from a run record or a report reaches innerHTML.
const ACTIONS_ENDPOINT_META = 'jit-hub-actions';
const ACTIONS_RUNS_META = 'jit-hub-runs';
const ACTIONS_REPORT_META = 'jit-hub-report';
const ACTIONS_SLUG_META = 'jit-hub-slug';
const ACTIONS_CSRF_META = 'jit-hub-csrf';
const ACTIONS_TAB_HASH = '#actions';
const ACTIONS_ACTIVE_POLL_MS = 3000;
const ACTIONS_IDLE_POLL_MS = 30000;
const ACTIONS_MAX_BACKOFF_MS = 60000;
const ACTION_RUN_TIMEOUT_MINUTES = 30;
// Ids and labels match src/hub/actions/__init__.py ACTION_LABELS (checked by test_hub_actions_ui.py).
const HUB_ACTIONS = [
  { id: 'audit360', label: 'Audyt 360', description: 'Kod, architektura, testy, dokumentacja i stan prac z dowodami plik:linia.' },
  { id: 'security', label: 'Audyt bezpieczeństwa', description: 'Sekrety, konfiguracja, zależności i słabe punkty w kodzie.' },
  { id: 'market', label: 'Badanie rynku', description: 'Konkurencja, grupy odbiorców i trendy ze źródłami w sieci.' },
  { id: 'monetization', label: 'Monetyzacja', description: 'Modele przychodu i ceny porównywalnych produktów ze źródłami.' },
];
const RUN_STATUS_LABELS = { queued: 'w kolejce', running: 'w toku', succeeded: 'gotowe', failed: 'błąd',
  timeout: 'przekroczony czas', interrupted: 'przerwane' };
const RUN_ACTIVE_STATUSES = ['queued', 'running'];

// {actions, runs, report, slug, csrf} from the meta tags the hub injects, or null outside the hub.
function readHubActionsConfig(doc) {
  function meta(name) {
    const node = doc.querySelector('meta[name="' + name + '"]');
    return node ? String(node.getAttribute('content') || '').trim() : '';
  }
  const config = { actions: meta(ACTIONS_ENDPOINT_META), runs: meta(ACTIONS_RUNS_META), report: meta(ACTIONS_REPORT_META),
    slug: meta(ACTIONS_SLUG_META), csrf: meta(ACTIONS_CSRF_META) };
  return config.actions && config.runs && config.report && config.slug && config.csrf ? config : null;
}

// 'hub' = live actions, 'file' = opened from disk, 'unavailable' = http page without the hub config.
function actionsMode(protocol, config) {
  if (protocol === 'file:') return 'file';
  if ((protocol === 'http:' || protocol === 'https:') && config) return 'hub';
  return 'unavailable';
}

function isActiveRun(run) {
  return Boolean(run) && RUN_ACTIVE_STATUSES.indexOf(run.status) >= 0;
}

// Action ids with a queued or running run: their buttons are disabled (the server answers 409 anyway).
function activeActionIds(runs) {
  const ids = [];
  (runs || []).forEach(run => { if (isActiveRun(run) && ids.indexOf(run.action) < 0) ids.push(run.action); });
  return ids;
}

// Fast polling while something runs, slow otherwise, exponential backoff after failed requests.
function nextPollDelay(runs, failures) {
  if (failures > 0) return Math.min(ACTIONS_MAX_BACKOFF_MS, ACTIONS_ACTIVE_POLL_MS * Math.pow(2, failures));
  return activeActionIds(runs).length ? ACTIONS_ACTIVE_POLL_MS : ACTIONS_IDLE_POLL_MS;
}

function runStatusLabel(status) {
  return RUN_STATUS_LABELS[status] || String(status || 'nieznany');
}

function actionLabel(actionId) {
  const found = HUB_ACTIONS.filter(action => action.id === actionId)[0];
  return found ? found.label : String(actionId || 'nieznana akcja');
}

function runTime(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleString('pl-PL') : '';
}

// "start ... · koniec ... · koszt ..." with missing values shown as missing, never guessed.
function runMetaText(run) {
  const parts = [];
  const started = runTime(run.started);
  const finished = runTime(run.finished);
  parts.push(started ? 'start: ' + started : 'utworzono: ' + (runTime(run.created) || 'brak danych'));
  if (finished) parts.push('koniec: ' + finished);
  if (typeof run.cost === 'number') parts.push('koszt: ' + run.cost.toFixed(4) + ' USD');
  else if (!isActiveRun(run)) parts.push('koszt: brak danych');
  const usage = run.usage || {};
  if (typeof usage.output_tokens === 'number') parts.push('tokeny wyjściowe: ' + usage.output_tokens);
  return parts.join(' · ');
}

function actionConfirmText(actionId, slug) {
  return 'Akcja „' + actionLabel(actionId) + '” uruchomi model (claude -p) w katalogu projektu ' + slug +
    ' w trybie tylko do odczytu. Potrwa do ' + ACTION_RUN_TIMEOUT_MINUTES + ' minut i zużyje tokeny, więc może kosztować. ' +
    'Raport zapisze się w hubie i w notatce projektu.';
}

function runTextNode(doc, tag, className, text) {
  const node = doc.createElement(tag);
  node.className = className;
  node.textContent = String(text);
  return node;
}

// One run row: label, status pill, times and cost, error, and a report button when the report exists.
function createRunNode(doc, run) {
  const row = doc.createElement('div');
  row.className = 'run-row run-' + (RUN_STATUS_LABELS[run.status] ? run.status : 'other');
  row.setAttribute('data-run-id', String(run.id || ''));
  const head = doc.createElement('div');
  head.className = 'run-head';
  head.appendChild(runTextNode(doc, 'strong', 'run-label', run.label || actionLabel(run.action)));
  head.appendChild(runTextNode(doc, 'span', 'run-status status-' + (RUN_STATUS_LABELS[run.status] ? run.status : 'other'), runStatusLabel(run.status)));
  row.appendChild(head);
  row.appendChild(runTextNode(doc, 'div', 'run-meta', runMetaText(run)));
  if (run.error) row.appendChild(runTextNode(doc, 'div', 'run-error', run.error));
  if (run.mirror_error) row.appendChild(runTextNode(doc, 'div', 'run-error', run.mirror_error));
  if (run.report_path) {
    const button = runTextNode(doc, 'button', 'btn btn-sm run-report-btn', 'Pokaż raport');
    button.setAttribute('type', 'button');
    button.setAttribute('data-run-id', String(run.id || ''));
    row.appendChild(button);
  }
  return row;
}

const ACTIONS_BROWSER_HELPERS = [readHubActionsConfig, actionsMode, isActiveRun, activeActionIds, nextPollDelay,
  runStatusLabel, actionLabel, runTime, runMetaText, actionConfirmText, runTextNode, createRunNode];

// Constants first, then the functions: the browser copy runs the exact code the node tests exercise.
function actionsHelpersSource() {
  const constants = { ACTIONS_ENDPOINT_META, ACTIONS_RUNS_META, ACTIONS_REPORT_META, ACTIONS_SLUG_META, ACTIONS_CSRF_META,
    ACTIONS_TAB_HASH, ACTIONS_ACTIVE_POLL_MS, ACTIONS_IDLE_POLL_MS, ACTIONS_MAX_BACKOFF_MS, ACTION_RUN_TIMEOUT_MINUTES,
    HUB_ACTIONS, RUN_STATUS_LABELS, RUN_ACTIVE_STATUSES };
  const lines = Object.entries(constants).map(([name, value]) => `const ${name} = ${JSON.stringify(value)};`);
  return lines.concat(ACTIONS_BROWSER_HELPERS.map(fn => fn.toString())).join('\n');
}

module.exports = { ACTIONS_ENDPOINT_META, ACTIONS_RUNS_META, ACTIONS_REPORT_META, ACTIONS_TAB_HASH, ACTIONS_ACTIVE_POLL_MS,
  ACTIONS_IDLE_POLL_MS, ACTIONS_MAX_BACKOFF_MS, HUB_ACTIONS, RUN_STATUS_LABELS, readHubActionsConfig, actionsMode,
  isActiveRun, activeActionIds, nextPollDelay, runStatusLabel, actionLabel, runMetaText, actionConfirmText, createRunNode,
  actionsHelpersSource };
