// The local bridge is explicit: no invented cloud model, secrets, or filesystem writes.
const { esc } = require('./html');
function renderChatTab(data) {
  const runtime = data.chatRuntime;
  return `<section class="notice">${runtime ? `Model: ${esc(runtime.model)} przez lokalny most i skonfigurowane proxy :8788. Kontekst jest wysyłany do dostawcy modelu, nie do Ollamy. Żadnych kluczy API w przeglądarce. Kontekst to snapshot STATE, ROADMAP, architektury i Obsidiana.` : 'Most czatu nie został uruchomiony. Nie wysłano żadnego zapytania do modelu.'} Czat nie zapisuje zmian do plików; proponowane zadania pozostają szkicami.</section>
  <div class="chat-layout"><div class="chat-header"><h2>Rozmowa o projekcie</h2><div class="header-actions"><span class="pill mono" id="chat-model-badge">${esc(runtime?.model || 'Nie skonfigurowano')}</span><button class="btn" onclick="clearChatHistory()">Wyczyść czat</button></div></div>
  <div class="chat-messages" id="chat-messages-container" aria-live="polite"><div class="msg msg-bot">Widzę stan projektu i plan z tego snapshotu. Zapytaj o konkretny etap, ryzyko albo kolejne zadanie. Nie mam uprawnień do samodzielnej zmiany plików.</div></div>
  <div class="chat-quick-chips"><button class="chip-btn" onclick="sendQuickPrompt('Jaki jest aktualny fokus projektu i jakie są 3 kolejne kroki? Podaj źródła.')">Kolejne kroki</button><button class="chip-btn" onclick="sendQuickPrompt('Wskaż sprzeczności pomiędzy STATE.md a ROADMAP.md. Nie wymyślaj dowodów wykonania.')">Sprawdź spójność planu</button><button class="chip-btn" onclick="sendQuickPrompt('Wyjaśnij architekturę na podstawie diagramu i wskaż niepewności.')">Omów architekturę</button></div>
  <div class="chat-input-bar"><textarea class="chat-input" id="chat-user-input" aria-label="Wiadomość o projekcie" placeholder="Zapytaj o projekt…" rows="2" onkeydown="handleChatKeyDown(event)"></textarea><button class="btn btn-primary" id="chat-send-btn" onclick="sendChatMessage()">Wyślij</button></div></div>`;
}
module.exports = { renderChatTab };
