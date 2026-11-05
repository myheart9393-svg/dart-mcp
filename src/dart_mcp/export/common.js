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
// rcept_no(14자리) 열인지: 줄바꿈되지 않게 최소 너비를 준다.
const isIdColumn = (b, i) => b.rows.some(r => /\d{14}/.test(plain(r[i])));

module.exports = { readJson, plain, textUnits, columnWeights, isIdColumn };
