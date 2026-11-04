// "Czat projektu" tab: the live chat runs only when the hub serves the page (/hub/<slug>, meta tags with the
// endpoint and CSRF token); a file:// cockpit shows a button to the hub chat. No secrets are embedded here.
const { esc } = require('./html');
const { icon } = require('./presentation');
const { hubUrl } = require('./freshness');
const { QUICK_PROMPTS, CHAT_TAB_HASH } = require('./hub_chat');

const HUB_HOME_URL = hubUrl('').replace(/\/$/, '');
const OPEN_HUB_CHAT_LABEL = 'Otwórz czat w hubie';

function hubChatUrl(slug) {
  return slug ? hubUrl(slug) + CHAT_TAB_HASH : HUB_HOME_URL;
}

function renderFallback(data) {
  const reason = data.hubSlug
    ? 'Ten kokpit otwarto z pliku, więc nie rozmawia z modelem. Czat działa w hubie, który czyta aktualne pliki projektu i trzyma historię rozmowy.'
    : 'Projekt nie jest w rejestrze huba (jit init albo jit hub scan), więc hub nie ma dla niego czatu.';
  return `<section class="card chat-fallback" id="chat-file-fallback"><div class="card-heading"><div><span class="eyebrow">Czat w hubie</span><h2>Rozmowa o projekcie</h2></div></div>
    <p id="chat-fallback-reason">${esc(reason)}</p>
    <a class="btn btn-primary" id="chat-open-hub" href="${esc(hubChatUrl(data.hubSlug))}">${icon('chat')}<span>${data.hubSlug ? OPEN_HUB_CHAT_LABEL : 'Otwórz hub'}</span></a></section>`;
}

function renderQuickPrompts() {
  return QUICK_PROMPTS.map(prompt => `<button class="chip-btn" type="button" data-prompt="${esc(prompt.text)}" onclick="sendQuickPrompt(this.dataset.prompt)">${esc(prompt.label)}</button>`).join('');
}

function renderHubPanel() {
  return `<section class="notice" id="chat-hub-notice">Czat huba: serwer składa kontekst z plików projektu (STATE, ROADMAP, README, architektura, notatka projektu, statystyki) i wysyła go do skonfigurowanego modelu. Odpowiedzi to porady, nie zmiany w plikach. Pod odpowiedzią widać źródła użyte w kontekście.</section>
  <div class="chat-layout"><div class="chat-header"><h2>Rozmowa o projekcie</h2><div class="header-actions"><span class="pill mono" id="chat-model-badge">Model: nieznany do pierwszej odpowiedzi</span></div></div>
  <div class="chat-messages" id="chat-messages-container" aria-live="polite"></div>
  <div class="chat-quick-chips">${renderQuickPrompts()}</div>
  <div class="chat-input-bar"><textarea class="chat-input" id="chat-user-input" aria-label="Wiadomość o projekcie" placeholder="Zapytaj o projekt…" rows="2" onkeydown="handleChatKeyDown(event)"></textarea><button class="btn btn-primary" id="chat-send-btn" type="button" onclick="sendChatMessage()">Wyślij</button></div></div>`;
}

function renderChatTab(data) {
  return `${renderFallback(data)}<div id="chat-hub-panel" hidden>${renderHubPanel()}</div>`;
}

module.exports = { renderChatTab, hubChatUrl, OPEN_HUB_CHAT_LABEL };
