// Renders JIT Livestream embed view
const { escapeHtml } = require("./html");

function renderStreamTab(data) {
  const stream = data.livestream || {};
  const defaultSession = stream.defaultSession || "20261018_163217_6298d0";
  const defaultUrl = `${stream.url || "http://127.0.0.1:8766/live"}?session=${defaultSession}`;

  return `
    <div class="card" style="margin-bottom:14px; padding:12px 18px;">
      <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <span style="font-weight:700; font-size:14px; color:#fff;">JIT LIVESTREAM OBSERVER</span>
          <span class="pill pill-emerald" id="stream-status-pill">
            <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--emerald);"></span>
            PORT 8766 SPRAWDZANIE...
          </span>
        </div>
        
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:12px; color:var(--text-muted);">Sesja:</span>
          <input type="text" id="stream-session-input" class="search-input mono" style="width:260px;" value="${escapeHtml(defaultSession)}" placeholder="ID sesji..." />
          <button class="btn btn-sm" onclick="updateStreamSession()">Załaduj sesję</button>
          <button class="btn btn-sm" onclick="reloadStreamIframe()">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
            Odśwież
          </button>
          <a id="stream-direct-link" href="${escapeHtml(defaultUrl)}" target="_blank" class="btn btn-sm">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3"/></svg>
            Otwórz w nowej karcie
          </a>
          <button class="btn btn-primary btn-sm" onclick="toggleStreamFullscreen()">Pełny ekran</button>
        </div>
      </div>
    </div>

    <div class="stream-frame-wrap" id="stream-frame-wrap">
      <iframe id="jit-stream-iframe" class="stream-iframe" src="${escapeHtml(defaultUrl)}" title="JIT Livestream"></iframe>
    </div>
  `;
}

module.exports = { renderStreamTab };
