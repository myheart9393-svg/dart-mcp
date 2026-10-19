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
from .financials import (
    FS_DIVS,
    KEY_ACCOUNTS,
    NO_DATA_STATUS,
    REPRT_CODES,
    STATEMENTS,
    group_statements,
    load_statements,
    period_years,
    summarize_key_financials,
)

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
    다음: 읽을 섹션을 고른 뒤 get_disclosure_section(rcept_no, section_id, file_id)를 호출한다.
      section_id에는 ".tN" 소제목 id도 그대로 쓸 수 있다.
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
    depth = max(0, depth)
    return {
        "rcept_no": disc.rcept_no,
        "depth": depth,
        "total_chars": sum(f.total_chars for f in files),
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "total_chars": f.total_chars,
                "section_count": len(f.sections),
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


def _check_fin_args(corp_code: str, bsns_year: str, reprt_code: str, fs_div: str) -> tuple[str, str, str, str]:
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
    reprt_code: str = "11011",
    fs_div: str = "CFS",
    sj_div: str | None = None,
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
    캐시: data/fin/<corp_code>_<연도>_<reprt_code>_<fs_div>.json. 한 번 받으면 재호출해도 API를 쓰지 않는다.
    """
    corp_code, bsns_year, reprt_code, fs_div = _check_fin_args(corp_code, bsns_year, reprt_code, fs_div)
    wanted = STATEMENTS
    if sj_div:
        wanted = tuple(s.strip().upper() for s in sj_div.split(",") if s.strip())
        bad = [s for s in wanted if s not in STATEMENTS]
        if bad:
            return {"error": f"sj_div {bad} 없음. 사용 가능: {list(STATEMENTS)}"}
    data = load_statements(_get_client, corp_code, bsns_year, reprt_code, fs_div)
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
def get_key_financials(corp_code: str, bsns_year: str, fs_div: str = "CFS") -> dict:
    """사업보고서 기준 핵심 재무지표 3개년(당기·전기·전전기)과 계산 비율을 돌려준다.

    언제: 기업분석·비교 보고서의 재무 표를 만들 때 가장 먼저 쓴다. 원문 재무 섹션을 읽을 필요가 없다.
      여러 연도를 보려면 bsns_year만 바꿔 재호출한다 (예: 2024 → 2024·2023·2022, 2021 → 2021·2020·2019).
    결과:
      - accounts{key: {label, values{연도: 원}, matched}}: revenue 매출액, operating_income 영업이익,
        net_income 당기순이익(비지배지분 포함 연결 총액), total_assets 자산총계, total_liabilities 부채총계,
        total_equity 자본총계, operating_cf 영업활동현금흐름, investing_cf 투자활동현금흐름,
        capex 유형자산취득(CAPEX 대용, 현금흐름표 금액 그대로·부호는 회사 표기를 따름), cash 현금및현금성자산.
        matched는 어떤 계정으로 잡았는지(account_id 우선, 없으면 계정명 일치)를 보여준다.
      - ratios{key: {label, values{연도: %}}}: 영업이익률, 순이익률, 부채비율, 자기자본비율, ROE, ROA.
        모두 해당 연도 기말 잔액 기준 단순 계산(평균잔액 아님). 보고서에는 "계산"으로 표기한다.
      - missing: 찾지 못한 계정 key 목록 (값은 null). 단위는 모두 원(KRW).
    출처 표기: 보고서에는 (rcept_no, "재무API") 형태로 적는다.
    """
    corp_code, bsns_year, reprt_code, fs_div = _check_fin_args(corp_code, bsns_year, "11011", fs_div)
    data = load_statements(_get_client, corp_code, bsns_year, reprt_code, fs_div)
    base = {
        "corp_code": corp_code, "bsns_year": bsns_year, "reprt_code": reprt_code,
        "fs_div": fs_div, "fs_nm": FS_DIVS[fs_div], "unit": "원(KRW)",
    }
    if data["status"] == NO_DATA_STATUS:
        return {**base, "rcept_no": None, "years": period_years(bsns_year), "accounts": {}, "ratios": {},
                "missing": [a.key for a in KEY_ACCOUNTS], "message": _no_data_message(*_base_args(base))}
    return {**base, "rcept_no": data.get("rcept_no"), **summarize_key_financials(data["list"], bsns_year)}


def main() -> None:
    log.info("starting dart MCP server (stdio); data_dir=%s", _cache.data_dir)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
