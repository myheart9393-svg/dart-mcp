// blocks.json → docx. 사용법: node docx.js <blocks.json> <out.docx> <style.json> [pages.json]
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Tab, Table, TableRow, TableCell, Header, Footer, AlignmentType, BorderStyle,
  WidthType, ShadingType, HeadingLevel, LevelFormat, PageNumber, TabStopType, VerticalAlign, PageBreak, LeaderType,
  PageOrientation, TableLayoutType } = require('docx');
const { readJson, plain, columnLayout } = require('./common');

const [blocksPath, outPath, stylePath, pagesPath] = process.argv.slice(2);
const { meta, blocks } = readJson(blocksPath);
const style = readJson(stylePath);
const pages = pagesPath ? readJson(pagesPath) : null;

const NAVY = style.colors.navy, BLUE = style.colors.blue, ACCENT = style.colors.accent, AMBER = style.colors.est;
const GRAY = '7F7F7F';
const FONT = { ascii: style.font, hAnsi: style.font, cs: style.font, eastAsia: style.font };
const MONO = { ascii: 'Courier New', hAnsi: 'Courier New', cs: 'Courier New', eastAsia: style.font };
const CW = 9048; // 본문 폭(A4 세로, 좌우 여백 제외)
const CW_WIDE = 13980; // 본문 폭(A4 가로)
const CELL_PAD = 170; // 칸 좌우 여백(twip)

function runs(rs, base = {}) {
  return rs.map(r => {
    const size = base.size || 20;
    const o = { text: r.t, font: FONT, size, color: base.color, bold: base.bold, italics: base.italics };
    if (r.b) o.bold = true;
    if (r.k === 'cite') o.color = GRAY;
    if (r.k === 'est') { o.bold = true; o.color = AMBER; }
    if (r.k === 'fn') o.superScript = true;
    if (r.code) { o.font = MONO; o.size = Math.round(size * 0.9); }
    return new TextRun(o);
  });
}
const bx = (c = GRAY, s = 4) => ({ style: BorderStyle.SINGLE, size: s, color: c });
const boxBorders = c => ({ top: bx(c), bottom: bx(c), left: bx(c), right: bx(c) });

function textBlock(b, keepNext) {
  switch (b.type) {
    case 'label': return new Paragraph({ children: runs(b.runs, { size: 21, color: NAVY, bold: true }), spacing: { before: 160, after: 60 }, keepNext: true });
    case 'verdict': return new Paragraph({ children: runs(b.runs, { size: 20 }), spacing: { before: 60, after: 120, line: 290 },
      shading: { type: ShadingType.CLEAR, fill: 'EEF3FA', color: 'auto' }, indent: { left: 120, right: 60 },
      border: { left: { style: BorderStyle.SINGLE, size: 18, color: NAVY, space: 6 } } });
    case 'note': return new Paragraph({ children: runs(b.runs, { size: 16, color: '595959' }), spacing: { after: 30 } });
    case 'source': return new Paragraph({ children: runs(b.runs, { size: 16, color: '595959', italics: true }), spacing: { before: 60, after: 100 } });
    default: return new Paragraph({ children: runs(b.runs), keepNext, spacing: { after: 100, line: 300 } });
  }
}

const tableSize = b => (b.header.length >= 7 ? 16 : 17); // 반 포인트
const emTwips = size => size * 10; // 글자 1em의 폭(twip)

function colWidths(b, total) {
  const cols = columnLayout(b, total, emTwips(tableSize(b)), CELL_PAD).cols.map(Math.round);
  const diff = total - cols.reduce((a, c) => a + c, 0);
  cols[cols.indexOf(Math.max(...cols))] += diff;
  return cols;
}
// 세로 폭에 낱말이 다 들어가지 않는 표는 가로 페이지에 넣는다.
const isWide = b => b.type === 'table' && columnLayout(b, CW, emTwips(tableSize(b)), CELL_PAD).overflow;

