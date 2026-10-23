"""DART MCP 서버 (stdio).

실행: python -m dart_mcp.server
주의: stdout은 MCP 프로토콜 전용. 로그는 전부 stderr(logging)로만.
"""

from __future__ import annotations

import datetime as dt
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
from .financials import (
    FINANCIAL_WARNING,
    FS_DIVS,
    KEY_ACCOUNTS,
    NO_DATA_STATUS,
    INTERIM_PERIOD_TYPES,
    OPTIONAL_ACCOUNTS,
    REPRT_CODES,
    STATEMENTS,
    detect_sector,
    group_statements,
    load_company,
    load_statements,
    period_years,
    summarize_interim_financials,
    summarize_key_financials,
)
from .periodic import classify_periodic_reports

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
# get_latest_reports가 본 정정 그룹의 rcept_no → 본문이 든 rcept_no(body_rcept_no). 본문 없는 첨부정정 ZIP 안내용
_body_hint: dict[str, str] = {}


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


def _missing_main(disc) -> dict:
    """본문(main) 없이 첨부만 든 ZIP(첨부정정·첨부추가 공시)을 main으로 읽으려 할 때의 에러."""
    body = _body_hint.get(disc.rcept_no)
    hint = (f"본문은 {body}에 있음: get_disclosure_outline({body!r})" if body and body != disc.rcept_no
            else "search_disclosures로 같은 기간의 원본(꼬리표 없음) 또는 [기재정정]본을 찾으세요")
    return {
        "error": f"{disc.rcept_no}의 ZIP에는 본문(main)이 없고 첨부만 있습니다(첨부정정·첨부추가 공시일 수 있음).",
        "available_file_ids": [x.file_id for x in disc.files],
        "hint": hint,
    }


