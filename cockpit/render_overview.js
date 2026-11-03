// Document-first overview with provenance, milestones, and a real diagram preview.
const { esc } = require('./html');
const { documentHtml } = require('./presentation');

function renderLinks(links) {
  if (!links || (!links.groups.length && !links.error)) return '';
  if (links.error) return `<section class="card"><div class="card-heading"><div><span class="eyebrow">Do kliknięcia</span><h2>Adresy</h2></div></div><div class="notice">${esc(links.error)}</div></section>`;
  const count = links.groups.reduce((n, g) => n + g.items.length, 0);
  const groups = links.groups.map(g => `<div class="link-group"><span class="eyebrow">${esc(g.name)}</span>${g.items.map(l => `<a class="link-item" href="${esc(l.url)}" target="_blank" rel="noopener"><strong>${esc(l.label)}</strong><span class="mono">${esc(l.url.replace(/^https?:\/\//, ''))}</span>${l.note ? `<small class="muted">${esc(l.note)}</small>` : ''}</a>`).join('')}</div>`).join('');
  return `<section class="card"><div class="card-heading"><div><span class="eyebrow">Do kliknięcia</span><h2>Adresy</h2></div><span class="pill">${count}</span></div><style>.link-group{display:flex;flex-direction:column;gap:2px;padding:10px 0;border-top:1px solid var(--border)}.link-group:first-of-type{border-top:0}.link-item{display:flex;flex-direction:column;gap:2px;padding:8px;border-radius:8px;text-decoration:none;color:inherit}.link-item:hover{background:var(--surface-2,rgba(127,127,127,.08))}.link-item .mono{font-size:12px;opacity:.75;overflow-wrap:anywhere}</style>${groups}</section>`;
}

function renderCredentials(credentials) {
  if (!credentials || (!credentials.entries.length && !credentials.blocked)) return '';
  if (credentials.blocked) return `<section class="card"><div class="card-heading"><div><span class="eyebrow">Dostępy</span><h2>Hasła</h2></div></div><div class="notice">${esc(credentials.blocked)}</div></section>`;
  const rows = credentials.entries.map(c => `<div class="cred"><strong>${esc(c.label || '')}</strong>${c.url ? `<a class="mono" href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.url)}</a>` : ''}<div class="cred-row"><span class="eyebrow">Login</span><code>${esc(c.user || '')}</code><button class="btn btn-sm" onclick="navigator.clipboard.writeText(${esc(JSON.stringify(c.user || ''))})">Kopiuj</button></div><div class="cred-row"><span class="eyebrow">Hasło</span>${c.unresolved ? '<span class="pill pill-amber">brak w pliku źródłowym</span>' : `<code>${esc(c.pass)}</code><button class="btn btn-sm" onclick="navigator.clipboard.writeText(${esc(JSON.stringify(c.pass))})">Kopiuj</button>`}</div>${c.note ? `<small class="muted">${esc(c.note)}</small>` : ''}<small class="muted">Źródło: ${esc(c.source || '')}</small></div>`).join('');
  return `<section class="card"><div class="card-heading"><div><span class="eyebrow">Dostępy (lokalnie, nie w gicie)</span><h2>Hasła</h2></div><span class="pill">${credentials.entries.length}</span></div><style>.cred{display:flex;flex-direction:column;gap:6px;padding:12px 0;border-top:1px solid var(--border)}.cred:first-of-type{border-top:0}.cred-row{display:flex;align-items:center;gap:8px}.cred-row .eyebrow{margin:0;min-width:46px}.cred-row code{flex:1;min-width:0;overflow-wrap:anywhere;word-break:break-all}.cred-row .btn{flex-shrink:0}</style>${rows}</section>`;
}
const MAX_VISIBLE_WORKTREES = 8;
const SHORT_SHA_LENGTH = 7;

function worktreeRow(w) {
  const name = w.branch || (w.bare ? 'repozytorium bare' : w.detached ? 'odłączony HEAD' : 'brak gałęzi');
  const when = w.last_commit_at ? new Date(w.last_commit_at).toLocaleString('pl-PL') : 'brak commita';
  const dirty = w.dirty_count === null ? '<span class="pill pill-amber">stan nieznany</span>' : w.dirty_count > 0 ? `<span class="pill pill-amber">${w.dirty_count} zmian</span>` : '<span class="pill">czyste</span>';
  return `<div class="worktree"><div class="worktree-head"><strong class="mono">${esc(name)}</strong>${dirty}</div><small class="muted">${esc(when)}${w.head ? ` · <span class="mono">${esc(w.head.slice(0, SHORT_SHA_LENGTH))}</span>` : ''}</small>${w.last_commit_subject !== null ? `<span>${esc(w.last_commit_subject)}</span>` : ''}<small class="mono muted">${esc(w.path)}</small>${w.error ? `<div class="notice">${esc(w.error)}</div>` : ''}</div>`;
}

function renderWorktrees(data) {
  const worktrees = data.worktrees || [];
  const heading = `<div class="card-heading"><div><span class="eyebrow">Aktywność w worktree</span><h2>Gałęzie robocze</h2></div>${worktrees.length ? `<span class="pill">${worktrees.length}</span>` : ''}</div>`;
  if (data.worktreesError) return `<section class="card">${heading}<div class="notice">git worktree list: ${esc(data.worktreesError)}</div></section>`;
  if (!worktrees.length) return '';
  const visible = worktrees.slice(0, MAX_VISIBLE_WORKTREES).map(worktreeRow).join('');
  const rest = worktrees.slice(MAX_VISIBLE_WORKTREES);
  const collapsed = rest.length ? `<details><summary>Pozostałe (${rest.length})</summary>${rest.map(worktreeRow).join('')}</details>` : '';
  return `<section class="card worktrees">${heading}<style>.worktree{display:flex;flex-direction:column;gap:3px;padding:9px 0;border-top:1px solid var(--border)}.worktree:first-of-type{border-top:0}.worktree-head{display:flex;justify-content:space-between;gap:8px}.worktree .mono{overflow-wrap:anywhere}.worktrees summary{cursor:pointer;padding:8px 0}</style>${visible}${collapsed}</section>`;
}

function renderOverview(data) {
  const { state, git, architectureMeta } = data;
  const milestones = state.milestones || [];
  const architecturePreview = `<section class="card architecture-preview"><div class="card-heading"><div><span class="eyebrow">Mapa systemu</span><h2>Architektura</h2></div><button class="btn btn-sm" onclick="switchTab('arch')">Powiększ</button></div><div class="diagram-preview"><pre class="mermaid">${esc(data.architecture)}</pre></div><div class="source-meta">Źródło: ${esc(architectureMeta.source)}<br>Dokumentacja, nie pomiar stanu usług.</div></section>`;
  return `<section class="summary-strip">
    <div><span class="eyebrow">Aktualny fokus</span><strong>${esc(state.phase)}</strong></div>
    <div><span class="eyebrow">Checklisty STATE + ROADMAP</span><strong>${state.doneCount} / ${state.totalCount}<small> ukończonych wpisów</small></strong></div>
    <div><span class="eyebrow">Drzewo robocze</span><strong>${git.dirtyCount || 0}<small> zmienionych plików</small></strong></div>
  </section>
  <div class="overview-grid">
    <article class="card state-document">
      <div class="card-heading"><div><span class="eyebrow">Źródło prawdy</span><h2>Stan projektu</h2></div><span class="pill mono">STATE.md</span></div>
      <div class="source-meta">${state.mtime ? `Plik z ${new Date(state.mtime).toLocaleString('pl-PL')}` : 'Brak pliku STATE.md'} · status z dokumentu: ${esc(state.status)}</div>
      ${state.reportedProgress !== null ? `<div class="notice">Postęp zadeklarowany w STATE.md: ${state.reportedProgress}%. To nie jest wynik niezależnej weryfikacji.</div>` : ''}
      <div class="document-body">${state.raw ? documentHtml(state.raw) : '<p>Nie znaleziono .planning/STATE.md. Kokpit nie będzie wymyślał stanu projektu.</p>'}</div>
    </article>
    <aside class="overview-aside">${renderLinks(data.links)}${renderCredentials(data.credentials)}${renderWorktrees(data)}${architecturePreview}
      <section class="card"><div class="card-heading"><div><span class="eyebrow">Plan produktu</span><h2>Kamienie milowe</h2></div><span class="pill">${milestones.length}</span></div>
        <div class="milestone-list">${milestones.length ? milestones.map((task, i) => `<button class="milestone" onclick="switchTab('tasks'); document.getElementById('task-search').value=${esc(JSON.stringify(task.text))}; filterTasks()"><span class="milestone-dot ${task.done ? 'done' : task.partial ? 'partial' : ''}">${String(i + 1).padStart(2, '0')}</span><span>${esc(task.text.replace(/\*\*/g, ''))}<small>${task.done ? 'Ukończone według ROADMAP' : task.partial ? 'Częściowo wykonane' : 'Do zrobienia'}</small></span></button>`).join('') : '<p class="muted">Brak kamieni milowych w ROADMAP.md.</p>'}</div>
        <button class="btn full-width" onclick="switchTab('tasks')">Przejdź do planu i zadań</button>
      </section>
    </aside>
  </div>`;
}
module.exports = { renderOverview };