function cell(rs, width, o = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA }, columnSpan: o.span, rowSpan: o.rowSpan,
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 40, bottom: 40, left: 80, right: 80 },
    borders: boxBorders(GRAY),
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    children: [new Paragraph({ alignment: o.align, keepNext: !!o.keepNext, spacing: { after: 0, line: 250 }, children: runs(rs, { size: o.size, bold: o.bold }) })],
  });
}

const PAGE_BODY = 13697, PAGE_BODY_WIDE = 9354; // 본문 높이(twip)
// 한 쪽에 넉넉히 들어가는 표만 쪽 나눔을 막는다. 못 들어가는 표를 묶으면 제목만 앞 쪽에 남는다.
function fitsOnePage(b, cols, wide) {
  const size = tableSize(b);
  const em = emTwips(size);
  const rowHeight = cells => Math.max(...cells.map((text, i) =>
    Math.ceil([...text].reduce((a, ch) => a + (ch.codePointAt(0) > 0x2e80 ? 1 : 0.58), 0) * em * 1.1 / (cols[i] - CELL_PAD)) || 1)) * em * 1.5 + 80;
  const height = [b.header.map(plain), ...b.rows.map(r => r.map(plain))].reduce((a, cells) => a + rowHeight(cells), 0);
  return height < (wide ? PAGE_BODY_WIDE : PAGE_BODY) * 0.8;
}

function table(b) {
  const wide = isWide(b);
  const total = wide ? CW_WIDE : CW;
  const cols = colWidths(b, total);
  const size = tableSize(b);
  const keep = fitsOnePage(b, cols, wide);
  const H = { fill: 'BFBFBF', bold: true, size, align: AlignmentType.CENTER, keepNext: true };
  const rows = [];
  if (b.groups) {
    let k = 1;
    const groupCells = b.groups.map(g => {
      const w = cols.slice(k, k + g.span).reduce((a, c) => a + c, 0);
      k += g.span;
      return cell([{ t: g.label }], w, { ...H, span: g.span });
    });
    rows.push(new TableRow({ tableHeader: true, children: [cell(b.header[0], cols[0], { ...H, rowSpan: 2 }), ...groupCells] }));
    rows.push(new TableRow({ tableHeader: true, children: b.subheader.map((s, i) => cell([{ t: s }], cols[i + 1], H)) }));
  } else {
    rows.push(new TableRow({ tableHeader: true, children: b.header.map((h, i) => cell(h, cols[i], H)) }));
  }
  b.rows.forEach((r, ri) => rows.push(new TableRow({ cantSplit: true, children: r.map((c, i) =>
    cell(c, cols[i], { keepNext: keep && ri < b.rows.length - 1, size, align: b.align[i] === 'r' ? AlignmentType.RIGHT : AlignmentType.LEFT })) })));
  const capText = `[표] ${b.n}${b.caption ? ' ' + b.caption : ''}`;
  const cap = new Paragraph({ keepNext: true, spacing: { before: 160, after: 60 }, children: [new TextRun({ text: capText, font: FONT, size: 18, bold: true })] });
  // 고정 레이아웃: 자동 맞춤이면 Word가 표를 페이지 밖까지 넓혀 오른쪽 열이 잘린다.
  return [cap, new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: cols, layout: TableLayoutType.FIXED, rows }), new Paragraph({ spacing: { after: 60 }, children: [] })];
}

function heading(b) {
  if (b.lvl <= 2) {
    return new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: b.text.startsWith('부록'), children: runs(b.runs, { size: 26, color: NAVY, bold: true }) });
  }
  const level = b.lvl === 3 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3;
  return new Paragraph({ heading: level, children: runs(b.runs, { size: b.lvl === 3 ? 22 : 20, color: NAVY, bold: true }) });
}

