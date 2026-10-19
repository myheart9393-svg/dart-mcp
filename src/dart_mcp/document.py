"""DART 원문 ZIP/XML → 텍스트(Markdown) 변환 및 섹션 구조화."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import asdict, dataclass

from lxml import etree

# XML 선언: <?xml version="1.0" encoding="euc-kr"?>
_XML_DECL_RE = re.compile(
    rb"^\s*<\?xml[^>]*?encoding\s*=\s*['\"]([A-Za-z0-9_.:-]+)['\"][^>]*\?>", re.S
)
_XML_DECL_ANY_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)
_SECTION_RE = re.compile(r"^SECTION-(\d+)$")

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
    "DOCUMENT", "COMPANY-NAME", "BODY", "SECTION", "LIBRARY", "COVER",
    "P", "DIV", "LI", "UL", "OL", "IMAGE", "IMG-CAPTION", "CORRECTION", "DATE", "TABLE-GROUP",
}
# 문서 메타데이터: 본문 텍스트가 아니므로 출력하지 않음
SKIP_TAGS = {"FORMULA-VERSION", "SUMMARY", "EXTRACTION"}
# 문서 제목급 → "# " 헤딩
H1_TAGS = {"DOCUMENT-NAME", "COVER-TITLE"}
# TD: 일반 셀, TH: 머리글 셀, TE: 코드(ACODE) 값 셀, TU: 단위/코드 값 셀(AUNITVALUE)
CELL_TAGS = {"TD", "TE", "TH", "TU"}
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
    text = text.strip()
    return text + "\n" if text else ""


def _tag_name(el: etree._Element) -> str:
    tag = el.tag
    if not isinstance(tag, str):  # comment / processing instruction
        return ""
    return tag.split("}")[-1].upper()


def _section_level(el: etree._Element) -> int | None:
    m = _SECTION_RE.match(_tag_name(el))
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- 렌더러
class _Renderer:
    def __init__(self, seen_tags: set[str] | None = None, *, skip_sections: bool = False):
        self.seen_tags = seen_tags if seen_tags is not None else set()
        self.skip_sections = skip_sections  # True면 SECTION-* 하위는 건너뜀 (섹션 밖 본문만 렌더)
        self.buf: list[str] = []

    def _tag(self, el: etree._Element) -> str:
        tag = _tag_name(el)
        if tag:
            self.seen_tags.add(tag)
        return tag

    @staticmethod
    def _text_of(el: etree._Element) -> str:
        """하위 전체 텍스트 (중첩 TABLE 등은 평문으로 납작하게)."""
        return "".join(el.itertext())

    def render(self, root: etree._Element) -> str:
        self._walk(root, is_root=True)
        return "".join(self.buf)

    def _walk(self, el: etree._Element, *, is_root: bool = False) -> None:
        tag = self._tag(el)
        if tag == "":
            if el.tail:
                self.buf.append(el.tail)
            return

        if tag in SKIP_TAGS:
            pass
        elif self.skip_sections and not is_root and _section_level(el) is not None:
            pass
        elif tag in H1_TAGS:
            title = _norm_inline(self._text_of(el))
            if title:
                self.buf.append(f"\n\n# {title}\n\n")
        elif tag == "TITLE":
            title = _norm_inline(self._text_of(el))
            if title:
                self.buf.append(f"\n\n## {title}\n\n")
        elif tag == "IMG":
            self.buf.append("\n[이미지]\n")
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

        if el.tail and not is_root:
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

    @staticmethod
    def _span(cell: etree._Element, name: str) -> int:
        try:
            return max(int(cell.get(name) or cell.get(name.lower()) or 1), 1)
        except ValueError:
            return 1

    def _render_table(self, table: etree._Element) -> str:
        """격자 방식으로 배치: ROWSPAN이 차지한 칸은 다음 행에서 빈 셀로 건너뛴다."""
        rows: list[list[str]] = []
        # 열 인덱스 → 앞 행의 ROWSPAN 때문에 아직 점유 중인 남은 행 수
        occupied: dict[int, int] = {}
        for tr in self._iter_rows(table):
            cells: list[str] = []
            col = 0

            def skip_occupied() -> None:
                nonlocal col
                while occupied.get(col, 0) > 0:
                    occupied[col] -= 1
                    cells.append("")
                    col += 1

            for cell in tr:
                ctag = self._tag(cell)
                if ctag not in CELL_TAGS:
                    continue
                skip_occupied()
                text = _norm_inline(self._text_of(cell)).replace("|", "\\|")
                colspan = self._span(cell, "COLSPAN")
                rowspan = self._span(cell, "ROWSPAN")
                cells.append(text)
                cells.extend([""] * (colspan - 1))
                if rowspan > 1:
                    for c in range(col, col + colspan):
                        occupied[c] = rowspan - 1
                col += colspan
            skip_occupied()  # 행 끝에 남은 점유 칸 소진
            if any(cells):
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


# --------------------------------------------------------------------------- 파싱
def parse_root(raw: bytes | str) -> etree._Element | None:
    """DART XML을 lxml recover 모드로 파싱해 루트 요소를 반환한다."""
    if isinstance(raw, bytes):
        text, _enc = decode_dart_xml(raw)
    else:
        text = raw

    # lxml은 encoding 선언이 있는 str을 거부하므로 선언 제거 후 utf-8 bytes로 파싱
    text = _XML_DECL_ANY_RE.sub("", text, count=1)
    text = _ENTITY_RE.sub(lambda m: _ENTITY_MAP[m.group(0)], text)

    parser = etree.XMLParser(recover=True, huge_tree=True, encoding="utf-8", resolve_entities=False)
    return etree.fromstring(text.encode("utf-8"), parser=parser)


def parse_dart_xml(raw: bytes | str, *, seen_tags: set[str] | None = None) -> str:
    """DART 원문 XML(bytes) → Markdown 풍 텍스트(UTF-8 str).

    seen_tags 집합을 넘기면 파싱 중 만난 태그 이름(대문자)을 수집해 준다.
    """
    root = parse_root(raw)
    if root is None:
        return ""
    renderer = _Renderer(seen_tags)
    return _finalize(renderer.render(root))


# --------------------------------------------------------------------------- 섹션 구조화
@dataclass
class Section:
    id: str          # "1", "1.2", "1.2.3" 같은 계층 번호. "0"은 섹션 밖 본문(표지 등). TITLE 기반 소제목은 "4.3.t12"
    level: int       # SECTION-1 → 1, SECTION-2 → 2, ... ("0" 섹션은 0). 소제목은 부모 level + 1
    title: str
    char_count: int
    text: str        # 하위 섹션을 포함한 전체 Markdown
    kind: str = "section"  # "section" (SECTION 태그) | "title" (섹션 안 TITLE 소제목 구간)

    def to_outline_dict(self) -> dict:
        """text를 뺀 목차용 dict."""
        d = asdict(self)
        d.pop("text")
        return d


_HEADING_RE = re.compile(r"^## (.+)$", re.M)


def split_by_titles(own_text: str, section_title: str) -> list[tuple[str, str]]:
    """섹션 자체 텍스트(하위 SECTION 제외)를 '## ' 소제목 단위로 나눈다 → [(소제목, 구간 텍스트)].

    섹션 제목과 같은 첫 소제목이 본문 없이 홀로 있으면 버린다. 소제목이 2개 미만이면 빈 리스트.
    """
    heads = list(_HEADING_RE.finditer(own_text))
    if len(heads) < 2:
        return []
    parts: list[tuple[str, str]] = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(own_text)
        title = m.group(1).strip()
        body = own_text[m.end():end].strip()
        if i == 0 and title == section_title and not body:
            continue
        parts.append((title, _finalize(own_text[m.start():end])))
    return parts if len(parts) >= 2 else []


def _section_title(el: etree._Element) -> str:
    """SECTION 태그의 제목: ATITLE/TITLE 속성 → 첫 TITLE 자손 → 빈 문자열."""
    for attr in ("ATITLE", "TITLE", "ATOC"):
        v = el.get(attr)
        if v and v.strip() and v.strip().upper() not in {"Y", "N"}:
            return _norm_inline(v)
    for child in el.iter():
        if _tag_name(child) == "TITLE":
            return _norm_inline("".join(child.itertext()))
    return ""


def build_outline(raw: bytes | str, *, root_title: str = "(표지 및 섹션 외 본문)") -> list[Section]:
    """DART XML → 섹션 목록(문서 순서). 상위 섹션 text는 하위 섹션 내용을 포함한다."""
    root = parse_root(raw)
    if root is None:
        return []

    sections: list[Section] = []

    # "0" 섹션: SECTION-* 바깥의 모든 본문
    outside = _finalize(_Renderer(skip_sections=True).render(root))
    sections.append(Section("0", 0, root_title, len(outside), outside))

    counters: dict[int, int] = {}
    for el in root.iter():
        level = _section_level(el)
        if level is None:
            continue
        counters[level] = counters.get(level, 0) + 1
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]
        sec_id = ".".join(str(counters.get(lv, 0)) for lv in range(1, level + 1))
        title = _section_title(el)
        text = _finalize(_Renderer().render(el))
        sections.append(Section(sec_id, level, title, len(text), text))

        # 섹션 자체 본문(하위 SECTION 제외)에 TITLE 소제목이 2개 이상이면 "<id>.tN" 하위 항목 추가
        own_text = _finalize(_Renderer(skip_sections=True).render(el))
        for n, (sub_title, sub_text) in enumerate(split_by_titles(own_text, title), start=1):
            sections.append(Section(f"{sec_id}.t{n}", level + 1, sub_title, len(sub_text), sub_text, kind="title"))

    return sections
