// Clickable project addresses for the cockpit ("Adresy" card).
// Source: <project>/.planning/links.json (no secrets, may be committed):
//   [{ "group": "Demo", "label": "Strona startowa", "url": "https://...", "note": "basic auth" }]
// Passwords never go here; they belong in credentials.local.json.
const fs = require("fs");
const path = require("path");

const FILE = "links.json";

function collectLinks(root) {
  const file = path.join(root, ".planning", FILE);
  if (!fs.existsSync(file)) return { groups: [], error: null };
  let raw;
  try { raw = JSON.parse(fs.readFileSync(file, "utf-8")); } catch (e) {
    return { groups: [], error: `${FILE} nie jest poprawnym JSON: ${e.message}` };
  }
  const groups = new Map();
  for (const link of Array.isArray(raw) ? raw : []) {
    if (!link || !link.url) continue;
    const name = link.group || "Inne";
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push({ label: link.label || link.url, url: link.url, note: link.note || "" });
  }
  return { groups: [...groups].map(([name, items]) => ({ name, items })), error: null };
}

module.exports = { collectLinks, FILE };
