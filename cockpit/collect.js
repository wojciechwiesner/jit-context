// Data collector for SOTA project cockpit
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const OBSIDIAN_VAULT = "/Users/wojciechwiesner/Documents/Wojciech";
const JIT_SESSIONS_DIR = path.join(process.env.HOME || "/Users/wojciechwiesner", ".hermes/state/ona-context/sessions");

function safeRead(filePath, fallback = "") {
  try {
    return fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf-8") : fallback;
  } catch (e) {
    return fallback;
  }
}

function runGit(root, args) {
  try {
    return execFileSync("git", args, { cwd: root, encoding: "utf-8", timeout: 8000 }).trim();
  } catch (e) {
    return "";
  }
}

function detectProjectSlug(root, planning) {
  const stateFile = path.join(planning, "STATE.md");
  if (fs.existsSync(stateFile)) {
    const text = safeRead(stateFile);
    const ssotMatch = text.match(/\*\*SSOT w Obsidianie:\*\*\s*.*?projects\/([a-zA-Z0-9_\-]+)\.md/i);
    if (ssotMatch) return ssotMatch[1].trim();
    const projMatch = text.match(/\*\*Projekt:\*\*\s*([a-zA-Z0-9_\-]+)/i);
    if (projMatch) return projMatch[1].trim().toLowerCase();
  }
  const jitJson = path.join(planning, "jit.json");
  if (fs.existsSync(jitJson)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(jitJson, "utf-8"));
      if (parsed.scope) return parsed.scope;
      if (parsed.name) return parsed.name;
    } catch (e) {}
  }
  const base = path.basename(root);
  if (/^W\d+$/i.test(base)) {
    const parentBase = path.basename(path.dirname(root));
    return parentBase.replace(/-wt$/i, "");
  }
  return base;
}

function parseTaskLine(line, section) {
  const trimmed = line.trim();
  const isOpen = /^-\s*\[ \]\s*/.test(trimmed);
  const isDone = /^-\s*\[x\]\s*/i.test(trimmed);
  if (!isOpen && !isDone) return null;
  const rawText = trimmed.replace(/^-\s*\[[ xX]\]\s*/, "");
  
  // Match leading ID like "E0 Migrations", "[W16]: Test", "T1 - Fix", "W16 Task"
  const leadingMatch = rawText.match(/^\[?([A-Za-z0-9_\-]+)\]?[:\s-]\s*(.+)$/);
  let id = null;
  let text = rawText.trim();
  if (leadingMatch && /^[A-Za-z]\d+$/i.test(leadingMatch[1])) {
    id = leadingMatch[1];
    text = leadingMatch[2].trim();
  }
  
  // Check for wave tag in text like "(W16)" or "(W1, merge ...)"
  const waveMatch = rawText.match(/\b(W\d+)\b/);
  const waveId = waveMatch ? waveMatch[1] : null;

  const isBlocker = /bloker|blocker/i.test(section) || /\[bloker\]/i.test(rawText);
  return { id: id || waveId, waveId, text, done: isDone, isBlocker, section, raw: trimmed };
}

function collectTasks(planning) {
  const file = path.join(planning, "STATE.md");
  if (!fs.existsSync(file)) return { exists: false, phase: "brak STATE.md", open: [], done: [], allTasks: [], sections: [], openCount: 0, doneCount: 0, totalCount: 0, progressPct: 0, blockers: [] };
  const text = safeRead(file);
  const lines = text.split("\n");
  let phase = "brak fazy";
  let updated = null;
  const sections = [];
  let currentSection = { title: "Wstęp", tasks: [] };
  const allTasks = [];
  const open = [];
  const done = [];
  const blockers = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^##\s+/.test(trimmed)) {
      if (currentSection.tasks.length > 0) sections.push(currentSection);
      const title = trimmed.replace(/^##\s+/, "").trim();
      currentSection = { title, tasks: [] };
      if (phase === "brak fazy" && !/bloker|blocker/i.test(title)) phase = title;
    }
    const updateMatch = trimmed.match(/\*\*Ostatnia aktualizacja:\*\*\s*([^\s*]+)/i);
    if (updateMatch) updated = updateMatch[1];
    const phaseMatch = trimmed.match(/\*\*Faza aktywna:\*\*\s*(.+)/i);
    if (phaseMatch) phase = phaseMatch[1].trim();

    const task = parseTaskLine(trimmed, currentSection.title);
    if (task) {
      allTasks.push(task);
      currentSection.tasks.push(task);
      if (task.done) done.push(task);
      else {
        open.push(task);
        if (task.isBlocker) blockers.push(task);
      }
    }
  }
  if (currentSection.tasks.length > 0) sections.push(currentSection);
  const totalCount = allTasks.length;
  const progressPct = totalCount > 0 ? Math.round((done.length / totalCount) * 100) : 0;
  return { exists: true, phase, updated, open, done, allTasks, sections, openCount: open.length, doneCount: done.length, totalCount, progressPct, blockers };
}

