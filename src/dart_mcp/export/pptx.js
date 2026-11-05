// blocks.json → pptx. 사용법: node pptx.js <blocks.json> <out.pptx> <style.json>
// H2마다 슬라이드를 만들고, 넘치면 "(계속)" 슬라이드로 나눈다. 번호를 새로 만들지 않는다(md에 없는 숫자 금지).
const PptxGenJS = require('pptxgenjs');
const { readJson, plain, columnWeights, isIdColumn } = require('./common');

const [blocksPath, outPath, stylePath] = process.argv.slice(2);
const { meta, blocks } = readJson(blocksPath);
const style = readJson(stylePath);

const G = style.colors.green, AM = style.colors.est, F = style.font;
const DK = '262626', GR = '7F7F7F';
const W = 13.33, X = 0.6, CW = W - 2 * X;
const TOP = 1.2, BOTTOM = 6.95, BODY_H = BOTTOM - TOP;
const GAP = 0.12;
const SIZE = { p: 14, ul: 14, h3: 18, h4: 15, label: 15, verdict: 15, note: 10, source: 10, quote: 12 };

const p = new PptxGenJS();
p.layout = 'LAYOUT_WIDE';
p.title = meta.title;

// ---- 글 높이 추정 (폭 단위는 em)
const charEm = ch => {
  const c = ch.codePointAt(0);
  if (c > 0x2e80) return 1.0;
  if (ch === ' ') return 0.32;
  return 0.58;
};
const textEm = s => [...s].reduce((a, ch) => a + charEm(ch), 0);
const emIn = size => size / 72;
const LINE = 1.36; // 맑은 고딕 줄 높이 배수
function lineCount(text, widthIn, size) {
  const perLine = widthIn / emIn(size);
  return Math.max(1, Math.ceil(textEm(text) * 1.04 / perLine));
}
const textH = (text, widthIn, size) => lineCount(text, widthIn, size) * emIn(size) * LINE;

// ---- 런 변환
function runsOf(rs, size, base = {}) {
  return rs.map(r => ({ text: r.t, options: {
    fontFace: r.code ? 'Consolas' : F, fontSize: size,
    bold: !!(base.bold || r.b || r.k === 'est'), italic: !!base.italic,
    superscript: r.k === 'fn' || undefined,
    color: r.k === 'cite' ? GR : r.k === 'est' ? AM : (base.color || DK),
  } }));
}

// 긴 글을 문장 경계에서 나눈다. 숫자 토큰은 쪼개지 않는다.
function splitRuns(rs, widthIn, size, maxH) {
  const pieces = [];
  rs.forEach(r => r.t.split(/(?<=[.!?。])\s+/).forEach((seg, i, all) => {
    pieces.push({ ...r, t: seg + (i < all.length - 1 ? ' ' : '') });
  }));
  const chunks = [[]];
  let text = '';
  pieces.forEach(piece => {
    if (text && textH(text + piece.t, widthIn, size) > maxH) { chunks.push([]); text = ''; }
    chunks[chunks.length - 1].push(piece);
    text += piece.t;
  });
  return chunks;
}

