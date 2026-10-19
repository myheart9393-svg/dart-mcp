"""DART MCP 서버 (stdio).

실행: python -m dart_mcp.server
주의: stdout은 MCP 프로토콜 전용. 로그는 전부 stderr(logging)로만.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any, Callable

from dotenv import load_dotenv
try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .cache import DisclosureCache
from .client import DartClient

load_dotenv()
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("dart_mcp.server")
# httpx는 INFO에서 요청 URL(crtfc_key 포함)을 찍으므로 경고 이상만 남긴다
logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = FastMCP("dart")
_cache = DisclosureCache()
_client: DartClient | None = None


def _get_client() -> DartClient:
    global _client
    if _client is None:
        _client = DartClient()  # DART_API_KEY 없으면 여기서 ValueError → 툴이 error로 돌려줌
    return _client


def _safe(fn: Callable[..., Any]) -> Callable[..., Any]:
    """툴 예외를 {"error": ...}로 바꿔 서버가 죽지 않게 한다."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("tool %s failed", fn.__name__)
            return {"error": f"{type(exc).__name__}: {exc}"}

    return wrapper


def _load(rcept_no: str):
    rcept_no = rcept_no.strip()
    if not re.fullmatch(r"\d{14}", rcept_no):
        raise ValueError(f"rcept_no는 14자리 숫자여야 합니다: {rcept_no!r}")
    client = None if _cache.has(rcept_no) else _get_client()
    return _cache.get(rcept_no, client)


# --------------------------------------------------------------------------- tools
@mcp.tool()
@_safe
def find_company(name: str, limit: int = 10) -> dict:
    """회사명(부분일치)으로 DART 고유번호 corp_code를 찾는다.

    언제: 사용자가 회사 이름만 알고 있을 때 가장 먼저 호출한다. 다른 모든 조회는 corp_code가 필요하다.
    결과: 상장사(stock_code 있음)를 먼저, 정확히 일치하는 이름을 그다음으로 정렬한 목록.
    다음: 원하는 회사의 corp_code를 골라 search_disclosures(corp_code, ...)를 호출한다.
    참고: 동명이인 회사가 많으므로(예: "삼성" 검색 시 수십 건) stock_code 유무와 corp_name을 보고 고를 것.
    """
    hits = _get_client().find_company(name, limit=limit)
    return {
        "query": name,
        "count": len(hits),
        "results": [
            {"corp_code": h["corp_code"], "corp_name": h["corp_name"], "stock_code": h["stock_code"] or None}
            for h in hits
        ],
    }


@mcp.tool()
@_safe
def search_disclosures(
    corp_code: str,
    bgn_de: str,
    end_de: str,
    pblntf_ty: str | None = None,
    max_results: int = 50,
) -> dict:
    """특정 회사의 공시 목록을 기간으로 검색한다 (OpenDART list.json).

    언제: find_company로 corp_code를 얻은 뒤, 읽고 싶은 공시의 접수번호(rcept_no)를 찾을 때.
    인자:
      - bgn_de, end_de: "YYYYMMDD". 사업보고서는 보통 결산 다음 해 3월에 제출된다
        (예: 2024 회계연도 사업보고서는 2025-03에 접수 → bgn_de="20250101", end_de="20251231", pblntf_ty="A").
      - pblntf_ty (공시유형, 생략하면 전체):
          A=정기공시(사업·반기·분기보고서), B=주요사항보고, C=발행공시, D=지분공시, E=기타공시,
          F=외부감사관련, G=펀드공시, H=자산유동화, I=거래소공시, J=공정위공시
    결과: 각 항목에 rcept_no(접수번호), report_nm(보고서명), rcept_dt(접수일), flr_nm(제출인).
      report_nm에 "[기재정정]"이 붙으면 정정본이다. 최신순으로 정렬되어 있다.
    다음: 원하는 항목의 rcept_no로 get_disclosure_outline(rcept_no)를 호출해 목차부터 본다.
      원문 전체를 한 번에 받는 툴은 없다. 항상 목차 → 섹션 순으로 읽는다.
    """
    client = _get_client()
    items: list[dict] = []
    page = 1
    total = None
    while len(items) < max_results:
        page_count = min(100, max_results - len(items))
        data = client.search_disclosures(
            corp_code=corp_code, bgn_de=bgn_de, end_de=end_de, pblntf_ty=pblntf_ty,
            page_no=page, page_count=page_count,
        )
        total = int(data.get("total_count", 0))
        batch = data.get("list", [])
        for it in batch:
            items.append(
                {
                    "rcept_no": it.get("rcept_no"),
                    "report_nm": it.get("report_nm"),
                    "rcept_dt": it.get("rcept_dt"),
                    "flr_nm": it.get("flr_nm"),
                    "corp_name": it.get("corp_name"),
                }
            )
        if not batch or page >= int(data.get("total_page", 1)):
            break
        page += 1
    return {"corp_code": corp_code, "total_count": total, "returned": len(items), "results": items}