def _sort_key(section_id: str) -> tuple[int, ...]:
    """'4.3.t12' → (4, 3, 12): 소제목(tN)도 문서 순서대로 정렬되게 한다."""
    return tuple(int(p[1:]) if p.startswith("t") else int(p) for p in section_id.split("."))


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
def get_disclosure_outline(rcept_no: str, file_id: str | None = None, depth: int = 2) -> dict:
    """공시 원문의 파일 목록과 섹션 목차를 돌려준다. 본문을 읽기 전에 반드시 먼저 호출한다.

    언제: search_disclosures에서 rcept_no를 얻은 직후. 사업보고서는 변환 시 수십만 자가 넘으므로
      전체를 받을 수 없고, 이 목차에서 필요한 섹션만 골라 읽어야 한다.
    결과:
      - files[]: 공시 ZIP 안의 파일들. file_id="main"이 본문, 그 외("00760" 등)는 첨부
        (감사보고서, 정정 문서 등). 각 파일에 total_chars와 sections[].
      - sections[]: {id, level, title, char_count}. id는 "1", "1.2", "1.2.3" 같은 계층 번호.
        level 1이 대분류(예: "I. 회사의 개요", "II. 사업의 내용"), level 2·3이 소분류.
        상위 섹션의 char_count는 하위 섹션을 모두 포함한 크기다. id "0"은 표지 등 섹션 밖 본문.
    인자:
      - file_id: 주면 그 파일의 목차만 돌려준다 (생략 시 전체 파일).
      - depth: 보여줄 최대 level (기본 2 = 대분류·소분류). depth=3이면 level 3 SECTION과
        TITLE 기반 소제목(id가 "4.3.t12"처럼 ".tN"으로 끝남, kind="title")까지 나온다.
        재무제표 주석처럼 섹션 하나가 10만 자를 넘을 때 depth=3으로 다시 호출해 주석 번호 단위로 읽는다.
        (목차 JSON이 커지므로 큰 섹션의 하위만 필요하면 file_id와 함께 쓰거나 search_in_disclosure를 쓴다.)
    parse_warnings: 비어 있지 않으면 파서가 원문 일부를 놓쳤을 수 있다(예: "SECTION-1 14개 중 4개만 파싱됨").
      그 공시의 목차·검색 결과는 뒷부분이 빠졌을 수 있으니 보고서에 그 사실을 적고, 빠진 장의 내용은 "원문 확인 불가"로 둔다.
    본문 없는 ZIP: 첨부정정·첨부추가 공시는 ZIP에 첨부(감사보고서)만 있다. 그 rcept_no로 본문을 요청하면 error와 hint가 온다.
      본문은 get_latest_reports의 body_rcept_no, 감사보고서는 attachment_rcept_no로 읽는다.
    다음: 읽을 섹션을 고른 뒤 get_disclosure_section(rcept_no, section_id, file_id)를 호출한다.
      section_id에는 ".tN" 소제목 id도 그대로 쓸 수 있다.
      char_count가 큰 섹션은 하위(level 2~3) id로 쪼개 읽거나 max_chars/offset으로 나눠 읽는다.
      특정 키워드 위치만 알고 싶으면 search_in_disclosure를 쓴다.
    """
    disc = _load(rcept_no)
    files = disc.files
    if file_id in (None, "main") and disc.get_file("main") is None:
        return _missing_main(disc)
    if file_id is not None:
        f = disc.get_file(file_id)
        if f is None:
            return {
                "error": f"file_id {file_id!r} 없음. 사용 가능: {[x.file_id for x in disc.files]}"
            }
        files = [f]
    depth = max(0, depth)
    warnings = [w if f.file_id == "main" else f"[{f.file_id}] {w}" for f in files for w in f.parse_warnings]
    return {
        "rcept_no": disc.rcept_no,
        "depth": depth,
        "total_chars": sum(f.total_chars for f in files),
        "parse_warnings": warnings,
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "total_chars": f.total_chars,
                "section_count": len(f.sections),
                "parse_warnings": f.parse_warnings,
                "shown": sum(1 for s in f.sections if s.level <= depth),
                "sections": [s.to_outline_dict() for s in f.sections if s.level <= depth],
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
      - section_id: 목차의 id ("2", "2.1", "0", 소제목 "4.3.t12" 등). 상위 id를 주면 하위 섹션 전체가 포함된다.
      - file_id: "main"(본문) 또는 첨부 id("00760" 등). 목차의 files[].file_id 참고.
      - max_chars / offset: 긴 섹션은 잘라서 받는다. 응답의 has_more가 true면
        next_offset을 offset으로 넣어 같은 호출을 반복한다.
    결과: {section_id, title, level, char_count, offset, returned_chars, has_more, next_offset, text}
    팁: 숫자 표가 필요하면 해당 소분류 섹션(level 2~3)을 직접 지정하는 편이 토큰을 아낀다.
    """
    disc = _load(rcept_no)
    f = disc.get_file(file_id)
    if f is None and file_id == "main":
        return _missing_main(disc)
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
    if f is None and file_id == "main":
        return _missing_main(disc)
    if f is None:
        return {"error": f"file_id {file_id!r} 없음. 사용 가능: {[x.file_id for x in disc.files]}"}

    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE)
    matches: list[tuple[tuple[int, ...], int, dict]] = []
    # 매치는 그것을 담은 가장 깊은 섹션에서만 보고한다. 상위 섹션 text는 하위 섹션 text를 그대로 포함하므로,
    # 하위 섹션 text가 상위 text 안에서 차지하는 구간에 든 매치는 건너뛴다.
    # (예전의 "매치 뒤 80자" 문맥 키는 하위 섹션 끝머리 매치를 상위에서 다시 보고했다: 리노공업 2025 '경쟁' 실측)
    for sec in f.sections:
        found = list(pattern.finditer(sec.text))
        if not found:
            continue
        covered: list[tuple[int, int]] = []
        if sec.id != "0":
            for sub in f.sections:
                if sub.id.startswith(sec.id + ".") and sub.text:
                    pos = sec.text.find(sub.text)
                    if pos >= 0:
                        covered.append((pos, pos + len(sub.text)))
        spans: list[tuple[int, int]] = []
        for m in found:
            if any(a <= m.start() < b for a, b in covered):
                continue
            spans.append((m.start(), m.end()))
        # 서로 context_chars 안에 있는 매치는 한 덩어리로 합친다
        clusters: list[list[tuple[int, int]]] = []
        for sp in spans:
            if clusters and sp[0] - clusters[-1][-1][1] <= context_chars:
                clusters[-1].append(sp)
            else:
                clusters.append([sp])
        sort_key = _sort_key(sec.id)
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


def _check_fin_args(corp_code: str, bsns_year: str, reprt_code: str | None, fs_div: str) -> tuple[str, str, str, str]:
    if reprt_code is None:
        # get_latest_reports가 결산기 변경 등으로 기간을 판별하지 못한 항목(reprt_code=null)을 그대로 넘긴 경우
        raise ValueError(
            "reprt_code가 null입니다. get_latest_reports가 보고 기간을 판별하지 못한 반기·분기보고서"
            "(결산기 변경 등)일 수 있으니 search_disclosures로 기간을 확인한 뒤 11011/11012/11013/11014 중 하나를 넘기세요"
        )
    corp_code, bsns_year = corp_code.strip(), str(bsns_year).strip()
    reprt_code, fs_div = str(reprt_code).strip(), fs_div.strip().upper()
    if not re.fullmatch(r"\d{8}", corp_code):
        raise ValueError(f"corp_code는 8자리 숫자여야 합니다(find_company로 확인): {corp_code!r}")
    if not re.fullmatch(r"\d{4}", bsns_year):
        raise ValueError(f"bsns_year는 4자리 연도여야 합니다: {bsns_year!r}")
    if reprt_code not in REPRT_CODES:
        raise ValueError(f"reprt_code는 {list(REPRT_CODES)} 중 하나: {reprt_code!r}")
    if fs_div not in FS_DIVS:
        raise ValueError(f"fs_div는 CFS(연결) 또는 OFS(별도): {fs_div!r}")
    return corp_code, bsns_year, reprt_code, fs_div


def _no_data_message(corp_code: str, bsns_year: str, reprt_code: str, fs_div: str) -> str:
    hint = " 연결 대상 종속회사가 없는 회사면 fs_div='OFS'로 다시 호출한다." if fs_div == "CFS" else ""
    return (
        f"조회 데이터 없음(status 013): {corp_code} {bsns_year} {REPRT_CODES[reprt_code]} {FS_DIVS[fs_div]}."
        f" 해당 보고서가 아직 제출 전이거나 2015년 이전 연도일 수 있다.{hint}"
    )


@mcp.tool()
@_safe
def get_financial_statements(
    corp_code: str,
    bsns_year: str,
    reprt_code: str | None = "11011",
    fs_div: str = "CFS",
    sj_div: str | None = None,
    refresh: bool = False,
) -> dict:
    """정기보고서의 재무제표 전체 계정을 구조화 데이터로 돌려준다 (OpenDART fnlttSinglAcntAll).

    언제: 재무 숫자가 필요할 때 원문 III장(요약재무정보·재무제표 본표) 대신 이것을 쓴다.
      원문 표를 옮겨 적는 것보다 정확하고(단위가 항상 원), 한 번에 당기·전기·전전기 3개년이 온다.
      핵심 지표만 필요하면 get_key_financials가 더 짧다.
    인자:
      - corp_code: find_company로 얻은 8자리. bsns_year: 사업연도 "YYYY" (2015년 이후).
      - reprt_code: 11011=사업보고서, 11012=반기보고서, 11013=1분기보고서, 11014=3분기보고서
      - fs_div: CFS=연결재무제표, OFS=재무제표(별도)
      - sj_div: 쉼표로 고를 재무제표. BS=재무상태표, IS=손익계산서, CIS=포괄손익계산서, CF=현금흐름표
        (생략 시 네 개 전부. 손익계산서를 포괄손익계산서 하나로 내는 회사는 IS 없이 CIS만 있다.)
    결과: statements{sj_div: {sj_nm, rows[]}}. 각 row는 account_nm, account_id, thstrm_amount(당기),
      frmtrm_amount(전기), bfefrmtrm_amount(전전기) 원문 문자열과 amount_krw{연도: 정수(원)}.
      years는 [당기, 전기, 전전기] 연도. 분기·반기 보고서는 전전기 열이 없을 수 있다.
      조회 데이터가 없으면(status 013) error가 아니라 빈 statements와 message.
    캐시: data/fin/<corp_code>_<연도>_<reprt_code>_<fs_div>.json. 90일 안에는 재호출해도 API를 쓰지 않고,
      90일이 지나면 다시 받는다. 재무제표 정정(정정공시)이 의심되면 refresh=True로 캐시를 무시하고 재조회한다.
    """
    corp_code, bsns_year, reprt_code, fs_div = _check_fin_args(corp_code, bsns_year, reprt_code, fs_div)
    wanted = STATEMENTS
    if sj_div:
        wanted = tuple(s.strip().upper() for s in sj_div.split(",") if s.strip())
        bad = [s for s in wanted if s not in STATEMENTS]
        if bad:
            return {"error": f"sj_div {bad} 없음. 사용 가능: {list(STATEMENTS)}"}
    data = load_statements(_get_client, corp_code, bsns_year, reprt_code, fs_div, refresh=refresh)
    base = {
        "corp_code": corp_code, "bsns_year": bsns_year,
        "reprt_code": reprt_code, "reprt_nm": REPRT_CODES[reprt_code],
        "fs_div": fs_div, "fs_nm": FS_DIVS[fs_div],
        "unit": "원(KRW)", "years": period_years(bsns_year),
    }
    if data["status"] == NO_DATA_STATUS:
        return {**base, "rcept_no": None, "statements": {}, "message": _no_data_message(*_base_args(base))}
    statements = group_statements(data["list"], bsns_year, wanted)
    return {
        **base,
        "rcept_no": data.get("rcept_no"),
        "currency": (data["list"][0].get("currency") if data["list"] else None),
        "row_counts": {k: len(v["rows"]) for k, v in statements.items()},
        "statements": statements,
    }


def _base_args(base: dict) -> tuple[str, str, str, str]:
    return base["corp_code"], base["bsns_year"], base["reprt_code"], base["fs_div"]


@mcp.tool()
@_safe
def get_key_financials(
    corp_code: str,
    bsns_year: str,
    fs_div: str = "CFS",
    reprt_code: str | None = "11011",
    period_type: str | None = None,
    refresh: bool = False,
) -> dict:
    """핵심 재무지표 10계정과 계산 비율을 돌려준다. 사업보고서는 3개년, 반기·분기보고서는 당기 vs 전년 동기.

    언제: 기업분석·비교 보고서의 재무 표를 만들 때 가장 먼저 쓴다. 원문 재무 섹션을 읽을 필요가 없다.
      여러 연도를 보려면 bsns_year만 바꿔 재호출한다 (예: 2024 → 2024·2023·2022, 2021 → 2021·2020·2019).
      최근 분기 동향은 get_latest_reports가 준 반기·분기보고서의 bsns_year·reprt_code로 호출한다.
    인자:
      - reprt_code: 11011=사업보고서(기본), 11012=반기, 11013=1분기, 11014=3분기
      - period_type: 사업보고서는 "annual"만 가능(생략 시 annual). 반기·분기는 "cumulative"(당기누적, 기본)
        또는 "quarter"(해당 3개월). 현금흐름표는 누적만 공시되므로 quarter면 CF 계정은 null.
      - refresh: 재무제표 정정이 의심되면 refresh=True (캐시 무시하고 재조회). 캐시는 90일이 지나면 자동 재조회.
    결과 (period_type="annual"):
      - years [당기, 전기, 전전기], periods [{year, name("제56기"), range, range_source}] 결산기 라벨.
        API에는 기간 날짜가 없어 range는 기업개황 결산월(acc_mt)로 추정한 값일 수 있다(range_source 참고).
      - accounts{key: {label, values{연도: 원}, matched}}, ratios{key: {label, values{연도: %}, formula}}
        ratios: 영업이익률, 순이익률, 부채비율, 자기자본비율(기말 잔액), ROE, ROA(평균잔액 (기초+기말)/2,
        전전기는 기초가 없어 기말 기준 — denominator_basis). ROE·ROA는 지배주주 계정(net_income_parent,
        equity_parent)이 둘 다 있으면 "지배주주 기준", 없으면 총액 기준이다(ratios.roe.basis). 보고서에 "계산" 표기.
      - flags: ["capital_impairment"]면 자본총계가 음수인 연도가 있다. 그 연도의 부채비율·자기자본비율·ROE는 null,
        설명은 note. 보고서 재무 표 아래에 "자본잠식(자본총계 음수)"을 밝힌다. 12월 결산이 아닌 회사도 note에 적는다.
    결과 (cumulative/quarter):
      - columns ["current", "prior"], column_labels로 각 열이 어떤 기간인지 설명.
        손익 계정의 prior는 **전년 동기**, 재무상태표 계정의 prior는 **전기말(직전 사업연도말)**이다.
        accounts[key].basis가 계정별 기준을 적는다. ratios는 영업이익률·순이익률·부채비율·자기자본비율만(ROE·ROA 없음).
      - 분기 수치를 연간 수치와 한 표에 섞지 않는다. 전년 동기와만 비교한다.
    공통: accounts 키 revenue 매출액, operating_income 영업이익, net_income 당기순이익(비지배 포함),
      total_assets, total_liabilities, total_equity, operating_cf, investing_cf, capex(유형자산취득), cash,
      그리고 optional인 net_income_parent(지배주주 순이익), equity_parent(지배주주 자본).
      missing: 찾지 못한 필수 계정 key (값 null). optional_missing: 없는 optional 계정(종속회사 없는 회사는 정상).
      단위는 모두 원(KRW).
      sector: {sector, induty_code, reason}. 업종은 기업개황 induty_code(KSIC)로 판단한다.
    금융업(sector="financial": 은행·보험·증권·금융지주)이면 warning이 붙는다. 이때 revenue와 영업이익률·순이익률은
      not_applicable/None이고, financial_accounts에 순이자이익·순수수료이익·보험수익·신용손실충당금전입이 온다
      (못 찾은 것은 financial_missing). 금융사를 일반 기업과 같은 표에서 비교하지 않는다.
    출처 표기: 보고서에는 (rcept_no, 재무API) 형태로 적는다.
    """
    corp_code, bsns_year, reprt_code, fs_div = _check_fin_args(corp_code, bsns_year, reprt_code, fs_div)
    annual = reprt_code == "11011"
    if period_type is None:
        period_type = "annual" if annual else "cumulative"
    if annual and period_type != "annual":
        return {"error": "사업보고서(11011)는 period_type='annual'만 가능합니다"}
    if not annual and period_type not in INTERIM_PERIOD_TYPES:
        return {"error": f"반기·분기보고서는 period_type이 {list(INTERIM_PERIOD_TYPES)} 중 하나여야 합니다: {period_type!r}"}
    data = load_statements(_get_client, corp_code, bsns_year, reprt_code, fs_div, refresh=refresh)
    base = {
        "corp_code": corp_code, "bsns_year": bsns_year, "reprt_code": reprt_code,
        "reprt_nm": REPRT_CODES[reprt_code], "period_type": period_type,
        "fs_div": fs_div, "fs_nm": FS_DIVS[fs_div], "unit": "원(KRW)",
    }
    if data["status"] == NO_DATA_STATUS:
        return {**base, "rcept_no": None, "accounts": {}, "ratios": {},
                "missing": [a.key for a in KEY_ACCOUNTS if a.key not in OPTIONAL_ACCOUNTS], "message": _no_data_message(*_base_args(base))}
    company = load_company(_get_client, corp_code)
    sector = detect_sector((company or {}).get("induty_code"), data["list"])
    extra: dict[str, Any] = {"sector": sector}
    if sector["sector"] == "financial":
        extra["warning"] = FINANCIAL_WARNING.format(reason=sector["reason"])
    if annual:
        return {**base, "rcept_no": data.get("rcept_no"), **extra,
                **summarize_key_financials(data["list"], bsns_year, sector["sector"], fs_div,
                                           (company or {}).get("acc_mt"))}
    prev = str(int(bsns_year) - 1)
    span = "누적" if period_type == "cumulative" else "3개월"
    labels = {
        "current": f"{bsns_year} {REPRT_CODES[reprt_code]} 기간 ({span}) / BS는 당기말",
        "prior": f"{prev} 동기 ({span}) / BS는 {prev} 사업연도말",
    }
    return {**base, "rcept_no": data.get("rcept_no"), "column_labels": labels, **extra,
            **summarize_interim_financials(data["list"], reprt_code, period_type, sector["sector"])}


@mcp.tool()
@_safe
def get_latest_reports(corp_code: str) -> dict:
    """가장 최근 사업보고서와 그 이후 제출된 반기·분기보고서를 찾아준다 (정정본 우선).

    언제: 사용자가 사업연도를 말하지 않았을 때, find_company 다음에 호출해 분석 대상 보고서를 정한다.
      최근 2년 정기공시(pblntf_ty=A)를 조회해 report_nm으로 사업/반기/분기보고서를 분류한다.
    결과:
      - latest_annual: {rcept_no, bsns_year, period("2025.12"), rcept_dt, report_nm, reprt_code "11011",
        prefix(원문 꼬리표), correction_kind("기재정정"|"첨부정정"|"첨부추가"|None), is_correction(기재정정만 True),
        supersedes[], original_rcept_no·original_rcept_dt(최초 제출본, 정정 없으면 자기 자신),
        body_rcept_no, attachment_rcept_no} — bsns_year는 get_key_financials(corp_code, bsns_year)에 쓴다.
        **본문 outline·섹션·검색은 body_rcept_no로, 감사보고서(00760/00761)는 attachment_rcept_no로** 읽는다.
        정정 ZIP에는 바뀐 부분만 있다: [첨부정정]·[첨부추가] ZIP은 본문이 없고, [기재정정] ZIP은 감사보고서 첨부가 없을 수 있다.
        body_rcept_no = 꼬리표 없음·[기재정정] 중 최신, attachment_rcept_no = 꼬리표 없음·[첨부정정]/[첨부추가] 중 최신(같으면 정정 없음).
        attachment_rcept_no의 원문 다운로드가 "status=014 파일이 존재하지 않습니다"로 실패하는 경우가 있다(첨부정정 실측).
        그때는 original_rcept_no(최초 제출본)의 첨부 감사보고서를 쓰고 보고서에 그 사실을 적는다.
        correction_kind="기재정정"이면 보고서 머리에 "[기재정정본, 접수일 YYYY-MM-DD]"를 적고 정정 사유를 확인한다.
      - interim_after_annual[]: 사업보고서 이후의 반기·분기보고서(기간순, body_rcept_no·attachment_rcept_no 포함), 각각 reprt_code
        (11013=1분기, 11012=반기, 11014=3분기)와 bsns_year 포함 → get_key_financials(corp_code, bsns_year,
        reprt_code=...)로 최근 누적 실적을 받는다.
      - superseded[]: 정정본에 밀린 원본(superseded_by). 분석에 쓰지 않는다.
      - late_corrections[]: latest_annual 최초 제출일(original_rcept_dt) 이후(같은 날 포함) 접수된, 그보다 앞선 기간(사업·반기·분기)의 정정본
        [{kind, period, rcept_no, rcept_dt, correction_kind}]. **있으면 전기 재무제표 재작성 가능성을 보고서에 적어라**
        (리스크 절 한 줄. 기재정정이면 특히). 첨부정정·첨부추가는 감사보고서 등 첨부만 바뀐 것이다.
      - reprt_code가 null인 반기·분기 항목: 결산기 변경 등으로 경과 개월수가 3·6·9가 아닌 경우다.
        get_key_financials에 넘기지 말고 search_disclosures로 기간을 확인한다.
      같은 기간에 [기재정정] 등이 여러 번 나오면 가장 늦게 접수된 것을 쓴다.
    """
    corp_code = corp_code.strip()
    if not re.fullmatch(r"\d{8}", corp_code):
        raise ValueError(f"corp_code는 8자리 숫자여야 합니다(find_company로 확인): {corp_code!r}")
    today = dt.date.today()
    bgn = today - dt.timedelta(days=731)
    found = search_disclosures(corp_code, bgn.strftime("%Y%m%d"), today.strftime("%Y%m%d"), "A", 200)
    if "error" in found:
        return found
    result = classify_periodic_reports(found["results"])
    for rep_ in ([result["latest_annual"]] if result["latest_annual"] else []) + result["interim_after_annual"]:
        for r in [rep_["rcept_no"], *rep_["supersedes"]]:
            _body_hint[r] = rep_["body_rcept_no"]
    if result["latest_annual"] is None:
        return {"corp_code": corp_code, "error": "최근 2년 안에 사업보고서가 없습니다. search_disclosures로 기간을 넓혀 확인하세요.",
                "searched": [bgn.isoformat(), today.isoformat()], "periodic_count": found["returned"]}
    return {"corp_code": corp_code, "searched": [bgn.isoformat(), today.isoformat()], **result}


def main() -> None:
    log.info("starting dart MCP server (stdio); data_dir=%s", _cache.data_dir)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