function collectOrchestration(planning) {
  const orchDir = path.join(planning, "orchestration");
  if (!fs.existsSync(orchDir)) return { exists: false, tasks: {}, results: {}, contracts: [], waves: [] };
  const files = fs.readdirSync(orchDir);
  const tasks = {};
  const results = {};
  const contracts = [];
  const wavesMap = {};

  for (const file of files) {
    if (!file.endsWith(".md")) continue;
    const full = path.join(orchDir, file);
    const content = safeRead(full);
    const taskMatch = file.match(/^TASK-([A-Za-z0-9_\-]+)\.md$/i) || file.match(/^([A-Za-z0-9_\-]+)\.md$/i);
    const resultMatch = file.match(/^RESULT-([A-Za-z0-9_\-]+)\.md$/i);
    if (resultMatch) {
      const id = resultMatch[1];
      const statusMatch = content.match(/Status:\s*([^\n\r]+)/i);
      results[id] = { id, file, fullPath: full, status: statusMatch ? statusMatch[1].trim() : "NIEZWERYFIKOWANE", content: content.slice(0, 4000), size: content.length };
      if (!wavesMap[id]) wavesMap[id] = { id, status: "PASS" };
      wavesMap[id].result = results[id];
      wavesMap[id].status = results[id].status;
    } else if (taskMatch && !file.startsWith("CONTRACTS")) {
      const id = taskMatch[1];
      const titleMatch = content.match(/^#\s*(.+)$/m);
      tasks[id] = { id, file, fullPath: full, title: titleMatch ? titleMatch[1].trim() : id, content: content.slice(0, 4000), size: content.length };
      if (!wavesMap[id]) wavesMap[id] = { id, status: "OPEN" };
      wavesMap[id].task = tasks[id];
      wavesMap[id].title = tasks[id].title;
    } else if (/CONTRACTS/i.test(file)) {
      contracts.push({ file, content: content.slice(0, 2500) });
    }
  }

  const waves = Object.values(wavesMap).sort((a, b) => {
    const numA = parseInt(a.id.replace(/\D/g, "")) || 0;
    const numB = parseInt(b.id.replace(/\D/g, "")) || 0;
    return numA - numB;
  });

  return { exists: true, tasks, results, contracts, waves, count: waves.length };
}

function collectObsidian(slug) {
  const notePath = path.join(OBSIDIAN_VAULT, "projects", `${slug}.md`);
  const exists = fs.existsSync(notePath);
  let content = "";
  let mtime = null;
  let ageMinutes = null;
  if (exists) {
    const stat = fs.statSync(notePath);
    mtime = stat.mtime;
    ageMinutes = Math.round((Date.now() - stat.mtimeMs) / (1000 * 60));
    content = safeRead(notePath);
  }
  const related = [];
  const projectsDir = path.join(OBSIDIAN_VAULT, "projects");
  if (fs.existsSync(projectsDir)) {
    try {
      const files = fs.readdirSync(projectsDir);
      for (const f of files) {
        if (f.startsWith(`${slug}-`) && f.endsWith(".md")) {
          const fPath = path.join(projectsDir, f);
          const fStat = fs.statSync(fPath);
          related.push({ name: f, path: fPath, size: fStat.size, mtime: fStat.mtime.toISOString(), uri: `obsidian://open?vault=Wojciech&file=projects%2F${encodeURIComponent(f)}` });
        }
      }
    } catch (e) {}
  }
  return { slug, exists, path: notePath, mtime, ageMinutes, uri: `obsidian://open?vault=Wojciech&file=projects%2F${encodeURIComponent(slug)}.md`, content: content.slice(0, 5000), related };
}

function collectJit(planning, root, slug) {
  let jitJson = null;
  const jsonPath = path.join(planning, "jit.json");
  if (fs.existsSync(jsonPath)) {
    try { jitJson = JSON.parse(fs.readFileSync(jsonPath, "utf-8")); } catch (e) {}
  }
  let capsule = null;
  const candidates = [
    path.join(JIT_SESSIONS_DIR, slug, "latest_context.xml"),
    path.join(JIT_SESSIONS_DIR, `${slug}-wt`, "latest_context.xml"),
    path.join(JIT_SESSIONS_DIR, path.basename(root), "latest_context.xml"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      try {
        const raw = fs.readFileSync(c, "utf-8");
        const goalMatch = raw.match(/Goal:\s*([^<\n\r]+)/);
        const scopeMatch = raw.match(/scope="([^"]+)"/);
        const compMatch = raw.match(/complexity="([^"]+)"/);
        const confMatch = raw.match(/confidence="([^"]+)"/);
        const wsMatch = raw.match(/\[WORKING SET & CONTRACTS\]([\s\S]*?)\[/);
        const workingFiles = [];
        if (wsMatch) {
          const fileLines = wsMatch[1].match(/•\s*([^\s(]+)/g) || [];
          for (const fl of fileLines) workingFiles.push(fl.replace(/•\s*/, "").trim());
        }
        let matched = 0;
        for (const wf of workingFiles) {
          if (fs.existsSync(path.resolve(root, wf)) || wf.includes(path.basename(root))) matched++;
        }
        const relevancePct = workingFiles.length > 0 ? Math.round((matched / workingFiles.length) * 100) : 100;
        capsule = { exists: true, path: c, scope: scopeMatch ? scopeMatch[1] : slug, goal: goalMatch ? goalMatch[1].trim() : "", complexity: compMatch ? compMatch[1] : "unknown", confidence: confMatch ? confMatch[1] : "1.0", workingFiles, relevancePct, isGrounded: relevancePct >= 70, size: raw.length, rawSnippet: raw.slice(0, 1500) };
        break;
      } catch (e) {}
    }
  }
  return { config: jitJson, capsule: capsule || { exists: false } };
}