// ---- 슬라이드 페이저
class Pager {
  constructor(title) { this.title = title; this.first = true; this.slide = null; this.y = TOP; this.list = null; }
  open() {
    this.flushList();
    const label = this.first ? this.title : `${this.title} (계속)`;
    this.first = false;
    this.slide = newSlide(label);
    this.y = TOP;
  }
  ensure() { if (!this.slide) this.open(); }
  room() { return BOTTOM - this.y; }
  need(h) { this.ensure(); if (h > this.room() && this.y > TOP) this.open(); }
  flushList() {
    if (!this.list) return;
    const { items, y, h } = this.list;
    this.slide.addText(items, { x: X, y, w: CW, h, valign: 'top', margin: 0, isTextBox: true });
    this.list = null;
  }
  text(rs, size, opts = {}) {
    const { base = {}, x = X, w = CW, gap = GAP } = opts;
    const maxH = BODY_H - 0.1;
    const whole = textH(plain(rs), w, size);
    if (whole > maxH) {
      splitRuns(rs, w, size, maxH).forEach(chunk => this.text(chunk, size, opts));
      return;
    }
    this.need(whole);
    this.flushList();
    if (opts.bar) this.slide.addShape(p.ShapeType.rect, { x: X, y: this.y, w: 0.07, h: whole, fill: { color: G }, line: { color: G } });
    this.slide.addText(runsOf(rs, size, base), { x, y: this.y, w, h: whole, valign: 'top', margin: 0, isTextBox: true });
    this.y += whole + gap;
  }
  bullet(item) {
    const size = item.lvl ? SIZE.ul - 1 : SIZE.ul;
    const indent = 0.28 * (item.lvl + 1);
    const w = CW - indent;
    const maxH = BODY_H - 0.1;
    if (textH(plain(item.runs), w, size) > maxH) {
      splitRuns(item.runs, w, size, maxH).forEach(chunk => this.bullet({ ...item, runs: chunk }));
      return;
    }
    const h = textH(plain(item.runs), w, size) + 0.08;
    this.ensure();
    if (h > this.room() && this.y > TOP) this.open();
    if (!this.list) this.list = { items: [], y: this.y, h: 0 };
    const rs = runsOf(item.marker ? [{ t: `${item.marker} ` }, ...item.runs] : item.runs, size);
    rs[0].options.paraSpaceAfter = 5;
    if (!item.marker) rs[0].options.bullet = { indent: 14 };
    rs[0].options.indentLevel = item.lvl;
    if (this.list.items.length) this.list.items[this.list.items.length - 1].options.breakLine = true;
    this.list.items.push(...rs);
    this.list.h += h;
    this.y += h;
  }
  endList() { if (this.list) { this.flushList(); this.y += GAP; } }
  box(paras) {
    const size = SIZE.quote, inner = CW - 0.3;
    const heights = paras.map(q => textH(plain(q), inner, size) + 0.05);
    let i = 0;
    while (i < paras.length) {
      this.ensure();
      let j = i, h = 0.16;
      while (j < paras.length && h + heights[j] <= Math.max(this.room(), BODY_H * (this.y > TOP ? 0 : 1))) { h += heights[j]; j++; }
      if (j === i) {
        if (this.y > TOP) { this.open(); continue; }
        j = i + 1; h += heights[i];
      }
      this.slide.addShape(p.ShapeType.rect, { x: X, y: this.y, w: CW, h, fill: { color: 'F2F2F2' }, line: { color: 'BFBFBF', width: 0.75 } });
      const rs = [];
      paras.slice(i, j).forEach((q, k, arr) => {
        const qr = runsOf(q, size);
        if (k < arr.length - 1) qr[qr.length - 1].options.breakLine = true;
        rs.push(...qr);
      });
      this.slide.addText(rs, { x: X + 0.15, y: this.y + 0.08, w: inner, h: h - 0.16, valign: 'top', margin: 0, isTextBox: true });
      this.y += h + GAP;
      i = j;
    }
  }
  table(b) {
    const size = b.header.length >= 7 ? 10 : b.header.length >= 5 ? 11 : 12;
    const colW = colWidths(b, size);
    const rowHs = b.rows.map(r => rowHeight(r.map(plain), colW, size));
    const headRows = headerRows(b, size);
    // 2단 머리글은 원래 머리글("가나 FY2023·연결")이 아니라 나뉜 글자로 잰다.
    const headTexts = b.groups ? b.subheader : b.header.map(plain);
    const headColW = b.groups ? colW.slice(1) : colW;
    const headH = headRows.length * rowHeight(headTexts, headColW, size);
    // 첫 조각의 캡션은 바로 위 제목·라벨과 같으므로 다시 쓰지 않는다. 이어지는 조각에만 붙인다.
    const CONT_CAP_H = 0.3;
    const total = headH + rowHs.reduce((a, c) => a + c, 0);
    this.ensure();
    this.flushList();
    const minimum = headH + rowHs.slice(0, 2).reduce((a, c) => a + c, 0);
    if (this.y > TOP && (total <= BODY_H ? total > this.room() : minimum > this.room())) this.open();
    let start = 0, firstPiece = true;
    do {
      const capH = firstPiece ? 0 : CONT_CAP_H;
      let h = capH + headH, end = start;
      while (end < b.rows.length && h + rowHs[end] <= this.room()) { h += rowHs[end]; end++; }
      if (end === start) {
        if (this.y > TOP) { this.open(); continue; }
        // 행 하나가 슬라이드보다 크다. 그대로 넣고 알린다.
        console.error(`경고: 표 ${b.n}의 행이 슬라이드보다 높다 (${plain(b.rows[start][0]).slice(0, 20)})`);
        h += rowHs[end]; end++;
      }
      if (capH) {
        this.slide.addText(`${b.caption || '표'} (계속)`, { x: X, y: this.y, w: CW, h: capH - 0.04, fontFace: F, fontSize: 12, bold: true, color: GR, margin: 0, isTextBox: true });
      }
      const rows = [...headRows, ...b.rows.slice(start, end).map(r => r.map((c, i) => ({
        text: runsOf(c, size), options: { align: b.align[i] === 'r' ? 'right' : 'left', valign: 'middle' } })))];
      const heights = [...headRows.map(() => headH / headRows.length), ...rowHs.slice(start, end)];
      this.slide.addTable(rows, { x: X, y: this.y + capH, w: CW, colW, rowH: heights, border: { type: 'solid', pt: 0.75, color: GR }, margin: [0.03, 0.08, 0.03, 0.08], fontFace: F, fontSize: size, color: DK });
      this.y += h + GAP;
      start = end;
      firstPiece = false;
      if (start < b.rows.length) this.open();
    } while (start < b.rows.length);
  }
  charts(specs) {
    const h = 4.7;
    this.need(h);
    this.flushList();
    const w = CW / specs.length;
    specs.forEach((c, i) => {
      const title = c.title + (c.unit ? ` (${c.unit})` : '');
      const data = c.series.map(s => ({ name: s.name, labels: c.categories, values: s.values }));
      const code = c.decimals ? `#,##0.${'0'.repeat(c.decimals)}` : '#,##0';
      this.slide.addChart(p.charts.BAR, data, {
        x: X + i * w, y: this.y, w: w - 0.1, h: h - 0.35, barDir: 'col', barGrouping: 'clustered', barGapWidthPct: 40,
        chartColors: style.colors.chart.slice(0, Math.max(c.series.length, 1)), showLegend: c.series.length > 1, legendPos: 'b', legendFontFace: F, legendFontSize: 11,
        showTitle: true, title, titleFontFace: F, titleFontSize: 14, titleColor: DK,
        showValue: true, dataLabelFontFace: F, dataLabelFontSize: 9, dataLabelFormatCode: code, dataLabelPosition: 'outEnd',
        catAxisLabelFontFace: F, catAxisLabelFontSize: 11, valAxisHidden: true, valGridLine: { style: 'none' }, catGridLine: { style: 'none' },
      });
    });
    this.slide.addText('표의 값으로 그린 그림', { x: X, y: this.y + h - 0.33, w: CW, h: 0.25, fontFace: F, fontSize: 10, color: GR, margin: 0, isTextBox: true });
    this.y += h + GAP;
  }
}

