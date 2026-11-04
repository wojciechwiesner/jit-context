// Canonical project cockpit: document-first, offline diagram runtime, no emoji.
const fs = require('node:fs');
const path = require('node:path');
const { getStyles } = require('./style');
const { getClientScript } = require('./client_workspace');
const { renderOverview } = require('./render_overview');
const { renderTasksTab } = require('./render_plan');
const { renderArchTab } = require('./render_arch');
const { renderContextTab } = require('./render_context');
const { renderStreamTab } = require('./render_stream');
const { renderChatTab } = require('./render_chat');
const { renderStatsTab } = require('./render_stats');
const { clean, cleanData, documentHtml, icon } = require('./presentation');
const { esc } = require('./html');
const { renderFreshnessStamp, renderNewerNotice, getFreshnessScript } = require('./freshness');

const TABS = [['overview', 'Stan projektu'], ['tasks', 'Plan i zadania'], ['arch', 'Architektura'],
  ['context', 'Wiedza i kontekst'], ['stats', 'Statystyki'], ['stream', 'Livestream'], ['chat', 'Czat projektu'], ['thoughts', 'Notatki']];

function render(input) {
  const data = cleanData(input);
  const title = /uni.?pro/i.test(data.slug) ? 'UniPro Works' : data.slug.replace(/^_+/, '').replace(/[-_]/g, ' ');
  const json = value => JSON.stringify(value).replace(/</g, '\\u003c');
  const mermaid = fs.readFileSync(path.join(__dirname, 'vendor/mermaid-10.9.3.min.js')).toString('base64');
  const panels = { overview: renderOverview(data), tasks: renderTasksTab(data), arch: renderArchTab(data),
    context: renderContextTab(data), stats: renderStatsTab(data), stream: renderStreamTab(data), chat: renderChatTab(data),
    thoughts: `<article class="card"><div class="card-heading"><div><span class="eyebrow">.planning/THOUGHTS.md</span><h2>Notatki projektu</h2></div></div><div class="document-body">${data.thoughts.length ? documentHtml(data.thoughts.map(t => '- ' + t).join('\n')) : '<p>Brak wpisów w THOUGHTS.md.</p>'}</div><p class="source-meta">Widok odczytu. Notatki edytujesz w .planning/THOUGHTS.md.</p></article>` };
  return `<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)} — Kokpit projektu</title><style>${getStyles()}</style></head><body>
    <aside class="sidebar"><div class="workspace-brand"><span class="brand-mark">W</span><span>Workspace<small>Kokpit projektu</small></span></div>
      <div class="sidebar-project"><span class="eyebrow">Aktywny projekt</span><strong>${esc(title)}</strong><span class="mono">${esc(data.git.branch)}</span></div>
      <nav class="nav-tabs" aria-label="Nawigacja projektu">${TABS.map(([id, label]) => `<button class="tab-btn ${id === 'overview' ? 'active' : ''}" data-tab="${id}" onclick="switchTab('${id}')">${icon(id)}<span>${label}</span>${id === 'tasks' ? `<span class="tab-badge">${data.state.totalCount}</span>` : ''}</button>`).join('')}</nav>
      <div class="sidebar-foot"><span class="local-dot"></span> Lokalny kokpit<small>Odczyt z plików projektu.<br>Stan dokumentów, nie certyfikat wdrożenia.</small></div></aside>
    <div class="workspace"><header class="top-header"><div class="breadcrumb">Projekty <span>/</span> ${esc(title)} <span>/</span> <strong id="current-view-label">Stan projektu</strong></div><div class="header-actions">${renderFreshnessStamp(data)}<button class="btn" onclick="location.reload()">Odśwież widok</button></div></header>${renderNewerNotice(data)}
      <main class="main-content"><div class="page-heading"><div><span class="eyebrow">Project workspace</span><h1>${esc(title)}</h1><p class="project-path">${esc(data.root)}</p></div><div class="snapshot-meta">Snapshot danych<br><strong>${new Date(data.generatedAt).toLocaleString('pl-PL')}</strong></div></div>
        ${TABS.map(([id]) => `<div class="tab-pane ${id === 'overview' ? 'active' : ''}" id="pane-${id}">${clean(panels[id])}</div>`).join('')}
        <footer class="page-footer">Źródła: STATE.md · ROADMAP.md · dokumentacja · Git <span>Generator kokpitu / 2.1</span></footer>
      </main></div>
    <script type="application/json" id="cockpit-data-json">${json(data)}</script>
    <script src="data:text/javascript;base64,${mermaid}"></script>
    <script>${clean(getClientScript())}</script>
    <script>${require('./client_arch').getArchScript()}</script>
    <script>${require('./client_chat').getChatScript()}</script>
    <script>${getFreshnessScript()}</script>
    <script>
      document.querySelectorAll('.filter-btn').forEach(button => button.addEventListener('click', () => setTaskFilter(button.dataset.filter)));
      document.addEventListener('keydown', event => { if (event.key === 'Escape') document.querySelectorAll('.modal-backdrop.open').forEach(modal => modal.classList.remove('open')); });
      if (window.mermaid) {
        mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base', flowchart: { htmlLabels: false, useMaxWidth: false }, themeVariables: { background: '#131518', primaryColor: '#22272a', primaryTextColor: '#e9ebe9', primaryBorderColor: '#5b6863', lineColor: '#808e87', secondaryColor: '#202421', tertiaryColor: '#1b201e', fontFamily: 'system-ui', fontSize: '15px' } });
        mermaid.run({ querySelector: '.diagram-preview .mermaid' }).catch(() => { document.querySelector('.diagram-preview').textContent = 'Podgląd niedostępny. Otwórz zakładkę Architektura, aby zobaczyć diagram i źródło.'; });
      }
    </script></body></html>`;
}
module.exports = { render };
