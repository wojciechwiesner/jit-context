// Hub chat UI: render helpers (textContent only), file:// fallback and the browser script against a fake DOM.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { collect } = require('./collect');
const { render } = require('./render');
const chat = require('./hub_chat');
const { getChatScript } = require('./client_chat');
const { hubChatUrl } = require('./render_chat');

const SLUG = 'demo-proj';
const ENDPOINT = '/api/hub/chat';
const CSRF = 'token-123';
const HOSTILE = '<img src=x onerror=alert(1)><b>bold</b>';
const CHAT_IDS = ['chat-file-fallback', 'chat-hub-panel', 'chat-fallback-reason', 'chat-messages-container',
  'chat-model-badge', 'chat-user-input', 'chat-send-btn', 'chat-open-hub'];

class FakeElement {
  constructor(tag) { this.tagName = tag; this.className = ''; this.children = []; this.attrs = {}; this.ownText = ''; this.hidden = false; this.value = ''; this.disabled = false; }
  set innerHTML(_) { throw new Error('innerHTML must not be used'); }
  get textContent() { return this.ownText + this.children.map(c => c.textContent).join(''); }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChild(next, old) { const i = this.children.indexOf(old); assert.ok(i >= 0); this.children[i] = next; return old; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  find(cls) { return [this, ...this.children.flatMap(c => c.find ? c.find(cls) : [])].filter(e => e.className.split(' ').includes(cls)); }
}

function fakeDocument(meta = {}) {
  const byId = Object.fromEntries(CHAT_IDS.map(id => [id, new FakeElement('div')]));
  byId['chat-hub-panel'].hidden = true;
  return {
    byId,
    createElement: tag => new FakeElement(tag),
    getElementById: id => byId[id] || null,
    querySelector: selector => {
      const name = /meta\[name="([^"]+)"\]/.exec(selector)?.[1];
      if (!(name in meta)) return null;
      const node = new FakeElement('meta'); node.attrs.content = meta[name]; return node;
    },
  };
}

function hubMeta() {
  return { [chat.HUB_CHAT_META]: ENDPOINT, [chat.HUB_SLUG_META]: SLUG, [chat.HUB_CSRF_META]: CSRF };
}

function runScript(t, { protocol, meta, responses = [] }) {
  const document = fakeDocument(meta);
  const calls = [];
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    const [status, payload] = responses.shift() || [500, { error: 'no fake response' }];
    return { ok: status >= 200 && status < 300, status, json: async () => payload };
  };
  const sandbox = { document, fetch, AbortSignal, window: { location: { protocol, hash: '' } } };
  vm.runInNewContext(getChatScript(), sandbox);
  return { sandbox, document, calls };
}

function cockpitHtml(t, hubSlug) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-chat-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, '.planning'));
  const data = collect(root);
  data.hubSlug = hubSlug;
  return render(data);
}

test('message node renders model text with textContent, meta line and source chips', () => {
  const doc = fakeDocument();
  const node = chat.createMessageNode(doc, { role: 'assistant', content: HOSTILE, model: 'm-1', elapsed_ms: 1500,
    sources: [{ name: 'STATE.md', status: 'included' }, { name: 'ROADMAP.md', status: 'missing' }, { name: '<x>', status: 'error' }] });
  assert.equal(node.className, 'msg msg-bot');
  assert.equal(node.find('msg-text')[0].textContent, HOSTILE);
  assert.equal(node.find('msg-meta')[0].textContent, 'model: m-1 · 1.5 s');
  assert.deepEqual(node.find('source-chip').map(c => c.textContent), ['STATE.md', 'ROADMAP.md (brak)', '<x> (błąd odczytu)']);
  assert.equal(node.find('source-missing').length, 1);
});

test('history records: name-list sources, user bubble and error bubble with statuses', () => {
  const doc = fakeDocument();
  const history = chat.createMessageNode(doc, { role: 'assistant', content: 'ok', sources: ['README.md'] });
  assert.deepEqual(history.find('source-chip').map(c => c.textContent), ['README.md']);
  assert.equal(chat.createMessageNode(doc, { role: 'user', content: 'q' }).className, 'msg msg-user');
  const error = chat.createMessageNode(doc, { role: 'error', content: 'model nie odpowiedział', http_status: 502, upstream_status: 500, model: 'm' });
  assert.equal(error.className, 'msg msg-error');
  assert.equal(error.find('msg-meta')[0].textContent, 'Błąd HTTP 502 · dostawca: HTTP 500 · model: m');
});

test('emoji are stripped from model text, digits and Polish letters stay', () => {
  const text = 'Krok 1' + String.fromCodePoint(0x1F680) + ' zażółć #3' + String.fromCodePoint(0x2705, 0xFE0F);
  assert.equal(chat.stripEmoji(text), 'Krok 1 zażółć #3');
  assert.equal(chat.createMessageNode(fakeDocument(), { role: 'assistant', content: text }).find('msg-text')[0].textContent, 'Krok 1 zażółć #3');
});

test('recent turns skip errors, respect turn and char limits and start with a user turn', () => {
  const records = [{ role: 'user', content: 'a' }, { role: 'assistant', content: 'b' }, { role: 'user', content: 'c' },
    { role: 'error', content: 'boom' }, { role: 'user', content: 'd' }, { role: 'assistant', content: 'e' }, { role: 'user', content: 'f' }];
  assert.deepEqual(chat.recentTurns(records, 12, 1000).map(r => r.content), ['a', 'b', 'c', 'd', 'e', 'f']);
  assert.deepEqual(chat.recentTurns(records, 3, 1000).map(r => r.content), ['d', 'e', 'f']);
  assert.deepEqual(chat.recentTurns(records, 2, 1000).map(r => r.content), ['f']);
  assert.deepEqual(chat.recentTurns([{ role: 'user', content: 'x'.repeat(50) }, { role: 'user', content: 'y' }], 12, 10), [{ role: 'user', content: 'y' }]);
});

