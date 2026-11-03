// Renders Task board, history, task inspector and task creation modal
const { escapeHtml } = require("./html");

function renderTasksTab(data) {
  const { state, orchestration } = data;
  const sections = state.sections || [];
  const allTasks = state.allTasks || [];
  const waves = (orchestration && orchestration.waves) || [];
  const openCount = state.openCount || 0;
  const doneCount = state.doneCount || 0;
  const totalCount = state.totalCount || 0;
  const progressPct = state.progressPct || 0;

  return `
    <div class="task-filter-bar">
      <div class="filter-pills">
        <button class="filter-btn active" data-filter="all">Wszystkie (${totalCount + waves.length})</button>
        <button class="filter-btn" data-filter="open">Do zrobienia (${openCount})</button>
        <button class="filter-btn" data-filter="done">Zrobione (${doneCount + waves.length})</button>
        ${waves.length > 0 ? `<button class="filter-btn" data-filter="waves">Fale Orchestration (${waves.length})</button>` : ''}
        <button class="filter-btn" data-filter="blocker">Blokery (${(state.blockers || []).length})</button>
      </div>
      <div style="display:flex; gap:10px; align-items:center;">
        <input type="text" class="search-input" id="task-search" placeholder="Szukaj zadania..." oninput="filterTasks()" />
        <button class="btn btn-primary btn-sm" onclick="openAddTaskModal()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
          Dodaj zadanie
        </button>
      </div>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-weight:600; font-size:12px; color:var(--text-muted);">POSTĘP PROJEKTU: ${doneCount} z ${totalCount} zadań STATE.md (+ ${waves.length} fal w orchestration)</span>
        <span class="mono" style="color:var(--emerald); font-weight:700;">${progressPct}%</span>
      </div>
      <div class="progress-bar-wrap" style="width:100%; height:10px;">
        <div class="progress-bar-fill" style="width:${progressPct}%;"></div>
      </div>
    </div>

    <!-- Staged / Locally Added Tasks Banner -->
    <div id="staged-tasks-container" style="display:none; margin-bottom:16px;"></div>

    <!-- Orchestration Waves Section (if exists) -->
    ${waves.length > 0 ? renderOrchestrationSection(waves) : ''}

    <div id="tasks-list-root">
      ${sections.map((sec, sIdx) => renderSection(sec, sIdx, orchestration)).join("")}
    </div>

    ${renderTaskDetailModal()}
    ${renderAddTaskModal(sections, data.slug)}
  `;
}

function renderOrchestrationSection(waves) {
  return `
    <div class="task-section" data-section-type="waves">
      <div class="section-header" onclick="toggleSection('waves')">
        <div style="display:flex; align-items:center; gap:8px;">
          <svg id="sec-arrow-waves" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
          <span style="color:var(--purple); font-weight:700;">FALE WYKONAWCZE & ORCHESTRATION (.planning/orchestration/): ${waves.length} fal</span>
        </div>
        <span class="pill pill-purple" style="font-size:10px;">${waves.length} ZWERYFIKOWANYCH FAL</span>
      </div>
      <div id="sec-body-waves" class="section-body">
        ${waves.map(w => renderWaveRow(w)).join("")}
      </div>
    </div>
  `;
}

