"""섹션 Markdown 텍스트에서 표 블록을 찾아 캡션·단위와 함께 돌려준다 (find_tables 툴의 순수 함수).

DART 원문은 표 제목·단위를 따로 한 칸짜리 표로 둔다(실측: 우성 합병 2026-10, 제논 증권신고서 2026-10):

    | |
    |---|
    | [외부평가기관인 한영 회계법인의 합병 비율 적정성 평가 요약] |

    | |
    |---|
    | (단위: 원) |

    | 구 분 | (주)우성 | ...

그래서 한 칸짜리 짧은 표는 다음 표의 캡션(대괄호) 또는 단위("(단위")로 붙이고, 그 자체는 결과에 넣지 않는다.
캡션 표가 없으면 표 바로 앞의 일반 텍스트 줄을 캡션으로 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TABLE_CHARS = 8000
_CAPTION_MAX = 200
_BRACKET_RE = re.compile(r"^\[.+\]$")
_UNIT_RE = re.compile(r"^\(?\s*단위\s*[:：]")


@dataclass
class _Block:
    start: int        # 섹션 텍스트 안 시작 offset
    end: int
    lines: list[str]  # 표 줄들(구분선 포함)


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|)+", line.strip()))


def _blocks(text: str) -> list[_Block | tuple[int, str]]:
    """텍스트 → 표 블록과 일반 줄((offset, line))의 순서 목록. 빈 줄은 뺀다."""
    out: list[_Block | tuple[int, str]] = []
    pos = 0
    cur: _Block | None = None
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if line.lstrip().startswith("|"):
            if cur is None:
                cur = _Block(start, start + len(line), [])
                out.append(cur)
            cur.lines.append(line)
            cur.end = start + len(line)
            continue
        cur = None
        if line.strip():
            out.append((start, line.strip()))
    return out


def _data_rows(block: _Block) -> list[list[str]]:
    """구분선과 빈 머리글 행을 뺀 행들."""
    rows = []
    for ln in block.lines:
        if _is_separator(ln):
            continue
        cells = _cells(ln)
        if any(cells):
            rows.append(cells)
    return rows


def _single_cell_text(block: _Block) -> str | None:
    """한 칸짜리 표(실질 값 1개)면 그 텍스트, 아니면 None."""
    rows = _data_rows(block)
    vals = [c for r in rows for c in r if c]
    if len(rows) <= 2 and len(vals) == 1 and all(len([c for c in r if c]) <= 1 for r in rows):
        return vals[0]
    return None


def find_tables(text: str, caption_pattern: str | None = None, *, max_tables: int = 10, offset: int = 0,
                max_table_chars: int = MAX_TABLE_CHARS) -> dict:
    """text(섹션 Markdown)에서 표를 찾는다.

    caption_pattern: 정규식(대소문자 무시). 캡션 또는 표의 첫 두 행에 맞는 표만. None이면 전부.
    offset: 이 위치 이후에서 시작하는 표만(긴 섹션을 이어 찾을 때 next_offset을 넣는다).
    반환: {total_matched, returned, has_more, next_offset, tables[{caption, caption_source, unit, offset,
    rows, cols, chars, truncated, text}]}. rows는 구분선을 뺀 행 수(머리글 포함), offset은 섹션 텍스트 기준.
    """
    pat = re.compile(caption_pattern, re.IGNORECASE) if caption_pattern else None
    items = _blocks(text)
    tables: list[dict] = []
    caption: tuple[str, str] | None = None  # (text, source)
    unit: str | None = None
    last_line: str | None = None
    for it in items:
        if isinstance(it, tuple):
            last_line = it[1]
            caption, unit = None, None
            continue
        single = _single_cell_text(it)
        if single is not None:
            if _UNIT_RE.match(single):
                unit = single
            elif _BRACKET_RE.match(single) or caption is None:
                caption = (single, "bracket" if _BRACKET_RE.match(single) else "cell")
            last_line = None
            continue
        cap = caption or ((last_line, "line") if last_line else None)
        if cap and len(cap[0]) > _CAPTION_MAX:
            cap = (cap[0][:_CAPTION_MAX] + "…", cap[1])
        rows = _data_rows(it)
        body = "\n".join(it.lines)
        head_text = " ".join(c for r in rows[:2] for c in r)
        caption, unit_now, last_line = None, unit, None
        unit = None
        if it.start < offset:
            continue
        if pat and not (cap and pat.search(cap[0])) and not pat.search(head_text) and not (unit_now and pat.search(unit_now)):
            continue
        truncated = len(body) > max_table_chars
        tables.append({
            "caption": cap[0] if cap else None,
            "caption_source": cap[1] if cap else None,
            "unit": unit_now,
            "offset": it.start,
            "rows": len(rows),
            "cols": max((len(r) for r in rows), default=0),
            "chars": len(body),
            "truncated": truncated,
            "text": body[:max_table_chars],
        })
    shown = tables[:max_tables]
    more = len(tables) > max_tables
    return {
        "total_matched": len(tables),
        "returned": len(shown),
        "has_more": more,
        "next_offset": tables[max_tables]["offset"] if more else None,
        "tables": shown,
    }
