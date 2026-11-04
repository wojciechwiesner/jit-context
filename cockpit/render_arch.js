// Self-contained architecture viewport; source remains available if SVG rendering fails.
const { esc } = require('./html');
function renderArchTab(data) {
  return `<section class="card architecture-card">
    <div class="card-heading"><div><span class="eyebrow">Architektura projektu</span><h2>Mapa systemu</h2></div>
      <div class="arch-controls"><button class="btn" aria-label="Pomniejsz diagram" onclick="zoomArch(0.8)">−</button><span id="zoom-indicator" class="mono">100%</span><button class="btn" aria-label="Powiększ diagram" onclick="zoomArch(1.25)">+</button><button class="btn" onclick="fitArchZoom()">Dopasuj</button><button class="btn" onclick="resetArchZoom()">1:1</button><button class="btn" onclick="openArchFullscreen()">Pełny ekran</button></div></div>
    <p class="source-meta">${esc(data.architectureMeta.source)} · Powiększaj kółkiem, przesuwaj przeciągnięciem. Kliknij węzeł, aby zobaczyć etykietę i źródło.</p>
    <div id="arch-viewport" class="arch-viewport"><div id="arch-svg-inner"><pre class="mermaid">${esc(data.architecture)}</pre></div></div>
    <div id="arch-node-details" class="notice">Wybierz węzeł diagramu. Mapa pochodzi z dokumentacji projektu; nie potwierdza działania usług.</div>
  </section>
  <details class="card"><summary>Kod źródłowy diagramu</summary><pre class="source-code">${esc(data.architecture)}</pre></details>
  <div class="modal-backdrop" id="arch-fullscreen-modal"><div class="modal-card arch-fullscreen-card"><div class="modal-header"><h2>Architektura</h2><div class="arch-controls"><button class="btn" onclick="zoomArch(0.8)">−</button><button class="btn" onclick="zoomArch(1.25)">+</button><button class="btn" onclick="fitArchZoom()">Dopasuj</button><button class="btn" onclick="closeArchFullscreen()">Zamknij</button></div></div><div id="fs-arch-viewport" class="arch-viewport"><div id="fs-arch-svg-inner"></div></div></div></div>`;
}
module.exports = { renderArchTab };
