"""DART 원문 ZIP/XML → 텍스트(Markdown) 변환."""

from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

# XML 선언: <?xml version="1.0" encoding="euc-kr"?>
_XML_DECL_RE = re.compile(
    rb"^\s*<\?xml[^>]*?encoding\s*=\s*['\"]([A-Za-z0-9_.:-]+)['\"][^>]*\?>", re.S
)
_XML_DECL_ANY_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)

# DART 원문에서 흔히 쓰이는 HTML 전용 엔티티 → lxml이 모르므로 미리 치환
_ENTITY_MAP = {
    "&nbsp;": " ",
    "&cr;": "\n",
    "&middot;": "·",
    "&bull;": "•",
    "&ldquo;": "“",
    "&rdquo;": "”",
    "&lsquo;": "‘",
    "&rsquo;": "’",
    "&ndash;": "–",
    "&mdash;": "—",
    "&hellip;": "…",
    "&times;": "×",
    "&divide;": "÷",
    "&plusmn;": "±",
    "&deg;": "°",
    "&copy;": "©",
    "&reg;": "®",
    "&trade;": "™",
    "&permil;": "‰",
    "&euro;": "€",
    "&yen;": "¥",
    "&pound;": "£",
    "&cent;": "¢",
    "&sect;": "§",
    "&para;": "¶",
    "&larr;": "←",
    "&rarr;": "→",
    "&uarr;": "↑",
    "&darr;": "↓",
}
_ENTITY_RE = re.compile("|".join(re.escape(k) for k in _ENTITY_MAP))

BLOCK_TAGS = {
    "DOCUMENT", "DOCUMENT-NAME", "COMPANY-NAME", "FORMULA-VERSION", "BODY",
    "SECTION", "LIBRARY", "COVER", "COVER-TITLE", "P", "DIV", "LI", "UL", "OL",
    "IMAGE", "SUMMARY", "CORRECTION", "DATE",
}
CELL_TAGS = {"TD", "TE", "TH"}
ROW_TAGS = {"TR"}


# --------------------------------------------------------------------------- ZIP
def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    """ZIP 파일명이 UTF-8 플래그 없이 CP949로 들어있는 경우 복원."""
    if info.flag_bits & 0x800:  # UTF-8 flag set
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def extract_from_zip(zip_bytes: bytes) -> list[tuple[str, bytes]]:
    """ZIP 안의 (파일명, 내용) 목록을 반환한다."""
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out.append((_fix_zip_name(info), zf.read(info)))
    return out


# --------------------------------------------------------------------------- 인코딩
def detect_declared_encoding(raw: bytes) -> str | None:
    """XML 선언에 적힌 encoding 속성값. 없으면 None."""
    m = _XML_DECL_RE.match(raw[:512])
    return m.group(1).decode("ascii") if m else None


_KOREAN_ALIASES = {
    "euc-kr", "ks-c-5601-1987", "ks-c-5601", "ksc5601", "cp949",
    "x-windows-949", "windows-949", "ms949",
}


