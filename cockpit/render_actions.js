// "Akcje" tab: four read-only agent runs (hub.actions), a runs list with status polling and a report viewer.
// The live panel works only when the hub serves the page (/hub/<slug>, meta tags with endpoints and CSRF);
// a file:// cockpit shows a button to the hub. Report text is rendered later in the browser with textContent.
const { esc } = require('./html');
const { icon } = require('./presentation');
const { hubUrl } = require('./freshness');
const { HUB_ACTIONS, ACTIONS_TAB_HASH } = require('./hub_actions');

const HUB_HOME_URL = hubUrl('').replace(/\/$/, '');
const OPEN_HUB_ACTIONS_LABEL = 'Otwórz akcje w hubie';
const COST_WARNING = 'Każda akcja uruchamia model (claude -p) i zużywa tokeny, więc może kosztować. Przed startem pokażemy potwierdzenie.';

function hubActionsUrl(slug) {
  return slug ? hubUrl(slug) + ACTIONS_TAB_HASH : HUB_HOME_URL;
}

function renderFallback(data) {
  const reason = data.hubSlug
    ? 'Ten kokpit otwarto z pliku, więc nie uruchamia akcji. Akcje działają w hubie, który kolejkuje uruchomienia modelu i trzyma raporty.'
    : 'Projekt nie jest w rejestrze huba (jit init albo jit hub scan), więc hub nie ma dla niego akcji.';
  return `<section class="card chat-fallback" id="actions-file-fallback"><div class="card-heading"><div><span class="eyebrow">Akcje w hubie</span><h2>Audyty i badania projektu</h2></div></div>
    <p id="actions-fallback-reason">${esc(reason)}</p>
    <a class="btn btn-primary" id="actions-open-hub" href="${esc(hubActionsUrl(data.hubSlug))}">${icon('actions')}<span>${data.hubSlug ? OPEN_HUB_ACTIONS_LABEL : 'Otwórz hub'}</span></a></section>`;
}

function renderActionButtons() {
  return HUB_ACTIONS.map(action => `<div class="action-card"><button class="btn btn-primary action-btn" type="button" id="action-btn-${esc(action.id)}" data-action="${esc(action.id)}" onclick="askActionRun(this.dataset.action)">${icon('actions')}<span>${esc(action.label)}</span></button><p class="action-desc">${esc(action.description)}</p></div>`).join('');
}

function renderConfirmModal() {
  return `<div class="modal-backdrop" id="action-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="action-confirm-title" onclick="closeActionConfirm(event)"><div class="modal-card">
    <div class="modal-header"><h2 id="action-confirm-title">Uruchomić akcję?</h2></div>
    <div class="modal-body"><p id="action-confirm-text"></p><p class="notice" id="action-confirm-cost">Uruchamia model i może kosztować tokeny. Model tylko czyta pliki projektu i źródła w sieci; niczego nie zmienia w repozytorium.</p><p class="run-error" id="action-confirm-error" hidden></p></div>
    <div class="modal-footer"><button class="btn" type="button" onclick="closeActionConfirm()">Anuluj</button><button class="btn btn-primary" type="button" id="action-confirm-run" onclick="confirmActionRun()">Uruchom model</button></div></div></div>`;
}

function renderHubPanel() {
  return `<section class="notice" id="actions-hub-notice">${esc(COST_WARNING)} Uruchomienia ponad limit serwera czekają w kolejce. Raport trafia do huba i do notatki projektu.</section>
  <section class="card"><div class="card-heading"><div><span class="eyebrow">Agent tylko do odczytu</span><h2>Uruchom akcję</h2></div></div><div class="actions-grid">${renderActionButtons()}</div></section>
  <section class="card"><div class="card-heading"><div><span class="eyebrow">Historia</span><h2>Uruchomienia</h2></div><div class="header-actions"><button class="btn" type="button" onclick="pollActionRuns()">Odśwież</button></div></div>
    <p class="source-meta" id="action-runs-status">Wczytuję listę uruchomień…</p><div class="runs-list" id="action-runs-list" aria-live="polite"></div></section>
  <section class="card" id="action-report-viewer" hidden><div class="card-heading"><div><span class="eyebrow">Raport</span><h2 id="action-report-title">Raport</h2></div><div class="header-actions"><button class="btn" type="button" onclick="closeRunReport()">Zamknij raport</button></div></div>
    <p class="source-meta" id="action-report-meta"></p><div class="document-body report-body" id="action-report-body"></div></section>
  ${renderConfirmModal()}`;
}

function renderActionsTab(data) {
  return `${renderFallback(data)}<div id="actions-hub-panel" hidden>${renderHubPanel()}</div>`;
}

module.exports = { renderActionsTab, hubActionsUrl, OPEN_HUB_ACTIONS_LABEL, COST_WARNING };
