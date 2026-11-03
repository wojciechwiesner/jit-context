// Select a real project diagram before falling back to a labelled repository map.
const fs = require('node:fs');
const path = require('node:path');
const { architectureFor } = require('./arch');
function read(file) { try { return fs.readFileSync(file, 'utf8'); } catch { return ''; } }
function collectArchitecture(root) {
  const source = '.planning/ARCHITECTURE.mmd';
  const explicit = read(path.join(root, source));
  if (explicit && !/UI \/ Web Client/.test(explicit)) {
    return { diagram: explicit, source, inferred: false };
  }
  for (const file of ['docs/02_architecture.md', 'docs/system_map.md', 'docs/ARCHITECTURE.md', 'README.md']) {
    const diagram = read(path.join(root, file)).match(/```mermaid\s*\n([\s\S]*?)```/)?.[1];
    if (diagram) return { diagram: diagram.trim(), source: file, inferred: false };
  }
  const fallback = architectureFor(root);
  return { diagram: fallback.mermaid, source: 'Struktura repozytorium (mapa, nie zweryfikowany przepływ)', inferred: true };
}
module.exports = { collectArchitecture };
