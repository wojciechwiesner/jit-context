// Safe markdown -> DOM for action reports written by a model. Every piece of report text goes through
// createTextNode / textContent; links are kept only for http(s) URLs. Report HTML never reaches innerHTML.
// The functions are self-contained so the browser copy (Function#toString) runs the code the node tests cover.
const MD_SAFE_URL_RE = /^https?:\/\/[^\s]+$/i;
const MD_PICTOGRAPHIC_RE = /[\p{Extended_Pictographic}\p{Regional_Indicator}\p{Variation_Selector}\p{Join_Control}\p{Me}]/gu;

function mdCleanText(value) {
  return String(value == null ? '' : value).replace(MD_PICTOGRAPHIC_RE, '');
}

function mdSplitRow(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
}

// Pure block parser: [{type: heading|paragraph|list|code|quote|hr|table, ...}].
function mdBlocks(markdown) {
  const lines = mdCleanText(markdown).replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  const listItem = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/;
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*(```|~~~)\s*([\w-]*)\s*$/.exec(line);
    if (fence) {
      const body = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      blocks.push({ type: 'code', lang: fence[2], text: body.join('\n') });
      i++;
      continue;
    }
    const heading = /^\s*(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) { blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] }); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { blocks.push({ type: 'hr' }); i++; continue; }
    if (/^\s*\|/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = rows.filter(row => !/^\s*\|?\s*:?-{2,}/.test(row)).map(mdSplitRow);
      blocks.push({ type: 'table', header: cells[0] || [], rows: cells.slice(1) });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
      blocks.push({ type: 'quote', text: quote.join(' ') });
      continue;
    }
    const item = listItem.exec(line);
    if (item) {
      const ordered = Boolean(item[2]);
      const items = [];
      let match;
      while (i < lines.length && (match = listItem.exec(lines[i])) && Boolean(match[2]) === ordered) {
        items.push(match[3]);
        i++;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(#{1,6}\s|```|~~~|>|\||([-*+]|\d+[.)])\s)/.test(lines[i])) {
      paragraph.push(lines[i++].trim());
    }
    if (!paragraph.length) paragraph.push(lines[i++].trim());
    blocks.push({ type: 'paragraph', text: paragraph.join(' ') });
  }
  return blocks;
}

// Inline `code`, **bold**, *em* and [text](http(s) url) as DOM nodes; anything else stays plain text.
function mdAppendInline(doc, parent, text) {
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  const source = String(text);
  let last = 0;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > last) parent.appendChild(doc.createTextNode(source.slice(last, match.index)));
    let node;
    if (match[1] !== undefined) { node = doc.createElement('code'); node.textContent = match[1]; }
    else if (match[2] !== undefined) { node = doc.createElement('strong'); node.textContent = match[2]; }
    else if (match[3] !== undefined) { node = doc.createElement('em'); node.textContent = match[3]; }
    else if (MD_SAFE_URL_RE.test(match[5])) {
      node = doc.createElement('a');
      node.setAttribute('href', match[5]);
      node.setAttribute('target', '_blank');
      node.setAttribute('rel', 'noopener noreferrer');
      node.textContent = match[4];
    } else {
      node = doc.createTextNode(match[4] + ' (' + match[5] + ')');
    }
    parent.appendChild(node);
    last = pattern.lastIndex;
  }
  if (last < source.length) parent.appendChild(doc.createTextNode(source.slice(last)));
  return parent;
}

function mdTableNode(doc, block) {
  const table = doc.createElement('table');
  const head = doc.createElement('thead');
  const headRow = doc.createElement('tr');
  block.header.forEach(cell => headRow.appendChild(mdAppendInline(doc, doc.createElement('th'), cell)));
  head.appendChild(headRow);
  table.appendChild(head);
  const body = doc.createElement('tbody');
  block.rows.forEach(row => {
    const tr = doc.createElement('tr');
    row.forEach(cell => tr.appendChild(mdAppendInline(doc, doc.createElement('td'), cell)));
    body.appendChild(tr);
  });
  table.appendChild(body);
  return table;
}

function mdBlockNode(doc, block) {
  if (block.type === 'heading') return mdAppendInline(doc, doc.createElement('h' + Math.min(block.level + 1, 6)), block.text);
  if (block.type === 'hr') return doc.createElement('hr');
  if (block.type === 'table') return mdTableNode(doc, block);
  if (block.type === 'quote') return mdAppendInline(doc, doc.createElement('blockquote'), block.text);
  if (block.type === 'code') {
    const pre = doc.createElement('pre');
    const code = doc.createElement('code');
    code.textContent = block.text;
    pre.appendChild(code);
    return pre;
  }
  if (block.type === 'list') {
    const list = doc.createElement(block.ordered ? 'ol' : 'ul');
    block.items.forEach(item => list.appendChild(mdAppendInline(doc, doc.createElement('li'), item)));
    return list;
  }
  return mdAppendInline(doc, doc.createElement('p'), block.text);
}

// Replaces the container's content with the rendered report; returns the number of blocks.
function renderSafeMarkdown(doc, container, markdown) {
  container.textContent = '';
  const blocks = mdBlocks(markdown);
  blocks.forEach(block => container.appendChild(mdBlockNode(doc, block)));
  return blocks.length;
}

const MARKDOWN_HELPERS = [mdCleanText, mdSplitRow, mdBlocks, mdAppendInline, mdTableNode, mdBlockNode, renderSafeMarkdown];

function markdownHelpersSource() {
  return [`const MD_SAFE_URL_RE = ${MD_SAFE_URL_RE};`, `const MD_PICTOGRAPHIC_RE = ${MD_PICTOGRAPHIC_RE};`]
    .concat(MARKDOWN_HELPERS.map(fn => fn.toString())).join('\n');
}

module.exports = { mdCleanText, mdBlocks, mdAppendInline, renderSafeMarkdown, markdownHelpersSource };
