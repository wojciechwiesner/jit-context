// Renders Obsidian SSOT, Git Context stream and JIT Capsule Relevance Inspector
const { escapeHtml } = require("./html");

function renderContextTab(data) {
  const { obsidian, git, jit } = data;
  const capsule = jit.capsule || {};
  const isCapsuleGrounded = capsule.isGrounded !== false;

  return `
    <div class="grid-3" style="margin-bottom:16px;">
      <!-- Column 1: Obsidian SSOT & Knowledge -->
      <div class="card" style="display:flex; flex-direction:column; height:740px;">
        <div class="card-title">
          <span>Obsidian SSOT & Baza Wiedzy</span>
          <span class="pill ${obsidian.exists ? 'pill-emerald' : 'pill-amber'}">
            ${obsidian.exists ? 'SSOT ZNALEZIONY' : 'BRAK SSOT'}
          </span>
        </div>
        
        <div style="background:#0c1017; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-weight:700; color:#fff; font-size:13px;">${escapeHtml(obsidian.slug)}.md</span>
            <a href="${obsidian.uri}" class="btn btn-sm" style="padding:2px 8px; font-size:10px;">Otwórz w Obsidianie</a>
          </div>
          <div style="font-size:11px; color:var(--text-faint);">
            Ścieżka: <span class="mono">${escapeHtml(obsidian.path)}</span>
          </div>
          <div style="font-size:11px; color:var(--text-faint); margin-top:2px;">
            Ostatnia modyfikacja: <span class="mono" style="color:var(--text-muted);">${obsidian.mtime ? new Date(obsidian.mtime).toLocaleString("pl-PL") : "brak"}</span>
            (${obsidian.ageMinutes !== null ? (obsidian.ageMinutes < 60 ? obsidian.ageMinutes + " min temu" : Math.round(obsidian.ageMinutes/60) + " godz. temu") : "brak"})
          </div>
        </div>

        <div style="font-size:11px; font-weight:700; color:var(--cyan); margin-bottom:6px;">POWIĄZANE NOTATKI W VAULCIE (${obsidian.related ? obsidian.related.length : 0}):</div>
        <div style="max-height:160px; overflow-y:auto; margin-bottom:12px; border:1px solid var(--border); border-radius:6px; background:#0a0d14; padding:6px;">
          ${(obsidian.related || []).length > 0 ? obsidian.related.map(r => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; border-bottom:1px solid #1a202c; font-size:11px;">
              <span class="mono" style="color:#cbd5e1;">${escapeHtml(r.name)}</span>
              <a href="${r.uri}" style="color:var(--cyan); text-decoration:none; font-size:10px;">Otwórz ↗</a>
            </div>
          `).join("") : '<div style="color:var(--text-faint); padding:8px; font-size:11px;">Brak dodatkowych notatek o prefixie ' + escapeHtml(obsidian.slug) + '-*.md</div>'}
        </div>

        <div style="font-size:11px; font-weight:700; color:var(--text-muted); margin-bottom:6px;">TREŚĆ NOTATKI SSOT (PODGLĄD):</div>
        <div style="flex:1; overflow-y:auto; background:#070a0f; border:1px solid var(--border); border-radius:6px; padding:12px; font-family:ui-monospace, monospace; font-size:11px; line-height:1.45; color:#94a3b8; white-space:pre-wrap;">
          ${escapeHtml(obsidian.content || "Brak treści notatki w Obsidianie.")}
        </div>
      </div>

      <!-- Column 2: Git Context & Stream -->
      <div class="card" style="display:flex; flex-direction:column; height:740px;">
        <div class="card-title">
          <span>Git Context & Historia Commitów</span>
          <span class="pill pill-cyan mono">${escapeHtml(git.branch || "HEAD")}</span>
        </div>

        <div style="background:#0c1017; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-weight:700; color:#fff; font-size:13px;">Stan drzewa roboczego:</span>
            <span class="pill ${git.dirtyCount === 0 ? 'pill-emerald' : 'pill-amber'}">
              ${git.dirtyCount === 0 ? 'Czyste (clean)' : `${git.dirtyCount} zmienionych plików`}
            </span>
          </div>
          ${git.dirtyCount > 0 ? `
            <div style="margin-top:8px; max-height:100px; overflow-y:auto; font-size:11px;" class="mono">
              ${git.dirty.slice(0, 10).map(d => `<div style="color:var(--amber);">${escapeHtml(d)}</div>`).join("")}
              ${git.dirty.length > 10 ? `<div style="color:var(--text-faint);">... i jeszcze ${git.dirty.length - 10} plików</div>` : ''}
            </div>
          ` : ''}
        </div>

        <div style="font-size:11px; font-weight:700; color:var(--text-muted); margin-bottom:6px;">STRUMIEŃ OSTATNICH COMMITÓW (${(git.log || []).length}):</div>
        <div style="flex:1; overflow-y:auto; border:1px solid var(--border); border-radius:6px; background:#0a0d14; padding:8px;">
          ${(git.log || []).map(c => `
            <div style="padding:8px; border-bottom:1px solid #19202e; font-size:12px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                <span class="mono pill pill-cyan" style="font-size:10px; padding:1px 6px;">${escapeHtml(c.hash)}</span>
                <span style="color:var(--text-faint); font-size:11px;">${escapeHtml(c.relTime || "")}</span>
              </div>
              <div style="color:#e2e8f0; font-weight:500;">${escapeHtml(c.msg)}</div>
              <div style="color:var(--text-faint); font-size:10px; margin-top:2px;">Autor: ${escapeHtml(c.author)}</div>
            </div>
          `).join("")}
        </div>
      </div>

      <!-- Column 3: JIT Epistemic Runtime & Relevance -->
      <div class="card" style="display:flex; flex-direction:column; height:740px;">
        <div class="card-title">
          <span>JIT Context & Kapsuły</span>
          <span class="pill ${capsule.exists ? (isCapsuleGrounded ? 'pill-emerald' : 'pill-amber') : 'pill-purple'}">
            ${capsule.exists ? (isCapsuleGrounded ? 'ZGODNOŚĆ NAZWY PROJEKTU' : 'POTENCJALNY WYCIEK') : 'BRAK KAPSUŁY'}
          </span>
        </div>

        <div style="background:#0c1017; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
            <span style="font-size:11px; color:var(--text-muted);">Scope sesji:</span>
            <span class="mono pill pill-purple" style="font-size:10px;">${escapeHtml(capsule.scope || data.slug)}</span>
          </div>
          <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
            <span style="font-size:11px; color:var(--text-muted);">Złożoność (Complexity):</span>
            <span class="mono" style="color:var(--cyan); font-size:11px;">${escapeHtml(capsule.complexity || "n/d")}</span>
          </div>
          <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
            <span style="font-size:11px; color:var(--text-muted);">Pewność (Confidence):</span>
            <span class="mono" style="color:var(--emerald); font-size:11px;">${escapeHtml(capsule.confidence || "1.0")}</span>
          </div>
          <div style="display:flex; justify-content:space-between;">
            <span style="font-size:11px; color:var(--text-muted);">Trafność plików (Relevance):</span>
            <span class="mono" style="color:${isCapsuleGrounded ? 'var(--emerald)' : 'var(--amber)'}; font-weight:700;">${capsule.relevancePct !== undefined ? capsule.relevancePct + '%' : '100%'}</span>
          </div>
        </div>

        <div style="font-size:11px; font-weight:700; color:var(--text-muted); margin-bottom:6px;">CEL WSTRZYKNIĘTY DO MODELU (GOAL):</div>
        <div style="background:#0a0d14; border:1px solid var(--border); border-radius:6px; padding:10px; font-size:12px; color:#f1f5f9; margin-bottom:12px;">
          ${escapeHtml(capsule.goal || "Brak aktywnego celu w kapsule.")}
        </div>

        <div style="font-size:11px; font-weight:700; color:var(--cyan); margin-bottom:6px;">PLIKI ROBOCZE W KAPSULE (${(capsule.workingFiles || []).length}):</div>
        <div style="flex:1; overflow-y:auto; background:#0a0d14; border:1px solid var(--border); border-radius:6px; padding:8px; font-family:ui-monospace, monospace; font-size:11px; margin-bottom:12px;">
          ${(capsule.workingFiles || []).length > 0 ? capsule.workingFiles.map(wf => `
            <div style="padding:4px 6px; border-bottom:1px solid #161c27; color:#cbd5e1; display:flex; align-items:center; gap:6px;">
              <span style="color:var(--emerald);">•</span>
              <span style="word-break:break-all;">${escapeHtml(wf)}</span>
            </div>
          `).join("") : '<div style="color:var(--text-faint); padding:6px;">Brak plików w working set kapsuły.</div>'}
        </div>

        <button class="btn btn-sm" onclick="toggleCapsuleRaw()" style="width:100%; justify-content:center;">
          Pokaż / Ukryj surowy XML kapsuły
        </button>
        <div id="capsule-raw-box" style="display:none; margin-top:8px; max-height:160px; overflow-y:auto; background:#040609; border:1px solid var(--border); border-radius:6px; padding:8px; font-family:ui-monospace, monospace; font-size:10px; color:#94a3b8; white-space:pre-wrap;">
          ${escapeHtml(capsule.rawSnippet || "")}
        </div>
      </div>
    </div>
  `;
}

module.exports = { renderContextTab };