@mcp.tool()
@_safe
def get_disclosure_outline(rcept_no: str, file_id: str | None = None) -> dict:
    """공시 원문의 파일 목록과 섹션 목차를 돌려준다. 본문을 읽기 전에 반드시 먼저 호출한다.

    언제: search_disclosures에서 rcept_no를 얻은 직후. 사업보고서는 변환 시 수십만 자가 넘으므로
      전체를 받을 수 없고, 이 목차에서 필요한 섹션만 골라 읽어야 한다.
    결과:
      - files[]: 공시 ZIP 안의 파일들. file_id="main"이 본문, 그 외("00760" 등)는 첨부
        (감사보고서, 정정 문서 등). 각 파일에 total_chars와 sections[].
      - sections[]: {id, level, title, char_count}. id는 "1", "1.2", "1.2.3" 같은 계층 번호.
        level 1이 대분류(예: "I. 회사의 개요", "II. 사업의 내용"), level 2·3이 소분류.
        상위 섹션의 char_count는 하위 섹션을 모두 포함한 크기다. id "0"은 표지 등 섹션 밖 본문.
    인자: file_id를 주면 그 파일의 목차만 돌려준다 (생략 시 전체 파일).
    다음: 읽을 섹션을 고른 뒤 get_disclosure_section(rcept_no, section_id, file_id)를 호출한다.
      char_count가 큰 섹션은 하위(level 2~3) id로 쪼개 읽거나 max_chars/offset으로 나눠 읽는다.
      특정 키워드 위치만 알고 싶으면 search_in_disclosure를 쓴다.
    """
    disc = _load(rcept_no)
    files = disc.files
    if file_id is not None:
        f = disc.get_file(file_id)
        if f is None:
            return {
                "error": f"file_id {file_id!r} 없음. 사용 가능: {[x.file_id for x in disc.files]}"
            }
        files = [f]
    return {
        "rcept_no": disc.rcept_no,
        "total_chars": sum(f.total_chars for f in files),
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "total_chars": f.total_chars,
                "section_count": len(f.sections),
                "sections": f.outline(),
            }
            for f in files
        ],
    }


@mcp.tool()
@_safe
def get_disclosure_section(
    rcept_no: str,
    section_id: str,
    file_id: str = "main",
    max_chars: int = 30000,
    offset: int = 0,
) -> dict:
    """공시 원문의 한 섹션을 Markdown 텍스트로 돌려준다 (표는 Markdown 표).

    언제: get_disclosure_outline에서 읽을 섹션 id를 고른 뒤.
    인자:
      - section_id: 목차의 id ("2", "2.1", "0" 등). 상위 id를 주면 하위 섹션 전체가 포함된다.
      - file_id: "main"(본문) 또는 첨부 id("00760" 등). 목차의 files[].file_id 참고.
      - max_chars / offset: 긴 섹션은 잘라서 받는다. 응답의 has_more가 true면
        next_offset을 offset으로 넣어 같은 호출을 반복한다.
    결과: {section_id, title, level, char_count, offset, returned_chars, has_more, next_offset, text}
    팁: 숫자 표가 필요하면 해당 소분류 섹션(level 2~3)을 직접 지정하는 편이 토큰을 아낀다.
    """
    disc = _load(rcept_no)
    f = disc.get_file(file_id)
    if f is None:
        return {"error": f"file_id {file_id!r} 없음. 사용 가능: {[x.file_id for x in disc.files]}"}
    sec = f.get_section(section_id)
    if sec is None:
        return {
            "error": f"section_id {section_id!r} 없음 (file_id={file_id}). get_disclosure_outline로 id를 확인하세요.",
            "available_ids": [s.id for s in f.sections][:200],
        }
    offset = max(0, offset)
    max_chars = max(1, max_chars)
    chunk = sec.text[offset : offset + max_chars]
    end = offset + len(chunk)
    return {
        "rcept_no": rcept_no,
        "file_id": file_id,
        "section_id": sec.id,
        "title": sec.title,
        "level": sec.level,
        "char_count": sec.char_count,
        "offset": offset,
        "returned_chars": len(chunk),
        "has_more": end < sec.char_count,
        "next_offset": end if end < sec.char_count else None,
        "text": chunk,
    }