def decode_dart_xml(raw: bytes) -> tuple[str, str]:
    """바이트 → (문자열, 실제 사용한 인코딩). 선언 → cp949 → utf-8 순으로 시도."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"

    candidates: list[str] = []
    declared = detect_declared_encoding(raw)
    if declared:
        norm = declared.lower().replace("_", "-")
        if norm in _KOREAN_ALIASES:
            norm = "cp949"  # cp949 ⊃ euc-kr
        candidates.append(norm)
    for fb in ("cp949", "utf-8"):
        if fb not in candidates:
            candidates.append(fb)

    for enc in candidates:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("cp949", errors="replace"), "cp949(replace)"


# --------------------------------------------------------------------------- 텍스트 정리
def _norm_inline(s: str) -> str:
    """셀/인라인 텍스트: 모든 공백·개행을 단일 공백으로."""
    return re.sub(r"\s+", " ", s).strip()


def _finalize(text: str) -> str:
    """줄 단위 trim, 줄 안 연속 공백 축약, 3개 이상 개행 → 빈 줄 1개."""
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# --------------------------------------------------------------------------- 렌더러
class _Renderer:
    def __init__(self, seen_tags: set[str] | None = None):
        self.seen_tags = seen_tags if seen_tags is not None else set()
        self.buf: list[str] = []

    def _tag(self, el: etree._Element) -> str:
        tag = el.tag
        if not isinstance(tag, str):  # comment / processing instruction
            return ""
        tag = tag.split("}")[-1].upper()
        self.seen_tags.add(tag)
        return tag

    @staticmethod
    def _text_of(el: etree._Element) -> str:
        """하위 전체 텍스트 (중첩 TABLE 등은 평문으로 납작하게)."""
        return "".join(el.itertext())

    def render(self, root: etree._Element) -> str:
        self._walk(root)
        return "".join(self.buf)

    def _walk(self, el: etree._Element) -> None:
        tag = self._tag(el)
        if tag == "":
            if el.tail:
                self.buf.append(el.tail)
            return

        if tag == "TITLE":
            title = _norm_inline(self._text_of(el))
            if title:
                self.buf.append(f"\n\n## {title}\n\n")
        elif tag == "TABLE":
            self.buf.append("\n\n" + self._render_table(el) + "\n\n")
        elif tag in ("BR", "PGBRK"):
            self.buf.append("\n")
        else:
            is_block = tag in BLOCK_TAGS or tag.startswith("SECTION")
            if is_block:
                self.buf.append("\n")
            if el.text:
                self.buf.append(el.text)
            for child in el:
                self._walk(child)
            if is_block:
                self.buf.append("\n")

        if el.tail:
            self.buf.append(el.tail)

    # --- tables
    def _iter_rows(self, table: etree._Element):
        """TABLE 직속 또는 THEAD/TBODY/TFOOT 아래의 TR을 순서대로."""
        for child in table:
            tag = self._tag(child)
            if tag in ROW_TAGS:
                yield child
            elif tag in ("THEAD", "TBODY", "TFOOT"):
                for tr in child:
                    if self._tag(tr) in ROW_TAGS:
                        yield tr
            # COLGROUP/COL/CAPTION 등은 무시 (태그 이름만 seen_tags에 기록)

    def _render_table(self, table: etree._Element) -> str:
        rows: list[list[str]] = []
        for tr in self._iter_rows(table):
            cells: list[str] = []
            for cell in tr:
                ctag = self._tag(cell)
                if ctag not in CELL_TAGS:
                    continue
                text = _norm_inline(self._text_of(cell)).replace("|", "\\|")
                cells.append(text)
                try:
                    span = int(cell.get("COLSPAN") or cell.get("colspan") or 1)
                except ValueError:
                    span = 1
                cells.extend([""] * max(span - 1, 0))
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        ncol = max(len(r) for r in rows)
        rows = [r + [""] * (ncol - len(r)) for r in rows]

        def fmt(r: list[str]) -> str:
            return "| " + " | ".join(r) + " |"

        out = [fmt(rows[0]), "|" + "---|" * ncol]
        out.extend(fmt(r) for r in rows[1:])
        return "\n".join(out)


# --------------------------------------------------------------------------- 공개 API
def parse_dart_xml(raw: bytes | str, *, seen_tags: set[str] | None = None) -> str:
    """DART 원문 XML(bytes) → Markdown 풍 텍스트(UTF-8 str).

    seen_tags 집합을 넘기면 파싱 중 만난 태그 이름(대문자)을 수집해 준다.
    """
    if isinstance(raw, bytes):
        text, _enc = decode_dart_xml(raw)
    else:
        text = raw

    # lxml은 encoding 선언이 있는 str을 거부하므로 선언 제거 후 utf-8 bytes로 파싱
    text = _XML_DECL_ANY_RE.sub("", text, count=1)
    text = _ENTITY_RE.sub(lambda m: _ENTITY_MAP[m.group(0)], text)

    parser = etree.XMLParser(recover=True, huge_tree=True, encoding="utf-8", resolve_entities=False)
    root = etree.fromstring(text.encode("utf-8"), parser=parser)
    if root is None:
        return ""

    renderer = _Renderer(seen_tags)
    return _finalize(renderer.render(root))
