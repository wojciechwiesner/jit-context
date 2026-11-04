// Safe workspace controls. Drafts are local and never masquerade as project file writes.
function getClientScript() {
  return `
const COCKPIT_DATA = JSON.parse(document.getElementById('cockpit-data-json').textContent);
const PROJ_SLUG = COCKPIT_DATA.slug;
const DRAFT_KEY = 'cockpit_drafts_v2:' + COCKPIT_DATA.root;
let currentFilter = 'all';
let currentTaskMarkdown = '';
let archScale = 1, archPanX = 0, archPanY = 0;
function switchTab(id) {
  document.querySelectorAll('.tab-btn').forEach(button => button.classList.toggle('active', button.dataset.tab === id));
  document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.toggle('active', pane.id === 'pane-' + id));
  const button = document.querySelector('[data-tab="' + id + '"]');
  document.getElementById('current-view-label').textContent = button?.querySelector('span')?.textContent || id;
  if (id === 'arch') initMermaidPanZoom();
  if (id === 'stream') checkStreamLiveness();
}
function setTaskFilter(filter) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(button => button.classList.toggle('active', button.dataset.filter === filter));
  filterTasks();
}
function filterTasks() {
  const query = (document.getElementById('task-search')?.value || '').toLowerCase();
  document.querySelectorAll('.task-row').forEach(row => {
    const matches = currentFilter === 'all' || (currentFilter === 'waves' ? row.dataset.isWave === 'true' : row.dataset.taskStatus === currentFilter);
    row.style.display = matches && row.dataset.taskTitle.includes(query) ? 'flex' : 'none';
  });
}
function toggleSection(index) {
  const body = document.getElementById('sec-body-' + index);
  if (body) body.hidden = !body.hidden;
}
function openTaskDetail(id, title, done, section) {
  const body = document.getElementById('modal-task-body'); body.replaceChildren();
  document.getElementById('modal-task-title').textContent = title;
  document.getElementById('modal-task-badge').textContent = id || (done ? 'Ukończone wg pliku' : 'Otwarte wg pliku');
  const source = document.createElement('p'); source.className = 'source-meta'; source.textContent = section; body.appendChild(source);
  currentTaskMarkdown = '# ' + title + '\\nŹródło: ' + section + '\\nStatus w pliku: ' + (done ? 'ukończone' : 'otwarte') + '\\n';
  const task = COCKPIT_DATA.orchestration.tasks[id], result = COCKPIT_DATA.orchestration.results[id];
  for (const [label, record] of [['Specyfikacja',task],['Raport wykonania — deklaracja w pliku, nie niezależny test',result]]) {
    if (!record) continue;
    const heading = document.createElement('h3'); heading.textContent = label + ' · ' + record.file;
    const content = document.createElement('pre'); content.className = 'source-code'; content.textContent = record.content;
    body.append(heading, content); currentTaskMarkdown += '\\n## ' + label + '\\n' + record.content + '\\n';
    if (record.size > record.content.length) { const note = document.createElement('p'); note.className='source-meta'; note.textContent='Podgląd skrócony. Pełny plik: ' + record.fullPath; body.append(note); }
  }
  if (!task && !result) { const note = document.createElement('p'); note.textContent = 'Wpis z planu projektu. Nie znaleziono osobnej specyfikacji ani raportu wykonania dla tego wpisu.'; body.append(note); }
  document.getElementById('task-detail-modal').classList.add('open');
}
function closeTaskDetail(event) { if (!event || event.target.id === 'task-detail-modal') document.getElementById('task-detail-modal').classList.remove('open'); }
function copyTaskAsMarkdown() { navigator.clipboard.writeText(currentTaskMarkdown).catch(() => {}); }
function openAddTaskModal() { document.getElementById('add-task-modal').classList.add('open'); }
function closeAddTaskModal(event) { if (!event || event.target.id === 'add-task-modal') document.getElementById('add-task-modal').classList.remove('open'); }
function readDrafts() { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '[]'); } catch { return []; } }
function generateTaskPayload() {
  const title = document.getElementById('new-task-title').value.trim();
  const desc = document.getElementById('new-task-desc').value.trim();
  return { title, desc, section: document.getElementById('new-task-section').value, mdLine:'- [ ] ' + title + (desc ? ' — ' + desc.replace(/\\n/g,' ') : ''), date:new Date().toISOString() };
}
function stageNewTask() {
  const draft = generateTaskPayload();
  if (!draft.title) { document.getElementById('new-task-title').focus(); return; }
  const drafts = readDrafts(); drafts.push(draft); localStorage.setItem(DRAFT_KEY,JSON.stringify(drafts));
  document.getElementById('add-task-output-wrap').style.display='block';
  document.getElementById('add-task-preview').textContent = 'Szkic lokalny — nie zapisano do plików.\\n' + draft.mdLine;
  document.getElementById('btn-copy-agent-prompt').style.display='inline-flex'; renderStagedTasks();
}
function copyNewTaskPrompt() { const draft = generateTaskPayload(); navigator.clipboard.writeText('Projekt: ' + COCKPIT_DATA.root + '\\nSekcja: ' + draft.section + '\\n' + draft.mdLine).catch(() => {}); }
function renderStagedTasks() {
  const container = document.getElementById('staged-tasks-container'); if (!container) return;
  const drafts = readDrafts(); container.replaceChildren(); container.style.display = drafts.length ? 'block' : 'none';
  const card = document.createElement('section'); card.className='card';
  const heading = document.createElement('h3'); heading.textContent='Szkice lokalne (' + drafts.length + ') — jeszcze nie w STATE.md'; card.append(heading);
  drafts.forEach(draft => { const row=document.createElement('div'); row.className='task-row'; const title=document.createElement('span');title.textContent=draft.title;const copy=document.createElement('button');copy.className='btn';copy.textContent='Kopiuj wpis';copy.onclick=()=>navigator.clipboard.writeText(draft.mdLine).catch(()=>{});row.append(title,copy);card.append(row); });
  container.append(card);
}
function toggleCapsuleRaw() { const box=document.getElementById('capsule-raw-box'); if(box) box.style.display=box.style.display==='none'?'block':'none'; }
function updateStreamSession() {
  const id=document.getElementById('stream-session-input').value.trim();
  if(!id) return;const url='http://127.0.0.1:8766/live?session='+encodeURIComponent(id);
  document.getElementById('jit-stream-iframe').src=url;document.getElementById('stream-direct-link').href=url;
}
function reloadStreamIframe() { const frame=document.getElementById('jit-stream-iframe'); frame.src=frame.src; }
function toggleStreamFullscreen() { const wrap=document.getElementById('stream-frame-wrap'); if(document.fullscreenElement) document.exitFullscreen().catch(()=>{});else wrap?.requestFullscreen().catch(()=>{}); }
function checkStreamLiveness() { const pill=document.getElementById('stream-status-pill'); if(pill){pill.className='pill';pill.textContent='Osobna usługa :8766 · sprawdź obraz';} }
function handleChatKeyDown(event) { if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChatMessage();} }
function sendQuickPrompt(text) { document.getElementById('chat-user-input').value=text;sendChatMessage(); }
document.addEventListener('DOMContentLoaded',()=>{renderStagedTasks();loadChatSettings();});
`;
}
module.exports = { getClientScript };