function collectGit(root) {
  const isRepo = fs.existsSync(path.join(root, ".git")) || runGit(root, ["rev-parse", "--is-inside-work-tree"]) === "true";
  if (!isRepo) return { isRepo: false, branch: "brak gita", log: [], dirty: [], diffStat: "" };
  const branch = runGit(root, ["branch", "--show-current"]) || runGit(root, ["rev-parse", "--abbrev-ref", "HEAD"]) || "HEAD";
  const rawLog = runGit(root, ["log", "-15", '--pretty=format:%h|%s|%an|%cr|%cI']);
  const log = rawLog ? rawLog.split("\n").map(l => {
    const [hash, msg, author, relTime, iso] = l.split("|");
    return { hash, msg, author, relTime, iso };
  }) : [];
  const statusRaw = runGit(root, ["status", "--porcelain"]);
  const dirty = statusRaw ? statusRaw.split("\n").filter(Boolean) : [];
  const diffStat = runGit(root, ["diff", "--stat"]);
  return { isRepo: true, branch, log, dirty, diffStat, dirtyCount: dirty.length };
}

function collect(root) {
  const planning = path.join(root, ".planning");
  const slug = detectProjectSlug(root, planning);
  const tasks = require('./state').collectState(planning);
  const orch = collectOrchestration(planning);
  const obsidian = collectObsidian(slug);
  const jit = collectJit(planning, root, slug);
  const git = collectGit(root);
  const thoughtsRaw = safeRead(path.join(planning, "THOUGHTS.md"));
  const thoughts = thoughtsRaw ? thoughtsRaw.split("\n").filter(l => l.trim().startsWith("-")).map(l => l.replace(/^-\s*/, "")) : [];
  const architectureMeta = require('./architecture').collectArchitecture(root);
  const architecture = architectureMeta.diagram;

  return {
    chatRuntime: require('./runtime').chatRuntime(root),
    credentials: require('./credentials').collectCredentials(root),
    links: require('./links').collectLinks(root),
    root,
    slug,
    title: slug.toUpperCase(),
    generatedAt: new Date().toISOString(),
    state: tasks,
    orchestration: orch,
    obsidian,
    jit,
    git,
    thoughts,
    architecture,
    architectureMeta,
    livestream: { url: "http://127.0.0.1:8766/live", defaultSession: "20261018_163217_6298d0", port: 8766 }
  };
}

module.exports = { collect, detectProjectSlug };