function renderWaveRow(wave) {
  const id = wave.id;
  const title = (wave.title || wave.id).replace(/^#\s*(TASK|RESULT)-[A-Za-z0-9_\-]+:\s*/i, "");
  const isPass = /pass|done/i.test(wave.status);
  const statusLabel = isPass ? "PASS" : wave.status;

  return `
    <div class="task-row" data-task-id="${escapeHtml(id)}" data-task-status="done" data-is-wave="true" data-task-title="${escapeHtml((id + ' ' + title).toLowerCase())}" onclick="openTaskDetail('${escapeHtml(id)}', '${escapeHtml(title.replace(/'/g, "\\'"))}', true, 'Orchestration Wave ${escapeHtml(id)}')">
      <div class="task-left">
        <div class="check-icon done">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>
        </div>
        <span class="pill pill-purple mono" style="font-size:10px;">${escapeHtml(id)}</span>
        <span class="task-text done" style="text-decoration:none; color:#f1f5f9; font-weight:500;">${escapeHtml(title)}</span>
      </div>
      <div class="task-badges">
        <span class="pill pill-emerald mono" style="font-size:10px;">${escapeHtml(statusLabel)}</span>
        ${wave.result ? '<span class="pill pill-cyan" style="font-size:10px;">Dowód weryfikacji</span>' : ''}
        ${wave.task ? '<span class="pill" style="background:#1e2536; color:var(--text-muted); font-size:10px;">Specyfikacja</span>' : ''}
        <button class="btn btn-sm" style="padding:2px 8px; font-size:10px;" onclick="event.stopPropagation(); openTaskDetail('${escapeHtml(id)}', '${escapeHtml(title.replace(/'/g, "\\'"))}', true, 'Orchestration Wave ${escapeHtml(id)}')">Szczegóły</button>
      </div>
    </div>
  `;
}

function renderSection(sec, sIdx, orchestration) {
  const doneInSec = sec.tasks.filter(t => t.done).length;
  const totalInSec = sec.tasks.length;
  return `
    <div class="task-section" data-section-idx="${sIdx}">
      <div class="section-header" onclick="toggleSection(${sIdx})">
        <div style="display:flex; align-items:center; gap:8px;">
          <svg id="sec-arrow-${sIdx}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
          <span>${escapeHtml(sec.title)}</span>
        </div>
        <span class="pill pill-cyan" style="font-size:10px;">${doneInSec} / ${totalInSec} DONE</span>
      </div>
      <div id="sec-body-${sIdx}" class="section-body">
        ${sec.tasks.map(t => renderTaskRow(t, orchestration)).join("")}
      </div>
    </div>
  `;
}

function renderTaskRow(task, orchestration) {
  const isDone = task.done;
  const isBlocker = task.isBlocker;
  const id = task.id || "";
  const hasOrchTask = orchestration && orchestration.tasks && id && orchestration.tasks[id];
  const hasOrchResult = orchestration && orchestration.results && id && orchestration.results[id];
  const filterType = isBlocker ? "blocker" : (isDone ? "done" : "open");

  return `
    <div class="task-row" data-task-id="${escapeHtml(id)}" data-task-status="${filterType}" data-task-title="${escapeHtml(task.text.toLowerCase())}" onclick="openTaskDetail('${escapeHtml(id)}', '${escapeHtml(task.text.replace(/'/g, "\\'"))}', ${isDone}, '${escapeHtml(task.section.replace(/'/g, "\\'"))}')">
      <div class="task-left">
        <div class="check-icon ${isDone ? "done" : ""}">
          ${isDone ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>' : ''}
        </div>
        ${id ? `<span class="pill ${isDone ? "pill-emerald" : "pill-amber"} mono" style="font-size:10px;">${escapeHtml(id)}</span>` : ""}
        <span class="task-text ${isDone ? "done" : ""}">${escapeHtml(task.text)}</span>
      </div>
      <div class="task-badges">
        ${isBlocker ? '<span class="pill" style="background:var(--rose-glow); color:var(--rose); border-color:rgba(244,63,94,0.3);">BLOKER</span>' : ''}
        ${hasOrchResult ? '<span class="pill pill-purple" style="font-size:10px;">Wynik PASS</span>' : ''}
        ${hasOrchTask ? '<span class="pill pill-cyan" style="font-size:10px;">Specyfikacja</span>' : ''}
        <button class="btn btn-sm" style="padding:2px 8px; font-size:10px;" onclick="event.stopPropagation(); openTaskDetail('${escapeHtml(id)}', '${escapeHtml(task.text.replace(/'/g, "\\'"))}', ${isDone}, '${escapeHtml(task.section.replace(/'/g, "\\'"))}')">Szczegóły</button>
      </div>
    </div>
  `;
}

function renderTaskDetailModal() {
  return `
    <div class="modal-backdrop" id="task-detail-modal" onclick="closeTaskDetail(event)">
      <div class="modal-card" onclick="event.stopPropagation()">
        <div class="modal-header">
          <div style="display:flex; align-items:center; gap:10px;">
            <span id="modal-task-badge" class="pill pill-emerald mono">W16</span>
            <span id="modal-task-title" style="font-weight:700; font-size:15px; color:#fff;">Szczegóły zadania</span>
          </div>
          <button class="btn btn-sm" onclick="closeTaskDetail()">✕</button>
        </div>
        <div class="modal-body" id="modal-task-body">
          <div style="color:var(--text-muted); font-size:12px;">Ładowanie szczegółów zadania...</div>
        </div>
        <div class="modal-footer">
          <button class="btn" id="modal-task-copy-btn" onclick="copyTaskAsMarkdown()">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
            Kopiuj jako Markdown
          </button>
          <button class="btn btn-primary" onclick="closeTaskDetail()">Zamknij</button>
        </div>
      </div>
    </div>
  `;
}

function renderAddTaskModal(sections, slug) {
  return `
    <div class="modal-backdrop" id="add-task-modal" onclick="closeAddTaskModal(event)">
      <div class="modal-card" onclick="event.stopPropagation()">
        <div class="modal-header">
          <div style="display:flex; align-items:center; gap:8px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald)" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
            <span style="font-weight:700; font-size:15px; color:#fff;">Dodaj nowe zadanie do projektu</span>
          </div>
          <button class="btn btn-sm" onclick="closeAddTaskModal()">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">Tytuł zadania / Cel:</label>
            <input type="text" class="form-input" id="new-task-title" placeholder="np. W19: Implementacja telemetrycznego dashboardu" />
          </div>
          <div class="form-group">
            <label class="form-label">Faza / Sekcja docelowa w STATE.md:</label>
            <select class="form-select" id="new-task-section">
              ${sections.map(s => `<option value="${escapeHtml(s.title)}">${escapeHtml(s.title)}</option>`).join("")}
              <option value="Nowa faza">+ Nowa sekcja / faza</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Kryteria akceptacji & Wytyczne (opcjonalnie):</label>
            <textarea class="form-textarea" id="new-task-desc" placeholder="Opisz co dokładnie ma być zrobione i jak zweryfikowane..."></textarea>
          </div>
          <div class="form-group grid-2">
            <div>
              <label class="form-label">Priorytet:</label>
              <select class="form-select" id="new-task-prio">
                <option value="NORMAL">Normalny</option>
                <option value="HIGH">Wysoki</option>
                <option value="BLOCKER">Bloker</option>
              </select>
            </div>
            <div>
              <label class="form-label">Cel wykonawczy:</label>
              <select class="form-select" id="new-task-target">
                <option value="claude">Claude Code / Agent</option>
                <option value="hermes">Hermes Agent</option>
                <option value="cmux">cmux worker</option>
                <option value="manual">Manual / Operator</option>
              </select>
            </div>
          </div>
          <div id="add-task-output-wrap" style="display:none; margin-top:14px; background:#0b0e14; border:1px solid var(--border); border-radius:8px; padding:12px;">
            <div style="font-size:11px; font-weight:700; color:var(--cyan); margin-bottom:6px;">ODZWIERCIEDLENIE W PROJEKCIE (Gotowe do zastosowania):</div>
            <pre class="mono" id="add-task-preview" style="font-size:11px; color:#cbd5e1; white-space:pre-wrap; max-height:140px; overflow-y:auto;"></pre>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" id="btn-copy-agent-prompt" onclick="copyNewTaskPrompt('${slug}')" style="display:none;">Kopiuj prompt dla agenta</button>
          <button class="btn" onclick="stageNewTask('${slug}')">Dodaj i generuj wpisy</button>
          <button class="btn btn-primary" onclick="applyNewTaskDirect('${slug}')">Zapisz zadanie</button>
        </div>
      </div>
    </div>
  `;
}

module.exports = { renderTasksTab };
