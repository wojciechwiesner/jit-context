// Client-side controller for SOTA visual project cockpit
function getClientScript() {
  return `
    // Read safe embedded data
    const COCKPIT_DATA = JSON.parse(document.getElementById('cockpit-data-json').textContent);
    const PROJ_SLUG = COCKPIT_DATA.slug || "default";
    
    // Tab switching
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      const btn = document.querySelector('[data-tab="' + tabId + '"]');
      const pane = document.getElementById('pane-' + tabId);
      if (btn) btn.classList.add('active');
      if (pane) pane.classList.add('active');
      const label = document.getElementById('current-view-label');
      if (label && btn) label.textContent = btn.querySelector('span')?.textContent || btn.textContent;
      if (tabId === 'arch') initMermaidPanZoom();
      if (tabId === 'stream') checkStreamLiveness();
    }

    // Task filtering and search
    let currentFilter = 'all';
    function setTaskFilter(filter) {
      currentFilter = filter;
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = document.querySelector('[data-filter="' + filter + '"]');
      if (activeBtn) activeBtn.classList.add('active');
      filterTasks();
    }
    
    function filterTasks() {
      const q = (document.getElementById('task-search')?.value || '').toLowerCase().trim();
      document.querySelectorAll('.task-row').forEach(row => {
        const status = row.getAttribute('data-task-status');
        const title = row.getAttribute('data-task-title') || '';
        const matchesFilter = currentFilter === 'all' || 
          (currentFilter === 'open' && status === 'open') ||
          (currentFilter === 'done' && status === 'done') ||
          (currentFilter === 'blocker' && status === 'blocker') ||
          (currentFilter === 'waves' && row.dataset.isWave === 'true');
        const matchesQuery = !q || title.includes(q);
        row.style.display = (matchesFilter && matchesQuery) ? 'flex' : 'none';
      });
    }

    function toggleSection(idx) {
      const body = document.getElementById('sec-body-' + idx);
      const arrow = document.getElementById('sec-arrow-' + idx);
      if (body.style.display === 'none') {
        body.style.display = 'block';
        if (arrow) arrow.style.transform = 'rotate(0deg)';
      } else {
        body.style.display = 'none';
        if (arrow) arrow.style.transform = 'rotate(-90deg)';
      }
    }

    // Task detail modal
    let currentTaskMarkdown = "";
    function openTaskDetail(id, title, done, section) {
      const modal = document.getElementById('task-detail-modal');
      const badge = document.getElementById('modal-task-badge');
      const titleEl = document.getElementById('modal-task-title');
      const bodyEl = document.getElementById('modal-task-body');
      
      badge.textContent = id || (done ? "DONE" : "TODO");
      badge.className = "pill mono " + (done ? "pill-emerald" : "pill-amber");
      titleEl.textContent = title;

      const orchTasks = (COCKPIT_DATA.orchestration && COCKPIT_DATA.orchestration.tasks) || {};
      const orchResults = (COCKPIT_DATA.orchestration && COCKPIT_DATA.orchestration.results) || {};
      const tData = id ? orchTasks[id] : null;
      const rData = id ? orchResults[id] : null;

      currentTaskMarkdown = "# Zadanie: " + (id ? "[" + id + "] " : "") + title + "\\n" +
        "Status: " + (done ? "DONE" : "TODO") + "\\n" +
        "Sekcja: " + section + "\\n\\n";

      let html = '<div style="margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; background:#0d111a; padding:10px 14px; border-radius:8px; border:1px solid var(--border);">' +
        '<div><span style="color:var(--text-faint); font-size:11px;">SEKCJA:</span> <span style="font-weight:600; color:#fff;">' + escapeHtmlStr(section) + '</span></div>' +
        '<span class="pill ' + (done ? 'pill-emerald' : 'pill-amber') + '">' + (done ? 'ZROBIONE' : 'DO ZROBIENIA') + '</span>' +
        '</div>';

      if (rData) {
        currentTaskMarkdown += "## Wynik wykonania (RESULT-" + id + ".md)\\n" + rData.content + "\\n\\n";
        html += '<div style="margin-bottom:16px;">' +
          '<div style="font-size:11px; font-weight:700; color:var(--purple); margin-bottom:6px; display:flex; justify-content:space-between;">' +
          '<span>WYNIK WYKONANIA (' + escapeHtmlStr(rData.file) + ')</span>' +
          '<span class="pill">DEKLARACJA W PLIKU</span>' +
          '</div>' +
          '<pre class="mono" style="background:#090c12; border:1px solid var(--border); border-radius:6px; padding:12px; font-size:11px; color:#cbd5e1; white-space:pre-wrap; max-height:220px; overflow-y:auto;">' + escapeHtmlStr(rData.content) + '</pre>' +
          '</div>';
      }

      if (tData) {
        currentTaskMarkdown += "## Specyfikacja zadania (TASK-" + id + ".md)\\n" + tData.content + "\\n\\n";
        html += '<div style="margin-bottom:14px;">' +
          '<div style="font-size:11px; font-weight:700; color:var(--cyan); margin-bottom:6px;">SPECYFIKACJA / KONTRAKT (' + escapeHtmlStr(tData.file) + ')</div>' +
          '<pre class="mono" style="background:#090c12; border:1px solid var(--border); border-radius:6px; padding:12px; font-size:11px; color:#94a3b8; white-space:pre-wrap; max-height:180px; overflow-y:auto;">' + escapeHtmlStr(tData.content) + '</pre>' +
          '</div>';
      }

      if (!tData && !rData) {
        html += '<div style="padding:20px; text-align:center; color:var(--text-faint); background:#0b0e14; border-radius:8px;">Brak dedykowanego pliku orchestration dla tego zadania. Zadanie zdefiniowane w .planning/STATE.md.</div>';
      }

      bodyEl.innerHTML = html;
      modal.classList.add('open');
    }

    function closeTaskDetail(e) {
      if (e && e.target && e.target.id !== 'task-detail-modal' && !e.target.classList.contains('btn')) return;
      document.getElementById('task-detail-modal')?.classList.remove('open');
    }

    function copyTaskAsMarkdown() {
      navigator.clipboard.writeText(currentTaskMarkdown).then(() => {
        const btn = document.getElementById('modal-task-copy-btn');
        if (btn) { const old = btn.innerHTML; btn.textContent = "Skopiowano!"; setTimeout(() => { btn.innerHTML = old; }, 2000); }
      });
    }

    // Add new task
    function updateNewTaskPreview() {
      const p = generateTaskPayload();
      const prev = document.getElementById('add-task-preview');
      if (prev) {
        prev.textContent = "1. Wpis do .planning/STATE.md:\\n" + p.mdLine + "\\n\\n2. Komenda Hermes Kanban:\\n" + p.kanbanCmd;
      }
    }

    function openAddTaskModal() {
      document.getElementById('add-task-modal')?.classList.add('open');
      updateNewTaskPreview();
    }

    function closeAddTaskModal(e) {
      if (e && e.target && e.target.id !== 'add-task-modal' && !e.target.classList.contains('btn')) return;
      document.getElementById('add-task-modal')?.classList.remove('open');
    }

    function generateTaskPayload() {
      const title = document.getElementById('new-task-title')?.value.trim() || 'Nowe zadanie';
      const section = document.getElementById('new-task-section')?.value || 'Nowa faza';
      const desc = document.getElementById('new-task-desc')?.value.trim();
      const prio = document.getElementById('new-task-prio')?.value || 'NORMAL';
      const target = document.getElementById('new-task-target')?.value || 'claude';
      const mdLine = "- [ ] " + title + (desc ? " — " + desc.replace(/\\n/g, " ") : "");
      const kanbanCmd = 'hermes kanban create --title "' + title.replace(/"/g, '\\\\"') + '" --assignee "dev-worker" --body "' + (desc || title).replace(/"/g, '\\\\"') + '"';
      const agentPrompt = "Zadanie w projekcie " + PROJ_SLUG + ":\\nSekcja: " + section + "\\n" + title + "\\n" + (desc ? "\\nKryteria: " + desc : "");
      return { title, section, desc, prio, target, mdLine, kanbanCmd, agentPrompt, date: new Date().toISOString() };
    }

    function stageNewTask(slug) {
      const p = generateTaskPayload();
      const key = "cockpit_staged_tasks_" + slug;
      const existing = JSON.parse(localStorage.getItem(key) || "[]");
      existing.push(p);
      localStorage.setItem(key, JSON.stringify(existing));
      
      const outWrap = document.getElementById('add-task-output-wrap');
      const prev = document.getElementById('add-task-preview');
      const copyBtn = document.getElementById('btn-copy-agent-prompt');
      outWrap.style.display = 'block';
      copyBtn.style.display = 'inline-flex';
      prev.textContent = "1. Wpis do .planning/STATE.md:\\n" + p.mdLine + "\\n\\n2. Komenda Hermes Kanban:\\n" + p.kanbanCmd;
      renderStagedTasks(slug);
    }

    function applyNewTaskDirect(slug) {
      stageNewTask(slug);
      navigator.clipboard.writeText(generateTaskPayload().mdLine);
      alert("Zadanie dodane do kolejki roboczej w kokpicie i skopiowane do schowka! Wklej je do .planning/STATE.md lub przekaż agentowi.");
      closeAddTaskModal();
    }

    function copyNewTaskPrompt(slug) {
      const p = generateTaskPayload();
      navigator.clipboard.writeText(p.agentPrompt).then(() => { alert("Skopiowano prompt zadania dla agenta do schowka!"); });
    }

    function renderStagedTasks(slug) {
      const key = "cockpit_staged_tasks_" + slug;
      const container = document.getElementById('staged-tasks-container');
      if (!container) return;
      const staged = JSON.parse(localStorage.getItem(key) || "[]");
      if (staged.length === 0) { container.style.display = 'none'; return; }
      
      container.style.display = 'block';
      let html = '<div class="card" style="border-color:var(--cyan); background:#0c1522;">' +
        '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">' +
        '<span style="font-weight:700; color:var(--cyan); font-size:12px;">NOWE ZADANIA ROBOCZE (Lokalna kolejka): ' + staged.length + '</span>' +
        '<button class="btn btn-sm" onclick="clearStagedTasks(\\'' + slug + '\\')">Wyczyść kolejkę</button>' +
        '</div>';
      staged.forEach((st, idx) => {
        html += '<div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:#121c2d; border-radius:6px; margin-bottom:6px; font-size:12px;">' +
          '<div style="display:flex; align-items:center; gap:8px;">' +
          '<span class="pill pill-cyan" style="font-size:10px;">LOKALNE</span>' +
          '<span style="color:#fff; font-weight:500;">' + escapeHtmlStr(st.title) + '</span>' +
          '</div>' +
          '<button class="btn btn-sm" style="font-size:10px; padding:2px 8px;" onclick="copySingleStaged(\\'' + slug + '\\', ' + idx + ')">Kopiuj do STATE.md</button>' +
          '</div>';
      });
      html += '</div>';
      container.innerHTML = html;
    }

    function clearStagedTasks(slug) {
      localStorage.removeItem("cockpit_staged_tasks_" + slug);
      renderStagedTasks(slug);
    }

    function copySingleStaged(slug, idx) {
      const staged = JSON.parse(localStorage.getItem("cockpit_staged_tasks_" + slug) || "[]");
      if (staged[idx]) {
        navigator.clipboard.writeText(staged[idx].mdLine).then(() => { alert("Skopiowano linię zadania do schowka: " + staged[idx].mdLine); });
      }
    }

    // Mermaid Pan & Zoom
    let archScale = 1.0;
    let archPanX = 0;
    let archPanY = 0;
    let isArchDragging = false;
    let archStartX = 0;
    let archStartY = 0;

    function initMermaidPanZoom() {
      applyArchTransform();
      attachMermaidNodeListeners();
    }

    function applyArchTransform() {
      const target = document.getElementById('arch-svg-inner');
      const ind = document.getElementById('zoom-indicator');
      if (target) target.style.transform = "translate(" + archPanX + "px, " + archPanY + "px) scale(" + archScale + ")";
      if (ind) ind.textContent = Math.round(archScale * 100) + "%";
    }

    function zoomArch(factor) {
      archScale = Math.max(0.2, Math.min(5.0, archScale * factor));
      applyArchTransform();
    }

    function resetArchZoom() {
      archScale = 1.0; archPanX = 0; archPanY = 0;
      applyArchTransform();
    }

    function fitArchZoom() {
      archScale = 0.85; archPanX = 0; archPanY = 0;
      applyArchTransform();
    }

    function handleArchWheel(e) {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 0.85;
      zoomArch(factor);
    }

    function startArchDrag(e) {
      if (e.button !== 0) return;
      isArchDragging = true;
      archStartX = e.clientX - archPanX;
      archStartY = e.clientY - archPanY;
      window.addEventListener('mousemove', doArchDrag);
      window.addEventListener('mouseup', stopArchDrag);
    }

    function doArchDrag(e) {
      if (!isArchDragging) return;
      archPanX = e.clientX - archStartX;
      archPanY = e.clientY - archStartY;
      applyArchTransform();
    }

    function stopArchDrag() {
      isArchDragging = false;
      window.removeEventListener('mousemove', doArchDrag);
      window.removeEventListener('mouseup', stopArchDrag);
    }

    function attachMermaidNodeListeners() {
      document.querySelectorAll('.mermaid svg .node').forEach(node => {
        node.style.cursor = 'pointer';
        node.onclick = () => {
          const text = node.textContent.trim();
          const inspector = document.getElementById('arch-node-details');
          if (inspector) {
            inspector.innerHTML = '<div style="background:#0d111a; border:1px solid var(--border); border-radius:8px; padding:12px;">' +
              '<div style="font-size:11px; font-weight:700; color:var(--cyan); margin-bottom:4px;">ZAZNACZONY WĘZEŁ:</div>' +
              '<div style="font-size:14px; font-weight:700; color:#fff; margin-bottom:8px;">' + escapeHtmlStr(text) + '</div>' +
              '<div style="font-size:11px; color:var(--text-muted); line-height:1.4;">Węzeł architektury wyrenderowany z .planning/ARCHITECTURE.mmd.</div>' +
              '</div>';
          }
        };
      });
    }

    // Fullscreen Mermaid
    function openArchFullscreen() {
      const modal = document.getElementById('arch-fullscreen-modal');
      const src = document.getElementById('arch-svg-inner');
      const target = document.getElementById('fs-arch-svg-inner');
      if (src && target) target.innerHTML = src.innerHTML;
      if (modal) modal.classList.add('open');
    }

    function closeArchFullscreen(e) {
      if (e && e.target && e.target.id !== 'arch-fullscreen-modal' && !e.target.classList.contains('btn')) return;
      document.getElementById('arch-fullscreen-modal')?.classList.remove('open');
    }

    // Livestream Controller
    function updateStreamSession() {
      const sId = document.getElementById('stream-session-input')?.value.trim();
      const iframe = document.getElementById('jit-stream-iframe');
      const direct = document.getElementById('stream-direct-link');
      if (sId && iframe) {
        const url = "http://127.0.0.1:8766/live?session=" + encodeURIComponent(sId);
        iframe.src = url;
        if (direct) direct.href = url;
      }
    }

    function reloadStreamIframe() {
      const iframe = document.getElementById('jit-stream-iframe');
      if (iframe) iframe.src = iframe.src;
    }

    function toggleStreamFullscreen() {
      const wrap = document.getElementById('stream-frame-wrap');
      if (wrap) {
        if (!document.fullscreenElement) wrap.requestFullscreen().catch(() => {});
        else document.exitFullscreen().catch(() => {});
      }
    }

    function checkStreamLiveness() {
      const pill = document.getElementById('stream-status-pill');
      fetch("http://127.0.0.1:8766/live", { mode: 'no-cors' })
        .then(() => {
          if (pill) { pill.className = "pill pill-emerald"; pill.textContent = "PORT 8766 LIVE"; }
        })
        .catch(() => {
          if (pill) { pill.className = "pill"; pill.style.background = "#2a151b"; pill.style.color = "var(--rose)"; pill.textContent = "PORT 8766 NIEDOSTĘPNY"; }
        });
    }

    // Capsule Raw Toggle
    function toggleCapsuleRaw() {
      const b = document.getElementById('capsule-raw-box');
      if (b) b.style.display = b.style.display === 'none' ? 'block' : 'none';
    }

    // Project AI Chat Engine
    function openChatSettings() { document.getElementById('chat-settings-modal')?.classList.add('open'); loadChatSettings(); }
    function closeChatSettings(e) { if (e && e.target && e.target.id !== 'chat-settings-modal' && !e.target.classList.contains('btn')) return; document.getElementById('chat-settings-modal')?.classList.remove('open'); }
    
    function loadChatSettings() {
      const url = localStorage.getItem("cockpit_chat_url") || "http://localhost:8317/v1";
      const model = localStorage.getItem("cockpit_chat_model") || "gemini-3.8-flash";
      const key = localStorage.getItem("cockpit_chat_key") || "";
      if (document.getElementById('chat-api-url')) document.getElementById('chat-api-url').value = url;
      if (document.getElementById('chat-model-name')) document.getElementById('chat-model-name').value = model;
      if (document.getElementById('chat-api-key')) document.getElementById('chat-api-key').value = key;
    }

    function saveChatSettings() {
      const url = document.getElementById('chat-api-url')?.value.trim() || "http://localhost:8317/v1";
      const model = document.getElementById('chat-model-name')?.value.trim() || "gemini-3.8-flash";
      const key = document.getElementById('chat-api-key')?.value.trim() || "";
      localStorage.setItem("cockpit_chat_url", url);
      localStorage.setItem("cockpit_chat_model", model);
      localStorage.setItem("cockpit_chat_key", key);
      const b = document.getElementById('chat-model-badge');
      if (b) b.textContent = model;
      closeChatSettings();
    }

    function sendQuickPrompt(promptText) {
      const input = document.getElementById('chat-user-input');
      if (input) { input.value = promptText; sendChatMessage(); }
    }

    function handleChatKeyDown(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
    }

    async function sendChatMessage() {
      const input = document.getElementById('chat-user-input');
      const container = document.getElementById('chat-messages-container');
      const text = input?.value.trim();
      if (!text) return;
      input.value = '';

      // Append user msg
      const uMsg = document.createElement('div');
      uMsg.className = 'msg msg-user';
      uMsg.textContent = text;
      container.appendChild(uMsg);
      container.scrollTop = container.scrollHeight;

      // Bot loading placeholder
      const bMsg = document.createElement('div');
      bMsg.className = 'msg msg-bot';
      bMsg.textContent = 'Generuję odpowiedź z kontekstem projektu...';
      container.appendChild(bMsg);
      container.scrollTop = container.scrollHeight;

      const pPayload = JSON.parse(document.getElementById('project-context-payload')?.textContent || '{}');
      const systemPrompt = "Jesteś asystentem inżynierskim dla projektu " + pPayload.title + " (" + pPayload.slug + ").\\n" +
        "Katalog: " + pPayload.root + "\\nFaza: " + pPayload.phase + "\\n" +
        "Zadania otwarte:\\n" + pPayload.openTasks + "\\n\\nZadania ukończone:\\n" + pPayload.doneTasks + "\\n\\n" +
        "Odpowiadaj po polsku, konkretnie, w punktach. Jeśli proponujesz zadania, używaj ścisłego formatu markdown '- [ ] Nazwa zadania: opis'.";

      const url = (localStorage.getItem("cockpit_chat_url") || "http://localhost:8317/v1").replace(/\\/$/, "");
      const model = localStorage.getItem("cockpit_chat_model") || "gemini-3.8-flash";
      const apiKey = localStorage.getItem("cockpit_chat_key") || "";

      try {
        const res = await fetch(url + "/chat/completions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(apiKey ? { "Authorization": "Bearer " + apiKey } : {})
          },
          body: JSON.stringify({
            model: model,
            messages: [
              { role: "system", content: systemPrompt },
              { role: "user", content: text }
            ],
            temperature: 0.3
          })
        });
        if (!res.ok) throw new Error("HTTP " + res.status + " " + res.statusText);
        const json = await res.json();
        const reply = json.choices?.[0]?.message?.content || "(Pusta odpowiedź)";
        renderBotReply(bMsg, reply);
      } catch (err) {
        bMsg.innerHTML = '<span style="color:var(--rose);">Błąd połączenia z API (' + escapeHtmlStr(err.message) + ').</span><br><small style="color:var(--text-faint);">Upewnij się, że lokalne proxy :8317 lub Ollama :11434 jest włączone, lub skonfiguruj endpoint w Ustawieniach API.</small>';
      }
      container.scrollTop = container.scrollHeight;
    }

    function renderBotReply(el, text) {
      el.textContent = text;
      const taskMatches = text.match(/^-\\s*\\[ \\]\\s*(.+)$/gm);
      if (taskMatches && taskMatches.length > 0) {
        const bar = document.createElement('div');
        bar.style.marginTop = '10px';
        bar.style.paddingTop = '8px';
        bar.style.borderTop = '1px solid var(--border)';
        bar.innerHTML = '<button class="btn btn-primary btn-sm" onclick="importChatTasks(' + JSON.stringify(taskMatches).replace(/"/g, '&quot;') + ')">➕ Dodaj te zadania (' + taskMatches.length + ') do To-Do</button>';
        el.appendChild(bar);
      }
    }

    function importChatTasks(matches) {
      const key = "cockpit_staged_tasks_" + PROJ_SLUG;
      const existing = JSON.parse(localStorage.getItem(key) || "[]");
      matches.forEach(m => {
        const clean = m.replace(/^-\\s*\\[ \\]\\s*/, "");
        existing.push({ title: clean, section: "Z czatu AI", desc: "Wygenerowane przez asystenta", prio: "NORMAL", target: "claude", mdLine: "- [ ] " + clean, date: new Date().toISOString() });
      });
      localStorage.setItem(key, JSON.stringify(existing));
      renderStagedTasks(PROJ_SLUG);
      switchTab('tasks');
      alert("Dodano " + matches.length + " zadań z czatu do kolejki roboczej kokpitu!");
    }

    function clearChatHistory() {
      const container = document.getElementById('chat-messages-container');
      if (container) container.innerHTML = '<div class="msg msg-bot">Czat wyczyszczony. W czym mogę pomóc?</div>';
    }

    function escapeHtmlStr(str) {
      if (!str) return "";
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // Auto-init on DOM load
    document.addEventListener('DOMContentLoaded', () => {
      renderStagedTasks(PROJ_SLUG);
      loadChatSettings();
      checkStreamLiveness();
    });
  `;
}

module.exports = { getClientScript };
