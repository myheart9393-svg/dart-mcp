"""변환 결과 숫자·문구 검증.

- docx·html: md의 숫자 토큰이 (개수까지) 전부 있어야 한다.
- pptx: 슬라이드·차트의 숫자가 전부 md에 있어야 한다(md에 없는 숫자 금지).
- 세 형식 모두: "추정:", 출처, 표본·경고, `4–5배` 범위, 투자 권유 문구의 개수 보존.

md 쪽 토큰은 파서를 거치지 않고 원문에서 바로 뽑는다. 파서가 내용을 잃어도 잡기 위해서다.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

from lxml import etree

from .parse_md import BR, LINK, TABLE_SEP, strip_nonrendered

TOKEN = re.compile(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?")
RANGE = re.compile(r"[0-9.,%]+–[0-9.,]+[^\s|)]{0,2}")
PHRASES = ("추정:", "출처", "표본", "경고", "이 보고서는 투자 권유가 아니다.")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


def tokens(text: str) -> Counter:
    """숫자 토큰(쉼표 제거, 부호 유지). 하이픈은 앞이 글자·숫자가 아닐 때만 부호로 본다."""
    out: Counter = Counter()
    for m in TOKEN.finditer(text):
        prev = text[m.start() - 1] if m.start() else ""
        before = text[m.start() - 2] if m.start() > 1 else ""
        sign = ""
        if prev in ("−", "+"):
            sign = "-" if prev == "−" else "+"
        elif prev == "-" and not (before.isalnum() or before == ")"):
            sign = "-"
        out[sign + m.group().replace(",", "")] += 1
    return out


def md_text(md: str) -> str:
    """md에서 렌더링되는 글자만 남긴다(표 구분선·링크 주소·강조 기호 제거)."""
    lines = []
    for line in strip_nonrendered(md).split("\n"):
        if TABLE_SEP.fullmatch(line):
            continue
        line = LINK.sub(r"\1", BR.sub(" ", line))
        lines.append(re.sub(r"\\([|*`_\[\]\\])", r"\1", line.replace("**", "").replace("`", "")))
    return "\n".join(lines)


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter(f"{W}p"):
        paras.append("".join((t.text or "") if t.tag == f"{W}t" else " "
                             for t in p.iter(f"{W}t", f"{W}tab")))
    return "\n".join(paras)


class _HtmlText(HTMLParser):
    INLINE_TAGS = {"strong", "b", "em", "i", "span", "code", "sup", "sub", "a"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if tag in ("style", "script"):
            self.skip += 1
        if tag not in self.INLINE_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip -= 1
        if tag not in self.INLINE_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_body and not self.skip:
            self.parts.append(data)


def html_text(path: Path) -> str:
    parser = _HtmlText()
    parser.feed(path.read_text(encoding="utf-8"))
    return "".join(parser.parts)


def _sorted_parts(z: zipfile.ZipFile, pattern: str) -> list[str]:
    names = [n for n in z.namelist() if re.fullmatch(pattern, n)]
    return sorted(names, key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))


def pptx_content(path: Path) -> tuple[str, list[str]]:
    """(슬라이드·차트 글자, 차트 수치값). 쪽 번호 필드(a:fld)와 노트는 뺀다."""
    texts: list[str] = []
    values: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name in _sorted_parts(z, r"ppt/slides/slide\d+\.xml"):
            root = etree.fromstring(z.read(name))
            for p in root.iter(f"{A}p"):
                texts.append("".join(r.findtext(f"{A}t") or "" for r in p.findall(f"{A}r")))
        for name in _sorted_parts(z, r"ppt/charts/chart\d+\.xml"):
            root = etree.fromstring(z.read(name))
            for v in root.iter(f"{C}v"):
                is_value = any(a.tag == f"{C}val" for a in v.iterancestors())
                (values if is_value else texts).append(v.text or "")
            for t in root.iter(f"{A}t"):
                texts.append(t.text or "")
    return "\n".join(texts), values


def _decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.lstrip("+"))
    except InvalidOperation:
        return None


def _phrase_counts(text: str) -> Counter:
    counts: Counter = Counter({p: text.count(p) for p in PHRASES})
    counts.update(f"범위 {m}" for m in RANGE.findall(text))
    return counts


@dataclass
class Result:
    fmt: str
    missing: list[str] = field(default_factory=list)  # md에 있는데 결과에 없는 숫자
    extra: list[str] = field(default_factory=list)  # 결과에 있는데 md에 없는 숫자
    phrases: list[str] = field(default_factory=list)  # 개수가 줄어든 문구

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or self.phrases)


def _lost_phrases(md: str, out: str) -> list[str]:
    source, result = _phrase_counts(md), _phrase_counts(out)
    return [f"{k} (md {v}, 결과 {result[k]})" for k, v in source.items() if v > result[k]]


def _lost_tokens(md: Counter, out: Counter) -> list[str]:
    return [f"{k} (md {v}, 결과 {out[k]})" for k, v in sorted((md - out).items()) for v in [md[k]]]


def verify(md: str, fmt: str, path: Path) -> Result:
    source = md_text(md)
    source_tokens = tokens(source)
    result = Result(fmt)
    if fmt == "pptx":
        text, values = pptx_content(path)
        known = {_decimal(t) for t in source_tokens}
        result.extra = sorted(t for t in tokens(text) if t not in source_tokens)
        result.extra += sorted({f"차트 {v}" for v in values if _decimal(v) not in known})
    else:
        text = docx_text(path) if fmt == "docx" else html_text(path)
        result.missing = _lost_tokens(source_tokens, tokens(text))
    result.phrases = _lost_phrases(source, text)
    return result