function listItem(it) {
  if (it.marker) {
    return new Paragraph({ indent: { left: 360 * (it.lvl + 1), hanging: 280 }, spacing: { after: 60, line: 290 }, children: runs([{ t: it.marker + ' ' }, ...it.runs]) });
  }
  return new Paragraph({ numbering: { reference: 'bul', level: Math.min(it.lvl, 2) }, children: runs(it.runs), spacing: { after: 60, line: 290 } });
}

// ---- 표지: 제목·부제·날짜는 md의 첫 H1·첫 인용문에서 온다.
const cover = [new Paragraph({ spacing: { before: 2600, after: 120 }, children: [new TextRun({ text: meta.title, font: FONT, size: 52, bold: true, color: BLUE })] })];
if (meta.subtitle) cover.push(new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: meta.subtitle, font: FONT, size: 26, color: ACCENT })] }));
if (meta.date) cover.push(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: meta.date, font: FONT, size: 22, color: '595959' })] }));
const coverBox = meta.cover.map(p => new Paragraph({ spacing: { after: 70, line: 270 }, children: runs(p, { size: 17 }) }));
if (meta.closing) coverBox.push(new Paragraph({ spacing: { after: 0 }, children: runs([{ t: meta.closing }], { size: 17, bold: true }) }));
cover.push(new Paragraph({ spacing: { before: 1800, after: 0 }, children: [] }));
if (coverBox.length) {
  cover.push(new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: [CW], layout: TableLayoutType.FIXED, rows: [new TableRow({ children: [new TableCell({
    width: { size: CW, type: WidthType.DXA }, borders: boxBorders('000000'), margins: { top: 100, bottom: 100, left: 160, right: 160 }, children: coverBox })] })] }));
}
cover.push(new Paragraph({ children: [new PageBreak()] }));

// ---- 목차: 쪽수는 soffice로 측정했을 때만 표시한다.
const heads = blocks.filter(b => b.type === 'h' && b.lvl <= 3);
const toc = [];
if (heads.length) {
  toc.push(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: '목 차', font: FONT, size: 36, color: NAVY })] }));
  heads.forEach(h => {
    const top = h.lvl <= 2;
    const page = pages ? pages[h.text] : undefined;
    const content = page === undefined ? [h.text] : [h.text, new Tab(), String(page)];
    toc.push(new Paragraph({ spacing: { before: top ? 160 : 40, after: 40 }, indent: { left: top ? 0 : 360 },
      tabStops: page === undefined ? undefined : [{ type: TabStopType.RIGHT, position: CW, leader: LeaderType.DOT }],
      children: [new TextRun({ children: content, font: FONT, size: top ? 21 : 19, bold: top })] }));
  });
  toc.push(new Paragraph({ children: [new PageBreak()] }));
}

