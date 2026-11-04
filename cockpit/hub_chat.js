// Hub chat helpers shared by the generator (node) and the browser script (injected with Function#toString).
// Every browser helper is self-contained and builds DOM with textContent only: model and file text never
// reaches innerHTML. The hub decides the chat config by injecting meta tags into the served cockpit.
const HUB_CHAT_META = 'jit-hub-chat';
const HUB_SLUG_META = 'jit-hub-slug';
const HUB_CSRF_META = 'jit-hub-csrf';
const CHAT_TAB_HASH = '#chat';
const MAX_SENT_TURNS = 12;
const MAX_SENT_CHARS = 40000;
const QUICK_PROMPTS = [
  { label: 'Status projektu', text: 'Jaki jest aktualny status projektu? Oddziel deklaracje z planu od dowodów i podaj źródła.' },
  { label: 'Co dalej', text: 'Jakie są 3 najważniejsze kolejne kroki w tym projekcie i dlaczego? Podaj źródła.' },
  { label: 'Ryzyka', text: 'Jakie są główne ryzyka i blokery projektu? Wskaż, skąd o nich wiesz, i czego brakuje w danych.' },
  { label: 'Wyjaśnij architekturę', text: 'Wyjaśnij architekturę projektu na podstawie diagramu i dokumentów. Wskaż niepewności.' },
];
const SOURCE_STATUS_LABELS = { included: 'w kontekście', missing: 'brak', error: 'błąd odczytu' };

function stripEmoji(value) {
  return String(value == null ? '' : value).replace(/[\p{Extended_Pictographic}\p{Regional_Indicator}\p{Variation_Selector}\p{Join_Control}\p{Me}]/gu, '');
}

// {endpoint, slug, csrf} from the meta tags the hub injects, or null when the page was not served by the hub.
function readHubChatConfig(doc) {
  function meta(name) {
    const node = doc.querySelector('meta[name="' + name + '"]');
    return node ? String(node.getAttribute('content') || '').trim() : '';
  }
  const config = { endpoint: meta(HUB_CHAT_META), slug: meta(HUB_SLUG_META), csrf: meta(HUB_CSRF_META) };
  return config.endpoint && config.slug && config.csrf ? config : null;
}

// 'hub' = live chat, 'file' = opened from disk, 'unavailable' = http page without the hub config.
function chatMode(protocol, config) {
  if (protocol === 'file:') return 'file';
  if ((protocol === 'http:' || protocol === 'https:') && config) return 'hub';
  return 'unavailable';
}

// Normalizes history (list of names) and live replies (list of {name, status}) to [{name, status}].
function sourceChipData(sources) {
  if (!Array.isArray(sources)) return [];
  return sources.map(function (source) {
    if (typeof source === 'string') return { name: source, status: 'included' };
    if (source && typeof source.name === 'string') return { name: source.name, status: String(source.status || 'included') };
    return null;
  }).filter(Boolean);
}

function messageMeta(record) {
  const parts = [];
  if (record.role === 'error') {
    parts.push('Błąd' + (record.http_status ? ' HTTP ' + record.http_status : ''));
    if (record.upstream_status != null) parts.push('dostawca: HTTP ' + record.upstream_status);
  }
  if (record.model) parts.push('model: ' + record.model);
  if (typeof record.elapsed_ms === 'number') parts.push((record.elapsed_ms / 1000).toFixed(1) + ' s');
  if (typeof record.ts === 'number') parts.push(new Date(record.ts * 1000).toLocaleString('pl-PL'));
  return parts.join(' · ');
}

// One chat bubble: text, meta line and source chips, all through textContent.
function createMessageNode(doc, record) {
  const labels = SOURCE_STATUS_LABELS;
  const roleClass = record.role === 'user' ? 'msg-user' : record.role === 'error' ? 'msg-error' : 'msg-bot';
  const node = doc.createElement('div');
  node.className = 'msg ' + roleClass;
  const text = doc.createElement('div');
  text.className = 'msg-text';
  text.textContent = stripEmoji(record.content);
  node.appendChild(text);
  const metaText = messageMeta(record);
  if (metaText) {
    const meta = doc.createElement('div');
    meta.className = 'msg-meta';
    meta.textContent = metaText;
    node.appendChild(meta);
  }
  const chips = sourceChipData(record.sources);
  if (chips.length) {
    const row = doc.createElement('div');
    row.className = 'source-chips';
    chips.forEach(function (chip) {
      const item = doc.createElement('span');
      item.className = 'source-chip source-' + (labels[chip.status] ? chip.status : 'other');
      item.textContent = stripEmoji(chip.name) + (chip.status === 'included' ? '' : ' (' + (labels[chip.status] || chip.status) + ')');
      row.appendChild(item);
    });
    node.appendChild(row);
  }
  return node;
}

// Recent user/assistant turns that fit the POST limit; errors and other roles never go to the model.
function recentTurns(records, maxTurns, maxChars) {
  const turns = (records || []).filter(function (r) {
    return r && (r.role === 'user' || r.role === 'assistant') && typeof r.content === 'string' && r.content.trim();
  }).map(function (r) { return { role: r.role, content: r.content }; });
  const picked = [];
  let total = 0;
  for (let i = turns.length - 1; i >= 0 && picked.length < maxTurns; i--) {
    total += turns[i].content.length;
    if (total > maxChars) break;
    picked.unshift(turns[i]);
  }
  while (picked.length && picked[0].role !== 'user') picked.shift();
  return picked;
}

const BROWSER_HELPERS = [stripEmoji, readHubChatConfig, chatMode, sourceChipData, messageMeta, createMessageNode, recentTurns];

// Constants first, then the functions: the browser copy runs the exact code the node tests exercise.
function browserHelpersSource() {
  const constants = { HUB_CHAT_META, HUB_SLUG_META, HUB_CSRF_META, SOURCE_STATUS_LABELS };
  const lines = Object.entries(constants).map(([name, value]) => `const ${name} = ${JSON.stringify(value)};`);
  return lines.concat(BROWSER_HELPERS.map(fn => fn.toString())).join('\n');
}

module.exports = { HUB_CHAT_META, HUB_SLUG_META, HUB_CSRF_META, CHAT_TAB_HASH, MAX_SENT_TURNS, MAX_SENT_CHARS,
  QUICK_PROMPTS, SOURCE_STATUS_LABELS, stripEmoji, readHubChatConfig, chatMode, sourceChipData, messageMeta,
  createMessageNode, recentTurns, browserHelpersSource };
