// Architecture diagram for the cockpit.
// Uses .planning/ARCHITECTURE.mmd when it is a real diagram; when it is missing or still
// the `jit init` starter template, builds an honest diagram from the repo structure.
const fs = require("fs");
const path = require("path");

const TEMPLATE_MARKER = /UI \/ Web Client/;
const MAX_NODES_PER_GROUP = 8;
const CODE_DIRS = ["src", "app", "backend", "frontend", "api", "server", "web", "worker",
  "workers", "scripts", "services", "lib"];
const STACK_RULES = [
  { pattern: /"next"\s*:/, label: "Next.js", group: "ui" },
  { pattern: /"react"\s*:/, label: "React", group: "ui" },
  { pattern: /"vite"\s*:/, label: "Vite", group: "ui" },
  { pattern: /"tailwindcss"\s*:/, label: "Tailwind", group: "ui" },
  { pattern: /"express"\s*:/, label: "Express", group: "backend" },
  { pattern: /\bfastapi\b/i, label: "FastAPI", group: "backend" },
  { pattern: /\bcelery\b/i, label: "Celery", group: "backend" },
  { pattern: /"@supabase\/supabase-js"\s*:/, label: "Supabase", group: "data" },
  { pattern: /"(@prisma\/client|prisma)"\s*:/, label: "Prisma", group: "data" },
  { pattern: /\b(sqlmodel|sqlalchemy)\b/i, label: "SQLModel / SQLAlchemy", group: "data" },
  { pattern: /("pg"\s*:|\basyncpg\b|\bpsycopg)/i, label: "PostgreSQL", group: "data" },
  { pattern: /("redis"\s*:|"ioredis"\s*:|^redis\b)/im, label: "Redis", group: "data" },
];
const AUTO_NOTE = "Diagram wygenerowany automatycznie ze struktury repo. Zastąp .planning/ARCHITECTURE.mmd prawdziwym diagramem.";

function readText(file) {
  try { return fs.readFileSync(file, "utf-8"); } catch (e) { return ""; }
}

function listDirs(dir) {
  try {
    return fs.readdirSync(dir, { withFileTypes: true })
      .filter(e => e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules")
      .map(e => e.name).sort();
  } catch (e) { return []; }
}

// Service names from the `services:` block of a compose file (2-space indented keys).
function composeServices(root) {
  const text = ["docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"]
    .map(name => readText(path.join(root, name))).find(Boolean) || "";
  const block = text.split(/^services:\s*$/m)[1];
  if (!block) return [];
  const body = block.split(/^\S/m)[0];
  return [...body.matchAll(/^ {2}([A-Za-z0-9_.-]+):\s*$/gm)].map(m => m[1]);
}

function detectStack(root) {
  const manifests = ["package.json", "pyproject.toml", "requirements.txt"]
    .map(name => readText(path.join(root, name))).join("\n");
  const seen = new Set();
  return STACK_RULES.filter(rule => {
    if (seen.has(rule.label) || !rule.pattern.test(manifests)) return false;
    seen.add(rule.label);
    return true;
  });
}

function nodeId(prefix, name) {
  return `${prefix}_${name.replace(/[^A-Za-z0-9]/g, "_")}`;
}

function label(text) {
  return `["${text.replace(/"/g, "'")}"]`;
}

function subgraph(id, title, nodes) {
  if (!nodes.length) return [];
  const lines = nodes.slice(0, MAX_NODES_PER_GROUP).map(n => `    ${n.id}${label(n.text)}`);
  return [`  subgraph ${id}${label(title)}`, ...lines, "  end"];
}

function collectGroups(root) {
  const stack = detectStack(root);
  const workspaces = ["apps", "packages"].flatMap(dir =>
    listDirs(path.join(root, dir)).map(name => ({ id: nodeId(dir, name), text: `${dir}/${name}` })));
  const codeDirs = listDirs(root).filter(name => CODE_DIRS.includes(name))
    .map(name => ({ id: nodeId("dir", name), text: `${name}/` }));
  const services = composeServices(root).map(name => ({ id: nodeId("svc", name), text: name }));
  const byGroup = group => stack.filter(s => s.group === group).map(s => ({ id: nodeId("st", s.label), text: s.label }));
  return {
    ui: byGroup("ui"),
    code: [...workspaces, ...codeDirs],
    backend: [...byGroup("backend"), ...services],
    data: byGroup("data"),
  };
}

function autoDiagram(root) {
  const name = path.basename(root);
  const groups = collectGroups(root);
  const lines = ["graph TD", `  ROOT(("${name.replace(/"/g, "'")}"))`];
  const sections = [["UI", "Frontend", groups.ui], ["CODE", "Moduły repo", groups.code],
    ["BACKEND", "Backend / usługi", groups.backend], ["DATA", "Dane", groups.data]];
  const present = sections.filter(([, , nodes]) => nodes.length);
  if (!present.length) return lines.concat(['  EMPTY["Nie wykryto modułów"]', "  ROOT --> EMPTY"]).join("\n");
  for (const [id, title, nodes] of present) lines.push(...subgraph(id, title, nodes));
  lines.push(`  ROOT --> ${present[0][0]}`);
  for (let i = 1; i < present.length; i++) lines.push(`  ${present[i - 1][0]} --> ${present[i][0]}`);
  return lines.join("\n");
}

function architectureFor(root) {
  const file = readText(path.join(root, ".planning", "ARCHITECTURE.mmd")).trim();
  if (file && !TEMPLATE_MARKER.test(file)) return { source: "file", mermaid: file, note: "" };
  try {
    return { source: "auto", mermaid: autoDiagram(root), note: AUTO_NOTE };
  } catch (e) {
    return { source: "auto", mermaid: `graph TD\n  ERR["Błąd generatora: ${String(e.message).replace(/"/g, "'")}"]`, note: AUTO_NOTE };
  }
}

module.exports = { architectureFor, autoDiagram, composeServices };
