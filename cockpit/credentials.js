// Project access credentials for the cockpit (local only, never committed).
// Source: <project>/.planning/credentials.local.json (chmod 600, git-ignored):
//   [{ "label": "Demo dla Zarządu", "url": "https://...", "user": "zarzad", "pass": "..." },
//    { "label": "...", "url": "...", "env_file": "~/.config/x/deploy.env", "user_var": "U", "pass_var": "P" }]
// Passwords are embedded only when state.html is NOT tracked by git; otherwise the
// cockpit shows a blocking notice instead of secrets.
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const FILE = "credentials.local.json";

function expandHome(p) {
  return p && p.startsWith("~/") ? path.join(os.homedir(), p.slice(2)) : p;
}

function readEnvFile(file) {
  const values = {};
  try {
    for (const line of fs.readFileSync(expandHome(file), "utf-8").split("\n")) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m) values[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  } catch { /* missing env file -> entry marked unresolved */ }
  return values;
}

function isTracked(root, relPath) {
  try {
    execFileSync("git", ["-C", root, "ls-files", "--error-unmatch", relPath], { stdio: "ignore" });
    return true;
  } catch { return false; }
}

function resolveEntry(entry) {
  if (!entry.env_file) return { ...entry, source: FILE };
  const env = readEnvFile(entry.env_file);
  const user = entry.user || env[entry.user_var] || "";
  const pass = env[entry.pass_var] || "";
  return { label: entry.label, url: entry.url, note: entry.note, user, pass, source: entry.env_file, unresolved: !pass };
}

function collectCredentials(root) {
  const file = path.join(root, ".planning", FILE);
  if (!fs.existsSync(file)) return { entries: [], blocked: null };
  let raw;
  try { raw = JSON.parse(fs.readFileSync(file, "utf-8")); } catch (e) {
    return { entries: [], blocked: `${FILE} nie jest poprawnym JSON: ${e.message}` };
  }
  if (isTracked(root, `.planning/${FILE}`)) return { entries: [], blocked: `${FILE} jest w gicie. Usuń go z repo (git rm --cached) i dodaj do .gitignore.` };
  if (isTracked(root, ".planning/state.html")) return { entries: [], blocked: "state.html jest śledzony przez gita, więc hasła nie zostały wpisane." };
  return { entries: (Array.isArray(raw) ? raw : []).map(resolveEntry), blocked: null };
}

module.exports = { collectCredentials, FILE };