@mcp.tool()
@_safe
def search_in_disclosure(
    rcept_no: str,
    query: str,
    file_id: str = "main",
    context_chars: int = 300,
    max_results: int = 20,
) -> dict:
    """공시 원문 안에서 키워드를 찾아 위치(섹션 id)와 앞뒤 문맥을 돌려준다.

    언제: 긴 문서(사업보고서 등)에서 "소송", "영업권", "우발부채" 같은 특정 내용이 어느 섹션에
      있는지 바로 알고 싶을 때. 목차 제목만으로는 위치를 알기 어려운 주석 항목 찾기에 유용하다.
    인자: query는 대소문자 무시 부분일치. file_id로 첨부(감사보고서 등)도 검색할 수 있다.
    결과: matches[] 각각 {section_id, section_title, level, offset, occurrences, context}. 가장 깊은(구체적인)
      섹션 기준으로 한 번만 보고하고, 서로 가까운 매치는 한 항목으로 묶는다(occurrences=묶인 수).
      total_matches는 전체 매치 수, total_clusters는 묶인 항목 수.
    다음: 매치된 section_id로 get_disclosure_section을 호출해 그 부분을 자세히 읽는다.
      offset 값을 get_disclosure_section의 offset으로 넘기면 매치 지점 근처부터 읽을 수 있다.
    """
    if not query.strip():
        return {"error": "query가 비어 있습니다"}
    disc = _load(rcept_no)
    f = disc.get_file(file_id)
    if f is None:
        return {"error": f"file_id {file_id!r} 없음. 사용 가능: {[x.file_id for x in disc.files]}"}

    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE)
    seen: set[str] = set()
    matches: list[tuple[tuple[int, ...], int, dict]] = []
    # 깊은 섹션부터 검색해, 상위 섹션에서 중복되는 매치는 문맥 키로 걸러낸다
    for sec in sorted(f.sections, key=lambda s: -s.level):
        spans: list[tuple[int, int]] = []
        for m in pattern.finditer(sec.text):
            # 뒤쪽 문맥만으로 키를 만든다: 하위 섹션 첫머리의 매치는 앞 문맥이 짧아 상위와 키가 달라지기 때문
            key = sec.text[m.start() : m.end() + 80]
            if key in seen:
                continue
            seen.add(key)
            spans.append((m.start(), m.end()))
        # 서로 context_chars 안에 있는 매치는 한 덩어리로 합친다
        clusters: list[list[tuple[int, int]]] = []
        for sp in spans:
            if clusters and sp[0] - clusters[-1][-1][1] <= context_chars:
                clusters[-1].append(sp)
            else:
                clusters.append([sp])
        sort_key = tuple(int(p) for p in sec.id.split("."))
        for cl in clusters:
            s0 = max(0, cl[0][0] - context_chars)
            s1 = min(len(sec.text), cl[-1][1] + context_chars)
            matches.append(
                (
                    sort_key,
                    cl[0][0],
                    {
                        "section_id": sec.id,
                        "section_title": sec.title,
                        "level": sec.level,
                        "offset": cl[0][0],
                        "occurrences": len(cl),
                        "context": sec.text[s0:s1].replace("\n", " "),
                    },
                )
            )
    matches.sort(key=lambda t: (t[0], t[1]))
    return {
        "rcept_no": rcept_no,
        "file_id": file_id,
        "query": query,
        "total_matches": sum(m[2]["occurrences"] for m in matches),
        "total_clusters": len(matches),
        "returned": min(len(matches), max_results),
        "matches": [m[2] for m in matches[:max_results]],
    }


def main() -> None:
    log.info("starting dart MCP server (stdio); data_dir=%s", _cache.data_dir)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