// ---- 표 측정
function colWidths(b, size) {
  const weights = columnWeights(b);
  const sum = weights.reduce((a, c) => a + c, 0);
  const minId = emIn(size) * 0.58 * 14 + 0.2;
  const cols = weights.map((x, i) => Math.max(isIdColumn(b, i) ? minId : 0.6, CW * x / sum));
  const scale = CW / cols.reduce((a, c) => a + c, 0);
  return cols.map(c => c * scale);
}
function rowHeight(texts, colW, size) {
  const lines = Math.max(...texts.map((t, i) => lineCount(t, colW[i] - 0.18, size)));
  return lines * emIn(size) * LINE + 0.07; // 셀 위아래 여백 0.06 + 여유
}
function headerRows(b, size) {
  const H = { bold: true, fill: { color: 'BFBFBF' }, align: 'center', valign: 'middle', fontFace: F, fontSize: size, color: DK };
  if (b.groups) {
    return [
      [{ text: plain(b.header[0]), options: { ...H, rowspan: 2 } }, ...b.groups.map(g => ({ text: g.label, options: { ...H, colspan: g.span } }))],
      b.subheader.map(s => ({ text: s, options: H })),
    ];
  }
  return [b.header.map(c => ({ text: plain(c), options: H }))];
}

// ---- 슬라이드 틀
function newSlide(title) {
  const s = p.addSlide();
  s.background = { color: 'FFFFFF' };
  const size = textEm(title) * emIn(26) > CW ? 20 : 26;
  s.addText(title, { x: X, y: 0.32, w: CW, h: 0.75, fontFace: F, fontSize: size, bold: true, color: G, margin: 0, isTextBox: true, valign: 'middle' });
  if (style.header) s.addText(style.header, { x: X, y: 0.08, w: CW, h: 0.24, fontFace: F, fontSize: 10, italic: true, color: GR, align: 'right', margin: 0, isTextBox: true });
  s.addShape(p.ShapeType.rect, { x: 0, y: 7.1, w: W, h: 0.4, fill: { color: G }, line: { color: G } });
  const foot = style.footer ? `${meta.title} · ${style.footer}` : meta.title;
  s.addText(foot, { x: X, y: 7.1, w: 10.5, h: 0.4, fontFace: F, fontSize: 11, color: 'FFFFFF', margin: 0, isTextBox: true, valign: 'middle' });
  s.slideNumber = { x: 12.1, y: 7.13, w: 0.65, h: 0.34, fontFace: F, fontSize: 12, bold: true, color: 'FFFFFF', align: 'right' };
  return s;
}

