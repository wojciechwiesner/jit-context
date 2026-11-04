// Shared presentation helpers: text is untrusted and product UI is emoji-free.
const { esc } = require('./html');
function clean(text) {
  return String(text ?? '').replace(/[\p{Extended_Pictographic}\p{Regional_Indicator}\uFE0E\uFE0F\u200D\u20E3]/gu, '');
}
function cleanData(value) { return JSON.parse(clean(JSON.stringify(value))); }
function inline(text) {
  return esc(clean(text)).replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
function documentHtml(text) {
  const lines = clean(text).replace(/^---\n[\s\S]*?\n---\s*\n/, '').split('\n');
  let code = false;
  return lines.map(line => {
    if (/^\s*```/.test(line)) { code = !code; return code ? '<pre class="document-code">' : '</pre>'; }
    if (code) return esc(line) + '\n';
    const heading = line.match(/^(#{1,6})\s+(.+)/);
    if (heading) { const level = Math.min(heading[1].length + 1, 5); return `<h${level}>${inline(heading[2])}</h${level}>`; }
    if (/^\s*[-*]\s+/.test(line)) return `<div class="document-bullet">${inline(line.replace(/^\s*[-*]\s+/, ''))}</div>`;
    if (/^\|/.test(line)) return `<div class="document-table-row">${inline(line)}</div>`;
    return line.trim() ? `<p>${inline(line)}</p>` : '<div class="document-space"></div>';
  }).join('');
}
function icon(name) {
  const paths = {
    overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    tasks: '<path d="m4 7 2 2 4-4M13 7h7M4 16l2 2 4-4M13 16h7"/>',
    arch: '<rect x="8" y="2" width="8" height="5" rx="1"/><rect x="2" y="17" width="8" height="5" rx="1"/><rect x="14" y="17" width="8" height="5" rx="1"/><path d="M12 7v5H6v5m6-5h6v5"/>',
    context: '<path d="M4 3h7a3 3 0 0 1 3 3v15a4 4 0 0 0-4-3H4zm16 0h-3v15h3z"/>',
    stats: '<path d="M3 21h18M6 17v-6m5 6V5m5 12v-9m4 9v-4"/>',
    stream: '<rect x="2" y="4" width="20" height="14" rx="2"/><path d="m10 8 5 3-5 3zM8 22h8m-4-4v4"/>',
    chat: '<path d="M21 15a3 3 0 0 1-3 3H8l-5 4V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3z"/>',
    actions: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
    thoughts: '<path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8m-8 4h6"/>',
  };
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${paths[name] || paths.overview}</svg>`;
}
module.exports = { clean, cleanData, inline, documentHtml, icon };
