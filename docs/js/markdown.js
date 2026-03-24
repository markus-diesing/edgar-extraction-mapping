/**
 * renderMarkdown(raw) — lightweight markdown-to-HTML renderer.
 *
 * Handles: bold, italic, inline code, links, headings (h1-h4), horizontal
 * rules, blockquotes, unordered lists, ordered lists, fenced code blocks,
 * and pipe tables.
 *
 * Shared by docs/index.html (document reader panel) and
 * docs/user_manual.html (embedded chat).  The chat system prompt
 * constrains Claude to avoid tables and headings, so those features are
 * available but rarely exercised in the chat context.
 */
function renderMarkdown(raw) {
  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  // Tables
  function renderTable(block) {
    const rows = block.trim().split('\n');
    if (rows.length < 2) return '<p>' + rows.map(r => esc(r)).join('<br>') + '</p>';
    let html = '<table>';
    rows.forEach((row, i) => {
      if (/^\s*\|?[-:| ]+\|?\s*$/.test(row)) return;
      const cells = row.replace(/^\||\|$/g,'').split('|');
      const tag = i === 0 ? 'th' : 'td';
      html += '<tr>' + cells.map(c => `<${tag}>${inline(c.trim())}</${tag}>`).join('') + '</tr>';
    });
    return html + '</table>';
  }

  function inline(s) {
    return s
      .replace(/`([^`]+)`/g, (_, c) => `<code>${esc(c)}</code>`)
      .replace(/\*\*([^*]+)\*\*/g, (_, b) => `<strong>${esc(b)}</strong>`)
      .replace(/\*([^*\n]+)\*/g, (_, i) => `<em>${esc(i)}</em>`)
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, u) => `<a href="${esc(u)}" target="_blank">${esc(t)}</a>`);
  }

  const lines = raw.split('\n');
  let html = '';
  let listItems = [];
  let listType = '';
  let inPre = false;
  let preContent = '';
  let paraLines = [];

  function flushList() {
    if (listItems.length) {
      html += `<${listType}>${listItems.map(li => `<li>${inline(li)}</li>`).join('')}</${listType}>`;
      listItems = []; listType = '';
    }
  }
  function flushPara() {
    if (paraLines.length) {
      html += `<p>${inline(paraLines.join(' '))}</p>`;
      paraLines = [];
    }
  }

  // Detect table blocks first (header row followed by separator row)
  const tableRanges = [];
  let ti = 0;
  while (ti < lines.length) {
    if (lines[ti].includes('|') && ti + 1 < lines.length && /^\s*\|?[-:| ]+\|?\s*$/.test(lines[ti + 1])) {
      let te = ti + 1;
      while (te < lines.length && lines[te].includes('|')) te++;
      tableRanges.push([ti, te]);
      ti = te;
    } else ti++;
  }

  for (let i = 0; i < lines.length; i++) {
    const inTable = tableRanges.find(([s, e]) => i >= s && i < e);
    if (inTable) {
      if (i === inTable[0]) {
        flushList(); flushPara();
        html += renderTable(lines.slice(inTable[0], inTable[1]).join('\n'));
      }
      i = inTable[1] - 1;
      continue;
    }

    const line = lines[i];
    // Code fence
    if (line.startsWith('```')) {
      if (!inPre) { flushList(); flushPara(); inPre = true; preContent = ''; continue; }
      html += `<pre><code>${esc(preContent.trimEnd())}</code></pre>`;
      inPre = false; continue;
    }
    if (inPre) { preContent += line + '\n'; continue; }

    const stripped = line.trimEnd().trim();

    // HR
    if (/^[-*_]{3,}$/.test(stripped)) { flushList(); flushPara(); html += '<hr>'; continue; }
    // Headings
    const hm = stripped.match(/^(#{1,4})\s+(.*)/);
    if (hm) { flushList(); flushPara(); const lvl = hm[1].length; html += `<h${lvl}>${inline(hm[2])}</h${lvl}>`; continue; }
    // Blockquote
    if (stripped.startsWith('> ')) { flushList(); flushPara(); html += `<blockquote>${inline(stripped.slice(2))}</blockquote>`; continue; }
    // Ordered list
    const olm = stripped.match(/^\d+\.\s+(.*)/);
    if (olm) { flushPara(); if (listType !== 'ol') { flushList(); listType = 'ol'; } listItems.push(olm[1]); continue; }
    // Unordered list
    const ulm = stripped.match(/^[-*]\s+(.*)/);
    if (ulm) { flushPara(); if (listType !== 'ul') { flushList(); listType = 'ul'; } listItems.push(ulm[1]); continue; }
    // Blank line
    if (!stripped) { flushList(); flushPara(); continue; }
    // Normal paragraph line
    flushList();
    paraLines.push(stripped);
  }
  flushList(); flushPara();
  return html || `<p>${esc(raw)}</p>`;
}
