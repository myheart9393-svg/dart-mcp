"""보고서 Markdown 표현 오류 정규식 점검 (/dart-review의 d 항목 보조).

실행: uv run python -m dart_mcp.report_lint reports/<보고서>.md   → JSON(findings[])을 stdout으로.
읽기로 확인해야 하는 것(문맥상 증감 방향 등)은 후보만 찍는다. 최종 판정은 리뷰어가 한다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 범위 표기 "4~5배": 같은 단락에 ~가 두 개 이상이면 GFM이 ~...~를 취소선으로 렌더해 "45배"처럼 보인다.
_TILDE = re.compile(r"(?<!\\)~")
_INLINE_CODE = re.compile(r"`[^`]*`")  # 코드 스팬 안의 ~는 취소선이 되지 않는다
_CURRENCY_MIX = re.compile(
    r"(USD|US\$|\$|달러|EUR|유로|JPY|엔화|CNY|위안)\s*[\d,.]+\s*(천|만|백만|억|조)\s*원"
)
_DIRECTION = re.compile(
    r"(△|▲|-|\+)\s*[\d,.]+\s*(%|%p|원|백만원|억원|조원)?\s*(증가|감소|개선|악화|상승|하락)"
)
_CITATION = re.compile(r"\(\s*\d{14}\s*,[^)]*\)")
_NUMBER = re.compile(r"\d[\d,.]*\s*(%|%p|원|백만원|억원|조원|배|주|명|건|개)")


def _paragraphs(lines: list[str]):
    """(시작 줄번호, [줄...]) 단위. 빈 줄·표·코드블록 경계로 끊는다."""
    buf: list[tuple[int, str]] = []
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            if buf:
                yield buf
                buf = []
            continue
        if in_code:
            continue
        if not line.strip() or line.lstrip().startswith(("#", "|", "- ", "* ")):
            if buf:
                yield buf
                buf = []
            if line.lstrip().startswith(("|", "- ", "* ")):
                yield [(i, line)]  # 표 행·목록 항목은 각각 한 단락
            continue
        buf.append((i, line))
    if buf:
        yield buf


def lint(text: str) -> list[dict]:
    lines = text.splitlines()
    out: list[dict] = []
    section = ""
    sec_of_line: dict[int, str] = {}
    for i, line in enumerate(lines, 1):
        if line.startswith("#"):
            section = line.lstrip("#").strip()
        sec_of_line[i] = section

    for para in _paragraphs(lines):
        joined = " ".join(l for _, l in para)
        tildes = [(n, l) for n, l in para if _TILDE.search(_INLINE_CODE.sub("", l))]
        if len(_TILDE.findall(_INLINE_CODE.sub("", joined))) >= 2:
            n = tildes[0][0]
            out.append({"check": "range_tilde", "line": n, "section": sec_of_line[n],
                        "text": joined.strip()[:200],
                        "why": "같은 단락에 '~'가 2개 이상 → Markdown 취소선으로 렌더되어 범위가 깨져 보임 (예: 4~5배 → 45배)",
                        "fix": "범위는 '4–5배'(en dash) 또는 '4\\~5배'로 쓴다"})
    for i, line in enumerate(lines, 1):
        for m in _CURRENCY_MIX.finditer(line):
            out.append({"check": "currency_unit_mix", "line": i, "section": sec_of_line[i], "text": m.group(0),
                        "why": "외화 통화명과 원화 금액 단위가 섞임", "fix": "원문 표 단위대로 쓰고 통화는 '어느 통화의 변동'으로만 표현"})
        for m in _DIRECTION.finditer(line):
            sign, word = m.group(1), m.group(3)
            neg = sign in ("△", "-")
            if (neg and word in ("증가", "개선", "상승")) or (not neg and sign in ("+", "▲") and word in ("감소", "악화", "하락")):
                out.append({"check": "direction_conflict", "line": i, "section": sec_of_line[i], "text": m.group(0),
                            "why": f"부호 '{sign}'와 '{word}'가 반대 방향", "fix": "부호와 증감 단어 중 하나를 원문에 맞게 고친다"})
        if (_NUMBER.search(line) and not _CITATION.search(line) and not line.lstrip().startswith(("|", "#", ">"))
                and "계산" not in line):
            out.append({"check": "number_without_citation_candidate", "line": i, "section": sec_of_line[i],
                        "text": line.strip()[:160],
                        "why": "숫자가 있는 줄에 (rcept_no, …) 출처가 없음 — 단락 끝 출처로 덮이는지 읽어서 판정",
                        "fix": "문장 또는 단락 끝에 (rcept_no, section_id|재무API) 추가"})
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m dart_mcp.report_lint <report.md>", file=sys.stderr)
        return 2
    findings = lint(Path(args[0]).read_text(encoding="utf-8"))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"file": args[0], "count": len(findings), "findings": findings}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
