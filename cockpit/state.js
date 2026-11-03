// Read GSD documents without requiring a checkbox-only STATE.md.
const fs = require('node:fs');
const path = require('node:path');

function read(file) {
  try { return fs.readFileSync(file, 'utf8'); } catch { return ''; }
}

function field(text, patterns, fallback = '') {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].replace(/\*\*/g, '').trim();
  }
  return fallback;
}

function documentTasks(text, source) {
  let section = 'Zadania';
  let code = false;
  return text.split('\n').flatMap((line, index) => {
    if (/^\s*```/.test(line)) code = !code;
    if (code) return [];
    const heading = line.match(/^#{1,6}\s+(.+)/);
    if (heading) section = heading[1];
    const match = line.match(/^\s*[-*]\s*\[([ xX~])\]\s*(.+)/);
    if (!match) return [];
    const text = match[2];
    const id = text.match(/^\[?([A-Za-z]\d+)\]?[:\s-]/)?.[1] || null;
    return [{ id, key: `${source}:${index + 1}`, text, done: /x/i.test(match[1]),
      partial: match[1] === '~', isBlocker: /blocker|bloker/i.test(section),
      section, source, line: index + 1, raw: line.trim() }];
  });
}

function collectState(planning) {
  const raw = read(path.join(planning, 'STATE.md'));
  const roadmap = read(path.join(planning, 'ROADMAP.md'));
  const tasks = [...documentTasks(raw, '.planning/STATE.md'),
    ...documentTasks(roadmap, '.planning/ROADMAP.md')];
  const sections = [];
  for (const task of tasks) {
    let section = sections.find(s => s.title === task.section && s.source === task.source);
    if (!section) { section = { title: task.section, source: task.source, tasks: [] }; sections.push(section); }
    section.tasks.push(task);
  }
  const done = tasks.filter(t => t.done);
  const open = tasks.filter(t => !t.done);
  const phase = field(raw, [/\*\*Current focus:\*\*\s*(.+)/i,
    /\*\*Faza aktywna:\*\*\s*(.+)/i, /^Phase:\s*(.+)/im], 'Nie określono fazy');
  const reportedProgress = field(raw, [/^\s+percent:\s*(\d+)/m, /^Progress:.*?(\d+)%/m]);
  return { exists: Boolean(raw), raw, roadmap, phase, sections, allTasks: tasks, open, done,
    status: field(raw, [/^Status:\s*(.+)/im, /^status:\s*(.+)/im], 'Brak statusu w dokumencie'),
    updated: field(raw, [/^last_updated:\s*"?([^"\n]+)/im, /\*\*Ostatnia aktualizacja:\*\*\s*(.+)/i]),
    mtime: raw ? fs.statSync(path.join(planning, 'STATE.md')).mtime.toISOString() : null,
    reportedProgress: reportedProgress === '' ? null : Number(reportedProgress),
    totalCount: tasks.length, doneCount: done.length, openCount: open.length,
    partialCount: tasks.filter(t => t.partial).length,
    progressPct: tasks.length ? Math.round(done.length / tasks.length * 100) : null,
    blockers: open.filter(t => t.isBlocker),
    milestones: tasks.filter(t => /^(?:\*\*)?Phase\s+[\d.]+:/i.test(t.text)) };
}

module.exports = { collectState, documentTasks };
