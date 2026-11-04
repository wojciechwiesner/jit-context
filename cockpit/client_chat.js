// Hub chat client: history from GET <endpoint>?slug=, turns via POST <endpoint> with the page's CSRF token.
// Runs only when the hub served the page; file:// keeps the static button. Never renders model HTML and
// never invents a reply: upstream and network failures are shown as errors with their status.
const { MAX_SENT_TURNS, MAX_SENT_CHARS, browserHelpersSource } = require('./hub_chat');

const CHAT_TIMEOUT_MS = 100000;
const CSRF_HEADER = 'X-JIT-Hub-CSRF';

function getChatScript() {
  return `
const HUB_CHAT_MAX_TURNS = ${MAX_SENT_TURNS};
const HUB_CHAT_MAX_CHARS = ${MAX_SENT_CHARS};
const HUB_CHAT_TIMEOUT_MS = ${CHAT_TIMEOUT_MS};
${browserHelpersSource()}
const hubChat = { config: readHubChatConfig(document), records: [], busy: false, started: false };
hubChat.mode = chatMode(window.location.protocol, hubChat.config);
function chatContainer() { return document.getElementById('chat-messages-container'); }
function appendChatRecord(record) {
  const container = chatContainer(); const node = createMessageNode(document, record);
  container.appendChild(node); container.scrollTop = container.scrollHeight; return node;
}
function setChatBadge(text) { const badge = document.getElementById('chat-model-badge'); if (badge) badge.textContent = text; }
function showChatMode() {
  if (hubChat.mode === 'hub') {
    document.getElementById('chat-file-fallback').hidden = true;
    document.getElementById('chat-hub-panel').hidden = false;
  } else if (hubChat.mode === 'unavailable') {
    document.getElementById('chat-fallback-reason').textContent = 'Ta strona nie pochodzi z huba (brak konfiguracji czatu w nagłówku), więc nie rozmawia z modelem. Otwórz czat w hubie.';
  }
}
async function loadChatHistory() {
  const url = hubChat.config.endpoint + '?slug=' + encodeURIComponent(hubChat.config.slug);
  try {
    const response = await fetch(url, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'HTTP ' + response.status);
    hubChat.records = Array.isArray(payload.messages) ? payload.messages : [];
    hubChat.records.forEach(appendChatRecord);
    const lastModel = hubChat.records.filter(r => r.role === 'assistant' && r.model).pop();
    if (lastModel) setChatBadge('Model: ' + lastModel.model);
    if (!hubChat.records.length) appendChatRecord({ role: 'assistant', content: 'Brak historii rozmowy dla tego projektu. Zadaj pytanie albo wybierz szybkie pytanie poniżej.' });
    if (payload.skipped_lines) appendChatRecord({ role: 'error', content: 'Pominięto nieczytelne wpisy historii: ' + payload.skipped_lines + ' (plik ' + payload.path + ').' });
  } catch (error) {
    appendChatRecord({ role: 'error', content: 'Nie wczytano historii czatu z ' + url + ': ' + error.message });
  }
}
function loadChatSettings() {
  if (hubChat.started) return; hubChat.started = true;
  showChatMode();
  if (hubChat.mode !== 'hub') return;
  if (window.location.hash === '#chat' && typeof switchTab === 'function') switchTab('chat');
  return loadChatHistory();
}
function chatErrorRecord(status, payload) {
  return { role: 'error', content: (payload && payload.error) || 'HTTP ' + status, http_status: status,
    upstream_status: payload ? payload.upstream_status : null, model: payload ? payload.model : null, sources: payload ? payload.sources : null };
}
async function postChatTurn(messages) {
  const response = await fetch(hubChat.config.endpoint, { method: 'POST', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', '${CSRF_HEADER}': hubChat.config.csrf },
    body: JSON.stringify({ slug: hubChat.config.slug, messages: messages }), signal: AbortSignal.timeout(HUB_CHAT_TIMEOUT_MS) });
  let payload = null;
  try { payload = await response.json(); } catch (error) { payload = { error: 'HTTP ' + response.status + ', odpowiedź nie jest JSON' }; }
  if (!response.ok) return chatErrorRecord(response.status, payload);
  if (!payload || typeof payload.reply !== 'string' || !payload.reply.trim()) return chatErrorRecord(response.status, { error: 'Model zwrócił pustą odpowiedź.' });
  setChatBadge('Model: ' + payload.model + (payload.model_origin ? ' (' + payload.model_origin + ')' : ''));
  return { role: 'assistant', content: payload.reply, model: payload.model, elapsed_ms: payload.elapsed_ms, sources: payload.sources };
}
async function sendChatMessage() {
  const input = document.getElementById('chat-user-input');
  const text = input.value.trim();
  if (!text || hubChat.busy || hubChat.mode !== 'hub') return;
  hubChat.busy = true; input.value = '';
  const button = document.getElementById('chat-send-btn'); button.disabled = true; button.textContent = 'Czekam…';
  const userRecord = { role: 'user', content: text };
  appendChatRecord(userRecord);
  const pending = appendChatRecord({ role: 'assistant', content: 'Czekam na odpowiedź modelu…' });
  let record;
  try {
    record = await postChatTurn(recentTurns(hubChat.records.concat([userRecord]), HUB_CHAT_MAX_TURNS, HUB_CHAT_MAX_CHARS));
  } catch (error) {
    record = { role: 'error', content: error.name === 'TimeoutError' ? 'Brak odpowiedzi w ' + HUB_CHAT_TIMEOUT_MS / 1000 + ' s.' : 'Błąd połączenia z hubem: ' + error.message };
  }
  hubChat.records.push(userRecord, record);
  chatContainer().replaceChild(createMessageNode(document, record), pending);
  if (record.role === 'error') input.value = text;
  hubChat.busy = false; button.disabled = false; button.textContent = 'Wyślij';
}
`;
}

module.exports = { getChatScript, CHAT_TIMEOUT_MS };