// ---- 본문: 넓은 표는 앞 제목·문단, 뒤 각주·출처와 함께 가로 구역으로 묶는다.
const wideStart = new Map(); // 가로 구역이 시작하는 블록 → 끝나는 블록
blocks.forEach((b, t) => {
  if (!isWide(b)) return;
  let start = t, end = t;
  if (start > 0 && ['p', 'label'].includes(blocks[start - 1].type)) start--;
  while (start > 0 && blocks[start - 1].type === 'h') start--;
  while (blocks[end + 1] && ['note', 'source'].includes(blocks[end + 1].type)) end++;
  wideStart.set(start, end);
});
const sectionsOut = []; // [{ wide, children }]
let body = [...cover, ...toc];
let wide = false, wideEnd = -1, frontOnly = true;
const closeSection = () => {
  if (frontOnly) body.pop(); // 표지·목차 끝의 쪽 나눔이 구역 나눔과 겹쳐 빈 쪽이 생기지 않게 한다.
  if (body.length) sectionsOut.push({ wide, children: body });
  body = [];
  frontOnly = false;
};
blocks.forEach((b, i) => {
  if (wideStart.has(i)) {
    if (!wide) { closeSection(); wide = true; }
    wideEnd = Math.max(wideEnd, wideStart.get(i));
  }
  frontOnly = false;
  const nextIsTable = blocks[i + 1] && blocks[i + 1].type === 'table';
  if (b.is_caption) { /* 캡션으로 표시한다 */ }
  else if (b.type === 'h') body.push(heading(b));
  else if (b.type === 'quote') {
    b.paras.forEach(p => body.push(new Paragraph({ children: runs(p, { size: 19 }), spacing: { after: 0, line: 290 },
      shading: { type: ShadingType.CLEAR, fill: 'F2F2F2', color: 'auto' }, border: boxBorders(GRAY), indent: { left: 100, right: 100 } })));
    body.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
  } else if (b.type === 'ul') b.items.forEach(it => body.push(listItem(it)));
  else if (b.type === 'table') body.push(...table(b));
  else if (b.closing) body.push(new Paragraph({ spacing: { before: 200 }, children: runs(b.runs, { bold: true, color: NAVY }) }));
  else body.push(textBlock(b, nextIsTable));
  if (wide && i === wideEnd && !wideStart.has(i + 1)) { closeSection(); wide = false; }
});
closeSection();

// ---- 머리글·바닥글: 문구는 style JSON에서만. 쪽 번호는 항상.
const header = () => {
  if (!style.header) return new Header({ children: [new Paragraph({ children: [] })] });
  return new Header({ children: [new Paragraph({ spacing: { after: 0 }, border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: GRAY, space: 4 } },
    children: [new TextRun({ text: style.header, font: FONT, size: 17, italics: true, bold: true, color: '404040' })] })] });
};
const footer = (withPage, width = CW) => {
  const parts = [];
  if (style.footer) parts.push(new TextRun({ text: style.footer, font: FONT, size: 17, bold: true, italics: true }));
  if (withPage) parts.push(new TextRun({ children: [new Tab(), PageNumber.CURRENT], font: FONT, size: 17 }));
  return new Footer({ children: [new Paragraph({ spacing: { before: 0 }, tabStops: [{ type: TabStopType.CENTER, position: width / 2 }], children: parts })] });
};

const doc = new Document({
  title: meta.title, creator: 'dart-mcp', description: meta.subtitle || meta.title,
  styles: {
    // 숫자와 한글 사이에 Word가 자동으로 넣는 간격("1 조 7,290 억원")을 끈다.
    default: { document: { run: { font: FONT, size: 20 }, paragraph: { autoSpaceEastAsianText: false } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 26, bold: true, color: NAVY },
        paragraph: { spacing: { before: 360, after: 120 }, keepNext: true, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: 'A6A6A6', space: 2 } } } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 22, bold: true, color: NAVY }, paragraph: { spacing: { before: 240, after: 80 }, keepNext: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 20, bold: true, color: NAVY }, paragraph: { spacing: { before: 180, after: 60 }, keepNext: true, outlineLevel: 2 } },
    ] },
  numbering: { config: [{ reference: 'bul', levels: ['•', '–', '·'].map((text, level) => ({ level, format: LevelFormat.BULLET, text, alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 360 * (level + 1), hanging: 240 } } } })) }] },
  sections: sectionsOut.map((s, i) => ({
    properties: {
      titlePage: i === 0,
      page: s.wide
        ? { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE }, margin: { top: 1418, bottom: 1134, left: 1418, right: 1440, header: 720, footer: 600 } }
        : { size: { width: 11906, height: 16838 }, margin: { top: 1701, bottom: 1440, left: 1418, right: 1440, header: 720, footer: 600 } },
    },
    headers: i === 0 ? { default: header(), first: header() } : { default: header() },
    footers: i === 0 ? { default: footer(true), first: footer(false) } : { default: footer(true, s.wide ? CW_WIDE : CW) },
    children: s.children,
  })),
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(outPath, buf); });
