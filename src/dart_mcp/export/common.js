// docx.js·pptx.js 공용: blocks.json 읽기와 표 열 너비 계산.
const fs = require('fs');

const readJson = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const plain = rs => rs.map(r => r.t).join('');
// 글자 폭 단위: 한글·한자는 영문·숫자의 약 1.8배.
const textUnits = s => [...s].reduce((a, ch) => a + (ch.codePointAt(0) > 0x2e80 ? 1.8 : 1), 0);

// 표의 열별 상대 너비. 숫자 열은 좁게, 글 열은 내용 길이에 비례(상한 있음).
function columnWeights(b) {
  const n = b.header.length;
  const lens = Array(n).fill(4);
  [b.header, ...b.rows].forEach(r => r.forEach((c, i) => { lens[i] = Math.max(lens[i], textUnits(plain(c))); }));
  return lens.map((l, i) => (b.align[i] === 'r' ? Math.min(Math.max(l, 7), 13) : Math.min(Math.max(l, 8), 46)));
}

const MAX_HANGUL_RUN_EM = 5; // 긴 한글은 어디서든 줄을 바꿀 수 있으니 이만큼만 보장한다.
const MAX_TOKEN_EM = 16; // 아주 긴 영문·경로가 다른 열을 다 먹지 않게 한다.

// 줄바꿈 없이 한 줄에 있어야 할 낱말의 폭(em). 숫자·영문은 통째로, 한글은 일부만.
function tokenEm(token) {
  let em = 0, run = 0;
  for (const ch of token) {
    if (ch.codePointAt(0) > 0x2e80) {
      run += 1;
      if (run <= MAX_HANGUL_RUN_EM) em += 1;
    } else {
      run = 0;
      em += 0.58;
    }
  }
  return Math.min(em, MAX_TOKEN_EM);
}

// 열마다 끊기면 안 되는 가장 긴 낱말의 폭(em). 범위 표기는 en dash 뒤에서 줄을 바꿀 수 있다.
function columnMinEm(b, i) {
  const cells = [b.subheader && i > 0 ? b.subheader[i - 1] : plain(b.header[i]), ...b.rows.map(r => plain(r[i]))];
  let longest = 0;
  cells.forEach(text => text.split(/\s+|(?<=–)/).forEach(token => { longest = Math.max(longest, tokenEm(token)); }));
  return longest;
}

// 열 너비: 낱말 폭(최소)을 먼저 주고 남는 폭을 상대 너비대로 나눈다. 합은 항상 total이다.
// em·pad는 total과 같은 단위. overflow=true면 최소 폭만으로도 total을 넘어 비율로 줄였다는 뜻이다.
function columnLayout(b, total, em, pad) {
  const mins = b.header.map((_, i) => columnMinEm(b, i) * em + pad);
  const minSum = mins.reduce((a, c) => a + c, 0);
  if (minSum >= total) return { cols: mins.map(m => m * total / minSum), minSum, overflow: true };
  const weights = columnWeights(b);
  const weightSum = weights.reduce((a, c) => a + c, 0);
  return { cols: mins.map((m, i) => m + (total - minSum) * weights[i] / weightSum), minSum, overflow: false };
}

module.exports = { readJson, plain, columnLayout };