function coverSlide() {
  const s = p.addSlide();
  s.background = { color: 'FFFFFF' };
  s.addShape(p.ShapeType.rect, { x: 0, y: 5.9, w: W, h: 1.6, fill: { color: G }, line: { color: G } });
  const size = textEm(meta.title) * emIn(38) > 11.4 ? 28 : 38;
  s.addText(meta.title, { x: 0.9, y: 1.5, w: 11.5, h: 1.5, fontFace: F, fontSize: size, bold: true, color: G, margin: 0, isTextBox: true, valign: 'bottom' });
  if (meta.subtitle) s.addText(meta.subtitle, { x: 0.9, y: 3.15, w: 11.5, h: 0.6, fontFace: F, fontSize: 20, color: DK, margin: 0, isTextBox: true });
  if (meta.date) s.addText(meta.date, { x: 0.9, y: 3.8, w: 11.5, h: 0.45, fontFace: F, fontSize: 16, color: GR, margin: 0, isTextBox: true });
  if (meta.closing) s.addText(meta.closing, { x: 0.9, y: 6.4, w: 11.5, h: 0.5, fontFace: F, fontSize: 16, bold: true, color: 'FFFFFF', margin: 0, isTextBox: true });
}

function tocSlides(titles) {
  const PER = 10;
  for (let i = 0; i < titles.length; i += PER) {
    const s = newSlide(i ? '목차 (계속)' : '목차');
    titles.slice(i, i + PER).forEach((t, k) => {
      const y = TOP + 0.1 + k * 0.56;
      s.addShape(p.ShapeType.rect, { x: 1.0, y: y + 0.12, w: 0.2, h: 0.2, fill: { color: G }, line: { color: G } });
      s.addText(t, { x: 1.4, y, w: 11, h: 0.44, fontFace: F, fontSize: 18, color: DK, valign: 'middle', margin: 0, isTextBox: true });
    });
  }
}

// ---- 섹션 구성: H2(또는 H1)마다 하나. 첫 H2 앞의 인용문·글은 "개요".
const sections = [];
let current = { title: '개요', blocks: meta.cover.length ? [{ type: 'quote', paras: meta.cover }] : [] };
blocks.forEach(b => {
  if (b.type === 'h' && b.lvl <= 2) {
    if (current.blocks.length || current.title !== '개요') sections.push(current);
    current = { title: b.text, blocks: [] };
  } else current.blocks.push(b);
});
if (current.blocks.length || current.title !== '개요') sections.push(current);

function renderSection(sec) {
  const pg = new Pager(sec.title);
  pg.ensure();
  sec.blocks.forEach((b, i) => {
    if (b.type !== 'ul') pg.endList();
    const next = sec.blocks[i + 1];
    switch (b.type) {
      case 'h': {
        const size = b.lvl === 3 ? SIZE.h3 : SIZE.h4;
        // 제목만 슬라이드 끝에 남지 않게 한다.
        if (next && pg.room() < textH(b.text, CW, size) + 1.0) pg.open();
        pg.text(b.runs, size, { base: { bold: true, color: G }, gap: 0.08 });
        break;
      }
      case 'label':
        if (next && pg.room() < 1.0) pg.open();
        pg.text(b.runs, SIZE.label, { base: { bold: true, color: G }, gap: 0.06 });
        break;
      case 'verdict':
        pg.text(b.runs, SIZE.verdict, { base: { bold: true }, x: X + 0.2, w: CW - 0.2, bar: true });
        break;
      case 'note':
        pg.text(b.runs, SIZE.note, { base: { color: '595959' }, gap: 0.04 });
        break;
      case 'source':
        pg.text(b.runs, SIZE.source, { base: { color: '595959', italic: true } });
        break;
      case 'quote':
        pg.box(b.paras);
        break;
      case 'ul':
        b.items.forEach(it => pg.bullet(it));
        pg.endList();
        break;
      case 'table':
        pg.table(b);
        if (b.charts) pg.charts(b.charts);
        break;
      default:
        pg.text(b.runs, SIZE.p, b.closing ? { base: { bold: true, color: G } } : {});
    }
  });
  pg.flushList();
}

coverSlide();
const tocTitles = sections.map(s => s.title);
if (tocTitles.length) tocSlides(tocTitles);
sections.forEach(renderSection);
p.writeFile({ fileName: outPath });
