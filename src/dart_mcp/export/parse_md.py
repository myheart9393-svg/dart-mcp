"""보고서 md → blocks.json.

블록 종류: h / quote / table / ul / p / label / verdict / note / source.
인라인 run: {t, b?, code?, k?} — k는 cite(출처)·est(추정:)·fn(각주 참조).
세 빌더(docx.js, html.py, pptx.js)는 이 결과만 읽는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CITE = re.compile(r"(\((?:[^()\d]{0,20} )?\d{14}[^()]*\))")
EST = re.compile(r"(추정:)")
INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[\^[^\]\s]+\](?!:))")
LINK = re.compile(r"!?\[([^\]^][^\]]*)\]\([^)\s]*\)")
BR = re.compile(r"<br\s*/?>", re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
HEADING = re.compile(r"^(#{1,6}) +(.*?)\s*$")
LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|(\d+)\.) +(.*)$")
FOOTNOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]:\s*(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
GROUP_HEADER = re.compile(r"(.+?) (FY\d{4})(?:·(연결|별도))?")
YEAR = re.compile(r"(?:^|[^0-9])((?:19|20)\d{2})(?:[^0-9]|$)")
NUMBER_CELL = re.compile(r"([+−-]?)([0-9]+(?:,[0-9]{3})*(?:\.([0-9]+))?)[¹²³⁴⁵⁶⁷⁸⁹]*\s*%?")
AMOUNT_ROW = re.compile(r"^(매출액?|영업수익|순영업수익|순이자이익|보험손익)")
RATIO_ROW = re.compile(r"^(영업이익률|ROE)")
GROWTH_ROW = re.compile(r"증감|증가|성장")
UNIT = re.compile(r"(백만원|십억원|억원|천원|원)")
CLOSING = "이 보고서는 투자 권유가 아니다."
DATE_IN_COVER = re.compile(r"작성일\s*([0-9]{4}[-.][0-9]{1,2}[-.][0-9]{1,2})")


def strip_nonrendered(text: str) -> str:
    """화면에 나오지 않는 부분(줄바꿈 통일, 프런트매터, HTML 주석)을 뺀다. 숫자 검증도 같은 기준을 쓴다."""
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    text = FRONTMATTER.sub("", text)
    return COMMENT.sub("", text)


def _unescape(text: str) -> str:
    return re.sub(r"\\([|*`_\[\]\\])", r"\1", text)


def inline(text: str) -> list[dict]:
    text = LINK.sub(r"\1", BR.sub(" ", text))
    runs: list[dict] = []
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            runs.append({"t": _unescape(part[2:-2]), "b": True})
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            runs.append({"t": part[1:-1], "code": True})
        elif part.startswith("[^") and part.endswith("]"):
            runs.append({"t": f"[{part[2:-1]}]", "k": "fn"})
        else:
            runs.append({"t": _unescape(part)})
    out: list[dict] = []
    for run in runs:
        if run.get("code") or run.get("k"):
            out.append(run)
            continue
        for seg in CITE.split(run["t"]):
            if not seg:
                continue
            if CITE.fullmatch(seg):
                out.append({**run, "t": seg, "k": "cite"})
                continue
            for sub in EST.split(seg):
                if not sub:
                    continue
                out.append({**run, "t": sub, "k": "est"} if sub == "추정:" else {**run, "t": sub})
    return out


def plain(runs: list[dict]) -> str:
    return "".join(r["t"] for r in runs)


def _cells(line: str) -> list[str]:
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") and not line.endswith(r"\|") else line
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _fit_row(row: list[str], n: int) -> list[str]:
    """머리글 칸 수에 맞춘다. 남는 칸은 마지막 칸에 합쳐 내용을 잃지 않는다."""
    if len(row) > n:
        return row[: n - 1] + [" ".join(row[n - 1 :])]
    return row + [""] * (n - len(row))


def _classify(line: str) -> str:
    if re.fullmatch(r"\*\*[^*]+\*\*", line):
        return "label"
    if re.match(r"\*\*(종합 )?판단", line):
        return "verdict"
    if re.match(r"[¹²³⁴⁵⁶⁷⁸⁹※]|주\)|주:|금액은 원 단위", line):
        return "note"
    if line.startswith("출처:") or re.match(r"\(\d{14}", line):
        return "source"
    return "p"


def _is_numeric(cell: str) -> bool:
    return bool(NUMBER_CELL.fullmatch(cell.replace("**", "").strip()))


def _table(rows: list[str], has_sep: bool) -> dict:
    header = _cells(rows[0])
    n = len(header)
    sep = _fit_row(_cells(rows[1]), n) if has_sep else [""] * n
    body = [_fit_row(_cells(r), n) for r in rows[(2 if has_sep else 1) :]]
    align = []
    for i, s in enumerate(sep):
        filled = [r[i] for r in body if r[i].strip() and r[i].strip() not in ("–", "-", "—")]
        numeric = sum(_is_numeric(c) for c in filled)
        is_right = s.endswith(":") and not s.startswith(":")
        align.append("r" if is_right or (i > 0 and filled and numeric / len(filled) >= 0.7) else "l")
    block = {
        "type": "table",
        "header": [inline(c) for c in header],
        "header_text": [plain(inline(c)) for c in header],
        "align": align,
        "rows": [[inline(c) for c in r] for r in body],
    }
    pats = [GROUP_HEADER.fullmatch(h) for h in block["header_text"][1:]]
    if pats and all(pats):
        groups: list[dict] = []
        for p in pats:
            label = f"{p.group(1)} ({p.group(3)})" if p.group(3) else p.group(1)
            if groups and groups[-1]["label"] == label:
                groups[-1]["span"] += 1
            else:
                groups.append({"label": label, "span": 1})
        block["groups"] = groups
        block["subheader"] = [p.group(2) for p in pats]
    return block


def _parse_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip() or HR.match(ln):
            i += 1
            continue
        m = HEADING.match(ln)
        if m:
            runs = inline(m.group(2))
            blocks.append({"type": "h", "lvl": len(m.group(1)), "runs": runs, "text": plain(runs)})
            i += 1
            continue
        if ln.startswith(">"):
            paras = []
            while i < len(lines) and lines[i].startswith(">"):
                t = lines[i][1:].strip()
                if t:
                    paras.append(inline(t))
                i += 1
            blocks.append({"type": "quote", "paras": paras})
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(_table(rows, len(rows) > 1 and bool(TABLE_SEP.fullmatch(rows[1]))))
            continue
        if LIST_ITEM.match(ln):
            items = []
            while i < len(lines) and (m := LIST_ITEM.match(lines[i])):
                item = {"runs": inline(m.group(3)), "lvl": len(m.group(1)) // 2}
                if m.group(2):
                    item["marker"] = f"{m.group(2)}."
                items.append(item)
                i += 1
            blocks.append({"type": "ul", "items": items})
            continue
        t = ln.strip()
        m = FOOTNOTE_DEF.match(t)
        if m:
            blocks.append({"type": "note", "runs": [{"t": f"[{m.group(1)}] ", "k": "fn"}, *inline(m.group(2))]})
        else:
            blocks.append({"type": _classify(t), "runs": inline(t)})
        i += 1
    return blocks


def _caption(blocks: list[dict], idx: int) -> str | None:
    """표 바로 앞의 라벨·제목. 사이에 단순 문단만 있으면 건너뛴다."""
    j = idx - 1
    while j >= 0 and blocks[j]["type"] == "p":
        j -= 1
    if j < 0 or blocks[j]["type"] not in ("h", "label"):
        return None
    text = plain(blocks[j]["runs"])
    return re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", text).strip() or None


def _chart_values(row: list[list[dict]]) -> tuple[list[float], list[str], int] | None:
    values, labels, decimals = [], [], 0
    for cell in row:
        text = plain(cell).strip()
        m = NUMBER_CELL.fullmatch(text)
        if not m:
            return None
        number = m.group(2).replace(",", "")
        values.append(float(("-" if m.group(1) in ("−", "-") else "") + number))
        labels.append(text)
        decimals = max(decimals, len(m.group(3) or ""))
    return values, labels, decimals


def _charts(block: dict) -> list[dict]:
    """3개년 이상 지표 표의 매출·이익률 행 → 막대 차트 스펙. 값은 표 칸 그대로다."""
    headers = block["header_text"][1:]
    years = [YEAR.search(h) for h in headers]
    if not headers or not all(years):
        return []
    years = [y.group(1) for y in years]
    n_years = len(set(years))
    if n_years < 3:
        return []
    groups = block.get("groups") or [{"label": None, "span": len(headers)}]
    if any(g["span"] != n_years for g in groups):
        return []
    charts = []
    caption = block.get("caption") or ""
    for pattern, is_ratio in ((AMOUNT_ROW, False), (RATIO_ROW, True)):
        row = next(
            (r for r in block["rows"]
             if pattern.search(plain(r[0]).strip()) and not GROWTH_ROW.search(plain(r[0]))),
            None,
        )
        parsed = _chart_values(row[1:]) if row else None
        if not parsed:
            continue
        values, labels, decimals = parsed
        label = plain(row[0]).strip()
        unit = "%" if is_ratio else None
        if not unit:
            unit_m = UNIT.search(block["header_text"][0]) or UNIT.search(caption)
            unit = unit_m.group(1) if unit_m else None
        series = []
        k = 0
        for g in groups:
            idx = sorted(range(k, k + g["span"]), key=lambda c: years[c])
            series.append({
                "name": g["label"] or label,
                "values": [values[c] for c in idx],
                "labels": [labels[c] for c in idx],
                "cats": [(block.get("subheader") or years)[c] for c in idx],
            })
            k += g["span"]
        charts.append({
            "title": label,
            "unit": unit,
            "categories": series[0]["cats"],
            "series": [{key: s[key] for key in ("name", "values", "labels")} for s in series],
            "decimals": decimals,
        })
    return charts


def parse(md: str, fallback_title: str = "보고서") -> dict:
    """md 원문 → {"meta": 표지 정보, "blocks": 본문 블록}."""
    blocks = _parse_blocks(strip_nonrendered(md).split("\n"))
    title_text = fallback_title
    for i, b in enumerate(blocks):
        if b["type"] == "h" and b["lvl"] == 1:
            title_text = b["text"]
            del blocks[i]
            break
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", title_text)
    title, subtitle = (m.group(1), m.group(2)) if m else (title_text, None)

    cover: list[list[dict]] = []
    for i, b in enumerate(blocks):
        if b["type"] == "h":
            break
        if b["type"] == "quote":
            cover = b["paras"]
            del blocks[i]
            break
    date = next((d.group(1) for p in cover if (d := DATE_IN_COVER.search(plain(p)))), None)

    has_closing = False
    for b in blocks:
        if b["type"] == "p" and plain(b["runs"]).startswith(CLOSING):
            b["closing"] = True
    has_closing = CLOSING in md

    n = 0
    for i, b in enumerate(blocks):
        if b["type"] == "table":
            n += 1
            b["n"] = n
            b["caption"] = _caption(blocks, i)
            if i and blocks[i - 1]["type"] == "label":
                blocks[i - 1]["is_caption"] = True  # docx·html은 캡션과 겹치는 라벨을 다시 쓰지 않는다.
            charts = _charts(b)
            if charts:
                b["charts"] = charts

    meta = {
        "title": title,
        "subtitle": subtitle,
        "date": date,
        "cover": cover,
        "closing": CLOSING if has_closing else None,
    }
    return {"meta": meta, "blocks": blocks}


def fallback_title(path: Path) -> str:
    """H1이 없을 때 쓰는 제목: 파일명에서 끝의 날짜를 뺀다(날짜는 md에 없는 숫자일 수 있다)."""
    return re.sub(r"[_-]?\d{4}-?\d{2}-?\d{2}$", "", path.stem).replace("_", " ") or path.stem


def parse_file(path: Path) -> dict:
    return parse(path.read_text(encoding="utf-8"), fallback_title(path))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    data = parse_file(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(sys.argv[2])