test('hub config comes from meta tags; mode depends on protocol', () => {
  assert.deepEqual(chat.readHubChatConfig(fakeDocument(hubMeta())), { endpoint: ENDPOINT, slug: SLUG, csrf: CSRF });
  assert.equal(chat.readHubChatConfig(fakeDocument({ [chat.HUB_CHAT_META]: ENDPOINT })), null);
  assert.equal(chat.chatMode('file:', null), 'file');
  assert.equal(chat.chatMode('file:', { endpoint: 'x' }), 'file');
  assert.equal(chat.chatMode('http:', { endpoint: 'x' }), 'hub');
  assert.equal(chat.chatMode('https:', null), 'unavailable');
});

test('rendered tab: hub chat button instead of the old bridge text, four quick prompts, panel hidden', t => {
  const html = cockpitHtml(t, SLUG);
  assert.equal(html.includes('Most czatu'), false);
  assert.ok(html.includes(`id="chat-open-hub" href="${hubChatUrl(SLUG)}"`));
  assert.equal(hubChatUrl(SLUG), `http://127.0.0.1:8767/hub/${SLUG}#chat`);
  assert.ok(html.includes('<div id="chat-hub-panel" hidden>'));
  for (const prompt of chat.QUICK_PROMPTS) assert.ok(html.includes(`>${prompt.label}</button>`), prompt.label);
  for (const id of CHAT_IDS) assert.ok(html.includes(`id="${id}"`), id);
  const outside = cockpitHtml(t, null);
  assert.ok(outside.includes('Projekt nie jest w rejestrze huba'));
  assert.ok(outside.includes('href="http://127.0.0.1:8767/hub"'));
});

test('file:// cockpit keeps the hub button and never calls fetch', async t => {
  const { sandbox, document, calls } = runScript(t, { protocol: 'file:', meta: {} });
  await sandbox.loadChatSettings();
  assert.equal(document.byId['chat-file-fallback'].hidden, false);
  assert.equal(document.byId['chat-hub-panel'].hidden, true);
  document.byId['chat-user-input'].value = 'pytanie';
  await sandbox.sendChatMessage();
  assert.equal(calls.length, 0);
});

test('served from the hub: history is loaded and a turn is posted with the CSRF header', async t => {
  const history = { messages: [{ role: 'user', content: 'stare pytanie' }, { role: 'assistant', content: HOSTILE, model: 'm-old', sources: ['STATE.md'] }] };
  const reply = { reply: 'nowa odpowiedź', model: 'm-new', model_origin: 'env', elapsed_ms: 900, sources: [{ name: 'STATE.md', status: 'included' }] };
  const { sandbox, document, calls } = runScript(t, { protocol: 'http:', meta: hubMeta(), responses: [[200, history], [200, reply]] });
  await sandbox.loadChatSettings();
  assert.equal(calls[0].url, `${ENDPOINT}?slug=${SLUG}`);
  assert.equal(document.byId['chat-file-fallback'].hidden, true);
  assert.equal(document.byId['chat-hub-panel'].hidden, false);
  const box = document.byId['chat-messages-container'];
  assert.equal(box.children[1].find('msg-text')[0].textContent, HOSTILE);
  assert.equal(document.byId['chat-model-badge'].textContent, 'Model: m-old');

  document.byId['chat-user-input'].value = 'co dalej?';
  await sandbox.sendChatMessage();
  const post = calls[1];
  assert.equal(post.options.method, 'POST');
  assert.equal(post.options.headers['X-JIT-Hub-CSRF'], CSRF);
  const body = JSON.parse(post.options.body);
  assert.equal(body.slug, SLUG);
  assert.deepEqual(body.messages.at(-1), { role: 'user', content: 'co dalej?' });
  assert.equal(body.messages.length, 3);
  assert.equal(box.children.at(-1).find('msg-text')[0].textContent, 'nowa odpowiedź');
  assert.equal(document.byId['chat-model-badge'].textContent, 'Model: m-new (env)');
  assert.equal(document.byId['chat-user-input'].value, '');
});

test('upstream error is shown as an error bubble and the question goes back to the input', async t => {
  const failure = { error: 'model nie odpowiedział poprawnie: HTTP 500', upstream_status: 500, model: 'm' };
  const { sandbox, document } = runScript(t, { protocol: 'https:', meta: hubMeta(), responses: [[200, { messages: [] }], [502, failure]] });
  await sandbox.loadChatSettings();
  document.byId['chat-user-input'].value = 'status?';
  await sandbox.sendChatMessage();
  const last = document.byId['chat-messages-container'].children.at(-1);
  assert.equal(last.className, 'msg msg-error');
  assert.equal(last.find('msg-text')[0].textContent, failure.error);
  assert.match(last.find('msg-meta')[0].textContent, /HTTP 502 · dostawca: HTTP 500/);
  assert.equal(document.byId['chat-user-input'].value, 'status?');
});

test('http page without the hub config explains why and does not call fetch', async t => {
  const { sandbox, document, calls } = runScript(t, { protocol: 'http:', meta: {} });
  await sandbox.loadChatSettings();
  assert.equal(calls.length, 0);
  assert.match(document.byId['chat-fallback-reason'].textContent, /nie pochodzi z huba/);
});
