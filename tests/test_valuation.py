import copy

from dart_mcp.document import HEURISTIC_MIN_CHARS, build_outline, split_by_markers
from dart_mcp.tables import find_tables
from dart_mcp.valuation import (
    classify_valuation_filing,
    date_windows,
    deal_stats,
    filter_rows,
    group_filings,
    pair_related,
    representative,
    scan_valuation_disclosures,
    validate_case,
    verify_citations,
)

# --------------------------------------------------------------------------- find_tables
# DART 원문 렌더링 그대로: 캡션·단위가 한 칸짜리 표로 따로 온다(우성 합병 2026-10 실측 모양)
SECTION = """본문 첫 줄입니다.

| |
|---|
| [외부평가기관인 한영 회계법인의 합병 비율 적정성 평가 요약] |

| |
|---|
| (단위: 원) |

| 구 분 | (주)우성 | (주)우성유통 |
|---|---|---|
| A. 기준시가 | 15,860 | 해당사항 없음 |
| B. 본질가치 | 해당사항 없음 | 124,992 |

민감도 분석 결과는 다음과 같습니다.

| 구분 | WACC -1.0% | WACC +1.0% |
|---|---|---|
| 주당가치 | 337,774 | 204,241 |
"""


def test_find_tables_attaches_bracket_caption_and_unit():
    out = find_tables(SECTION)
    assert out["total_matched"] == 2  # 한 칸짜리 캡션·단위 표는 결과에 넣지 않는다
    t = out["tables"][0]
    assert t["caption"] == "[외부평가기관인 한영 회계법인의 합병 비율 적정성 평가 요약]"
    assert t["caption_source"] == "bracket"
    assert t["unit"] == "(단위: 원)"
    assert t["rows"] == 3 and t["cols"] == 3
    assert SECTION[t["offset"]:].startswith("| 구 분 |")
    # 캡션 표가 없으면 바로 앞 줄
    assert out["tables"][1]["caption"] == "민감도 분석 결과는 다음과 같습니다."
    assert out["tables"][1]["caption_source"] == "line"


def test_find_tables_pattern_offset_and_truncation():
    only = find_tables(SECTION, "민감도")
    assert [t["rows"] for t in only["tables"]] == [2]
    by_header = find_tables(SECTION, "WACC")  # 캡션에 없어도 첫 두 행에 있으면 맞는다
    assert by_header["total_matched"] == 1
    first = find_tables(SECTION)["tables"][0]["offset"]
    after = find_tables(SECTION, offset=first + 1)
    assert after["total_matched"] == 1
    paged = find_tables(SECTION, max_tables=1)
    assert paged["has_more"] and paged["next_offset"] == after["tables"][0]["offset"]
    big = "| a | b |\n|---|---|\n" + "\n".join(f"| {i} | {'x' * 50} |" for i in range(400))
    t = find_tables(big, max_table_chars=1000)["tables"][0]
    assert t["truncated"] and len(t["text"]) == 1000 and t["chars"] > 1000


# --------------------------------------------------------------------------- 휴리스틱 소제목
def _big_text() -> str:
    filler = "평가 내용 서술입니다. " * 300  # 약 4,000자
    parts = ["머리 문단입니다.\n"]
    for head in ("가. 평가결과", "나. 희망공모가액의 산출 방법", "(1) 비교기업 선정", "[공모가 산정 요약표]", "다. 비교기업의 선정"):
        parts.append(f"{head}\n{filler}\n")
    parts.append("| 표 | 가. 표 안의 가나다는 경계가 아니다 |\n")
    text = "\n".join(parts)
    while len(text) < HEURISTIC_MIN_CHARS:
        text += filler + "\n"
    return text


def test_split_by_markers_boundaries_and_merge():
    parts = split_by_markers(_big_text())
    titles = [t for t, _ in parts]
    assert titles == ["가. 평가결과", "나. 희망공모가액의 산출 방법", "(1) 비교기업 선정", "[공모가 산정 요약표]", "다. 비교기업의 선정"]
    assert parts[0][1].startswith("머리 문단입니다.")  # 첫 표지 앞 머리는 첫 구간에 붙는다
    # 앞 표지에서 1,000자 안에 붙은 표지는 경계로 쓰지 않는다: "나." 구간이 "(1)"까지 품는다
    short = "가. 첫째\n" + "x" * 60_000 + "\n나. 둘째\n짧음\n(1) 셋째\n" + "y" * 5_000
    parts2 = split_by_markers(short)
    assert [t for t, _ in parts2] == ["가. 첫째", "나. 둘째"] and "(1) 셋째" in parts2[1][1]
    assert split_by_markers("가. 하나\n" + "x" * 1000 + "\n나. 둘") == []  # 5만 자 미만은 나누지 않는다


def _xml(doc_name: str, body: str) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?><DOCUMENT><DOCUMENT-NAME>{doc_name}</DOCUMENT-NAME><BODY>'
            f"<SECTION-1><TITLE>IV. 인수인의 의견</TITLE>{body}</SECTION-1>"
            f"<SECTION-1><TITLE>V. 기타</TITLE><P>짧음</P></SECTION-1></BODY></DOCUMENT>").encode("utf-8")


def test_heuristic_headings_only_for_large_untitled_non_periodic_main():
    body = "".join(f"<P>{line}</P>" for line in _big_text().split("\n"))
    secs = build_outline(_xml("증권신고서(지분증권)", body))
    heads = [s for s in secs if s.kind == "heading"]
    assert [s.id for s in heads][:2] == ["1.h1", "1.h2"] and all(s.level == 2 for s in heads)
    parent = next(s for s in secs if s.id == "1")
    assert all(h.text.strip() in parent.text for h in heads)  # search_in_disclosure의 하위 구간 판정용
    assert not any(s.kind == "heading" for s in build_outline(_xml("사업보고서", body)))  # 정기보고서 제외
    assert not any(s.kind == "heading" for s in build_outline(_xml("증권신고서(지분증권)", body), main=False))  # 첨부 제외


# --------------------------------------------------------------------------- 분류·묶기·짝
def test_classify_valuation_filing():
    c = classify_valuation_filing
    assert c("[기재정정]주요사항보고서(회사합병결정)")["deal_type"] == "merger"
    assert c("주요사항보고서(회사분할합병결정)")["deal_type"] == "split_merger"
    assert c("주요사항보고서(회사분할결정)")["source_grade"] == "summary"
    assert c("주요사항보고서(영업양수결정)")["deal_type"] == "business_transfer"
    assert c("주요사항보고서(주식교환ㆍ이전결정)")["deal_type"] == "share_exchange"
    full = c("[발행조건확정]증권신고서(지분증권)", "E")
    assert (full["deal_type"], full["source_grade"], full["prefix_kind"]) == ("ipo", "full", "발행조건확정")
    assert c("증권신고서(지분증권)", "K")["deal_type"] == "rights_offering"
    assert c("증권신고서(합병)")["filing_type"] == "증권신고서"
    assert c("증권신고서(주식의포괄적교환ㆍ이전)")["deal_type"] == "share_exchange"
    for other in ("주요사항보고서(유상증자결정)", "증권발행실적보고서(합병등)", "투자설명서", "증권신고서(채무증권)",
                  "소액공모공시서류(지분증권)", "타법인주식및출자증권양수결정"):
        assert c(other) is None, other


def _row(rcept_no, report_nm, rcept_dt, corp="00142661", cls="Y"):
    return {"rcept_no": rcept_no, "report_nm": report_nm, "rcept_dt": rcept_dt, "corp_code": corp,
            "corp_name": "우성", "corp_cls": cls, "flr_nm": "우성", **classify_valuation_filing(report_nm, cls)}


def test_group_corrections_and_pair_b_with_c():
    rows = [
        _row("20260904000355", "주요사항보고서(회사합병결정)", "20260904"),
        _row("20260909000530", "[첨부정정]주요사항보고서(회사합병결정)", "20260909"),
        _row("20261022000513", "[기재정정]주요사항보고서(회사합병결정)", "20261023"),
        _row("20261010000001", "증권신고서(합병)", "20261010"),
        _row("20261020000001", "[기재정정]증권신고서(합병)", "20261020"),
        _row("20261001000002", "[기재정정]주요사항보고서(회사분할결정)", "20261001"),  # 원본이 구간 밖
    ]
    deals = group_filings(rows)
    b = next(d for d in deals if d["deal_type"] == "merger" and d["filing_type"] == "주요사항보고서")
    assert b["rcept_no"] == "20261022000513" and b["original_rcept_no"] == "20260904000355"
    assert b["body_rcept_no"] == "20261022000513" and b["attachment_rcept_no"] == "20260909000530"
    assert sorted(b["supersedes"]) == ["20260904000355", "20260909000530"]
    split = next(d for d in deals if d["deal_type"] == "split")
    assert split["original_rcept_no"] is None and split["notes"]
    pair_related(deals)
    c = next(d for d in deals if d["filing_type"] == "증권신고서")
    assert b["related_rcept_nos"] == [c["rcept_no"]] == ["20261020000001"]
    assert c["related_rcept_nos"] == ["20261022000513"]
    assert split["related_rcept_nos"] == []


def test_scan_pages_windows_and_listed_filter():
    pages = {
        ("B001", 1): {"total_page": 2, "list": [
            {"rcept_no": "20261022000513", "report_nm": "주요사항보고서(회사합병결정)", "rcept_dt": "20261022",
             "corp_code": "00142661", "corp_name": "우성", "corp_cls": "Y"},
            {"rcept_no": "20261022000999", "report_nm": "주요사항보고서(유상증자결정)", "rcept_dt": "20261022",
             "corp_code": "00000001", "corp_name": "갑", "corp_cls": "K"}]},
        ("B001", 2): {"total_page": 2, "list": [
            {"rcept_no": "20261021000001", "report_nm": "주요사항보고서(회사합병결정)", "rcept_dt": "20261021",
             "corp_code": "00000002", "corp_name": "비상장", "corp_cls": "E"}]},
        ("C001", 1): {"total_page": 1, "list": [
            {"rcept_no": "20261026000001", "report_nm": "증권신고서(지분증권)", "rcept_dt": "20261026",
             "corp_code": "00000003", "corp_name": "제논", "corp_cls": "E"}]},
    }
    calls = []

    windows = date_windows("20260427", "20261026")
    latest_bgn = windows[0][0]  # 최신 구간(20260729–20261026)에만 공시가 있다고 둔다

    def list_page(**p):
        calls.append(p)
        return pages.get((p["pblntf_detail_ty"], p["page_no"]), {"total_page": 1, "list": []}) \
            if p["bgn_de"] == latest_bgn else {"total_page": 1, "list": []}

    res = scan_valuation_disclosures(list_page, "20260427", "20261026")
    assert res["windows"] == windows and len(windows) == 3 and windows[-1][0] == "20260427"
    assert {d["rcept_no"] for d in res["deals"]} == {"20261022000513", "20261026000001"}  # 비상장 B 제외, IPO는 남김
    assert sum(1 for p in calls if p["pblntf_detail_ty"] == "B001" and p["bgn_de"] == latest_bgn) == 2
    assert all("pblntf_ty" not in p for p in calls)  # 상세유형은 pblntf_ty 없이 줘야 걸린다
    only_ipo = scan_valuation_disclosures(list_page, "20260427", "20261026", kinds=["IPO"])
    assert [d["deal_type"] for d in only_ipo["deals"]] == ["ipo"]
    # 상장사 유상증자 신고서는 기본에서 빠지고 kinds로 명시해야 나온다
    pages[("C001", 1)]["list"].append({"rcept_no": "20261023000337", "report_nm": "증권신고서(지분증권)",
                                       "rcept_dt": "20261023", "corp_code": "00000004", "corp_name": "을", "corp_cls": "K"})
    default = scan_valuation_disclosures(list_page, "20260427", "20261026")
    assert "rights_offering" not in {d["deal_type"] for d in default["deals"]}
    ro = scan_valuation_disclosures(list_page, "20260427", "20261026", kinds="유상증자")
    assert [d["rcept_no"] for d in ro["deals"]] == ["20261023000337"]


# --------------------------------------------------------------------------- 스키마
def _cite(off):
    return {"section_id": "4", "offset": off, "file_id": "main"}


MIN_CASE = {
    "rcept_no": "20261014000077", "original_rcept_no": "20261014000077", "filing_type": "증권신고서",
    "source_grade": "full",
    "company": {"corp_code": "01016468", "name": "알테오젠", "market": "코스닥"},
    "deal": {"type": "merger", "counterparty": "알테오젠바이오로직스", "counterparty_listed": False,
             "related_party": True, "board_date": "2026-10-06", "regime": "기준시가"},
    "external_valuation": {"required": True, "exemption_reason": None, "basis_text": None, "firm": "이촌회계법인",
                           "firm_type": "회계법인", "period": None, "audit_committee_consent": None, "standards_cited": []},
    "valuations": [{
        "subject": "안진회계법인", "target": "알테오젠", "role": "재무자문", "purpose": "합병가액", "method": "DCF", "weights": None,
        "asset_value": None, "relative": None,
        "dcf": {"wacc": {"value": 8.1543, "unit": "%", "text": "8.1543%", "cite": _cite(10)}, "g": None, "peers": []},
        "result": {"value": {"value": 253384, "unit": "원", "cite": _cite(40)}, "unit": "원", "range": None},
    }],
    "conclusion": {"price_per_share": [], "range": [], "ratio": None, "opinion_text": None, "unit": "원"},
    "sensitivity": [], "citations": [],
    "extracted_at": "2026-10-26T15:00:00+09:00", "extractor_version": "1.0",
}


def test_schema_accepts_minimal_case_and_rejects_uncited_numbers():
    assert validate_case(MIN_CASE) == []
    bad = copy.deepcopy(MIN_CASE)
    bad["valuations"][0]["dcf"]["wacc"]["cite"] = None  # 숫자에는 cite가 반드시 있어야 한다
    bad["valuations"][0]["method"] = "감"  # 모르는 방법
    del bad["deal"]["regime"]
    errors = validate_case(bad)
    assert any("wacc" in e for e in errors) and any("method" in e for e in errors) and any("regime" in e for e in errors)
    ok_null = copy.deepcopy(MIN_CASE)
    ok_null["valuations"][0]["dcf"]["g"] = {"value": None, "cite": None}  # 원문에 없으면 null 허용
    assert validate_case(ok_null) == []
    text = "x" * 10 + "기준 가중평균자본비용: 8.1543%" + " " * 5 + "1주당 수익가치: 253,384원"
    res = verify_citations(MIN_CASE, lambda r, f, s: text, sample=8, seed=1)
    assert res["total"] == 2 and res["missing_cite"] == [] and all(x["ok"] for x in res["sampled"])


def test_distribution_warnings_are_separate_from_errors():
    from dart_mcp.valuation import distribution_warnings

    assert distribution_warnings(MIN_CASE) == []
    odd = copy.deepcopy(MIN_CASE)
    dcf = odd["valuations"][0]["dcf"]
    dcf["wacc"] = {"value": 4.0, "unit": "%", "text": "4.0%", "cite": dcf["wacc"]["cite"]}
    dcf["g"] = {"value": 0.06, "unit": None, "text": "0.06", "cite": dcf["wacc"]["cite"]}  # 단위 없는 소수 → 6%
    odd["ipo"] = {"multiple": {"value": -3.1, "unit": "배", "text": "-3.1", "cite": None},
                  "discount_range": {"min": {"value": 20.0, "unit": "%", "text": "20%", "cite": None},
                                     "max": {"value": 75.0, "unit": "%", "text": "75%", "cite": None}}}
    w = distribution_warnings(odd)
    assert any("g 6% > 5%" in x for x in w) and any("≥ WACC 4%" in x for x in w)
    assert any("ipo/multiple" in x for x in w) and any("discount_range/max" in x for x in w)
    assert not any("discount_range/min" in x for x in w) and not any("dcf/wacc" in x for x in w)
    big = copy.deepcopy(MIN_CASE)
    big["valuations"][0]["dcf"]["wacc"]["value"] = 31.5
    assert any("WACC 31.5%" in x for x in distribution_warnings(big)) and validate_case(big) == []


# --------------------------------------------------------------------------- 거래 단위 통계
def _r(rcept, role, wacc, purpose="합병가액", method="DCF", deal_type="merger", board="2026-10-06"):
    return {"rcept_no": rcept, "role": role, "wacc": wacc, "g": None, "multiple": None, "multiple_type": None,
            "purpose": purpose, "method": method, "deal_type": deal_type, "board_date": board,
            "firm": "이촌회계법인", "subject": "x"}


def test_representative_prefers_external_valuer_then_median():
    assert representative([("재무자문", 7.7), ("외부평가", 8.43), ("재무자문", 9.7)]) == 8.43
    assert representative([("재무자문", 7.0), ("재무자문", 9.0), ("주관사", 10.0)]) == 9.0
    assert representative([]) is None


def test_deal_stats_counts_deals_not_values_and_default_purpose_filter():
    rows = [_r("A", "재무자문", 7.7), _r("A", "외부평가", 8.43), _r("A", "재무자문", 9.7),
            _r("B", "재무자문", 10.0), _r("C", "외부평가", 14.04, purpose="공정가치평가", deal_type="ipo")]
    kept = filter_rows(rows)  # 기본: 공정가치평가·손상검사 제외
    assert {r["rcept_no"] for r in kept} == {"A", "B"}
    s = deal_stats(kept)
    w = s["variables"]["wacc"]
    assert (s["deals"], w["deals"], w["values"]) == (2, 2, 4)  # "2건 거래, 4개 값"
    assert w["per_deal"] == {"A": 8.43, "B": 10.0} and w["median"] == (8.43 + 10.0) / 2
    assert s["firms"] == {"x": 1, "(외부평가 없음)": 1}  # A는 외부평가 원소 subject, B는 없음
    from dart_mcp.valuation import range_order_errors
    assert range_order_errors({"r": {"min": {"value": 29.8}, "max": {"value": 11.7}}}) and \
        not range_order_errors({"r": {"min": {"value": 11.7}, "max": {"value": 29.8}}})
    assert len(filter_rows(rows, purposes={"all"})) == 5
    assert [r["rcept_no"] for r in filter_rows(rows, purposes={"공정가치평가"})] == ["C"]
    assert filter_rows(rows, date_from="2026-11-01") == []
    assert len(filter_rows(rows, regimes={"none"})) == 4 and filter_rows(rows, regimes={"기준시가"}) == []


# --------------------------------------------------------------------------- 업종(KSIC)
def test_industry_labels_and_filter():
    from dart_mcp.industry import label, section

    assert label("26429") == "26 전자부품·컴퓨터·영상·음향·통신장비" and label("21") == "21 의료용 물질·의약품"
    assert label("99999") == "99" and label(None) is None and label("7") is None  # 매핑 없는 중분류는 코드만
    assert section("70113") == "M 전문, 과학 및 기술 서비스업" and section("2221") == "C 제조업"
    rows = [dict(_r("A", "외부평가", 8.0), induty_code="26429"), dict(_r("B", "외부평가", 9.0), induty_code="21210"),
            dict(_r("C", "외부평가", 10.0), induty_code=None)]
    assert [r["rcept_no"] for r in filter_rows(rows, industries={"26"})] == ["A"]
    assert {r["rcept_no"] for r in filter_rows(rows, industries={"26", "212"})} == {"A", "B"}


def test_fill_case_records_reason(monkeypatch):
    from dart_mcp import industry

    monkeypatch.setattr(industry, "lookup", lambda code, data_dir=None: (None, "기업개황 조회 실패(DartApiError: 013)"))
    case = {"rcept_no": "X", "company": {"corp_code": "1", "induty_code": None}, "notes": ["기존"]}
    res = industry.fill_case(case)
    assert res["changed"] and case["company"]["induty_code"] is None
    assert case["notes"][0] == "기존" and case["notes"][1].startswith("induty_code: null — 기업개황 조회 실패")
    monkeypatch.setattr(industry, "lookup", lambda code, data_dir=None: ("26429", None))
    assert industry.fill_case(case)["induty_code"] == "26429" and case["notes"] == ["기존"]  # 다시 채우면 사유 note는 지운다


def test_asset_sum_identity_skips_split_and_catches_sign():
    from dart_mcp.valuation import identity_checks

    def st(adj, typ="merger", known=None):
        n = lambda v: {"value": v, "unit": "원", "text": f"{v:,}", "cite": None}
        c = {"deal": {"type": typ}, "valuations": [{"asset_value": {"equity_book": n(1000), "adjustments": n(adj), "total": n(900)}}],
             "conclusion": {}, "source_inconsistent": known or []}
        return [x["status"] for x in identity_checks(c) if x["check"] == "g_asset_sum"]
    assert st(-100) == ["pass"] and st(100) == ["warn"]  # 차감을 양수로 넣은 경우
    assert st(100, "split") == ["skip"]
    assert st(100, known=[{"check": "g_asset_sum", "path": "valuations/0", "note": "원문 표 합계 불일치"}]) == ["source_inconsistent"]


def _pctf(v, text=None):
    return {"value": v, "unit": "%", "text": text or f"{v}%", "cite": None}


def test_identity_beta_flags_de_dv_confusion_and_wacc_ke():
    from dart_mcp.valuation import identity_checks

    dcf = {"beta_unlevered": {"value": 0.7083, "unit": None, "text": "0.7083", "cite": None},
           "beta_levered": {"value": 0.8774, "unit": None, "text": "0.8774", "cite": None},
           "tax_rate": _pctf(20.9), "target_de": _pctf(30.18), "rf": _pctf(2.99), "mrp": _pctf(8.0),
           "size_premium": _pctf(3.75), "ke": _pctf(13.76), "kd": _pctf(4.27), "wacc": _pctf(11.4, "11.4%")}
    case = {"deal": {"type": "merger"}, "valuations": [{"dcf": dcf}], "conclusion": {}}
    st = {x["check"]: x for x in identity_checks(case)}
    assert st["a_beta"]["status"] == st["b_ke"]["status"] == st["c_wacc"]["status"] == "pass"  # 애드포러스 2025 실값
    dcf2 = dict(dcf, target_de=None, target_dv=_pctf(30.18))  # 같은 값을 D/V로 잘못 넣은 경우
    a = {x["check"]: x for x in identity_checks({**case, "valuations": [{"dcf": dcf2}]})}["a_beta"]
    assert a["status"] == "warn" and "D/E↔D/V 혼동 의심" in a["detail"]


def test_identity_intrinsic_and_ratio():
    from dart_mcp.valuation import identity_checks

    n = lambda v: {"value": v, "unit": "원", "text": f"{v:,}", "cite": None}
    val = {"method": "본질가치", "weights": {"asset": 1, "income": 1.5}, "asset_value": {"per_share": n(4313)},
           "income_value": n(22331), "result": {"value": n(15124), "unit": "원", "range": None}}
    case = {"deal": {"type": "merger"}, "valuations": [val],
            "conclusion": {"price_per_share": [{"value": n(15124)}, {"value": n(2000)}],
                           "ratio": {"value": 0.1322397, "unit": None, "text": "0.1322397", "cite": None}}}
    st = {x["check"]: x["status"] for x in identity_checks(case)}
    assert st["d_intrinsic"] == st["f_ratio"] == "pass" and st["g_asset_sum"] == "skip"


def test_classify_deal_status_window_and_withdrawal():
    from dart_mcp.valuation import classify_deal_status

    f = lambda r, nm: {"rcept_no": r, "rcept_dt": r[:8], "report_nm": nm}
    case = {"rcept_no": "20260623000368", "deal": {"type": "merger"}, "related_rcept_nos": ["20260623000373"]}
    rows = [f("20260623000368", "[기재정정]증권신고서(합병)"), f("20260623000373", "주요사항보고서(회사합병결정)"),
            f("20260929000637", "철회신고서"), f("20260929000640", "기타주요경영사항 (회사합병 결정 철회)")]
    r = classify_deal_status(case, rows, "20261027")
    assert r["status"] == "철회·중단" and r["status_source"] == "20260929000637"  # 같은 날 짝 공시는 새 거래가 아니다
    hlb = {"rcept_no": "20250519000315", "deal": {"type": "merger"}, "related_rcept_nos": []}
    rows = [f("20250801000001", "기타경영사항(자율공시) (회사합병결정 철회에 관한 사항)"),
            f("20250917000002", "주요사항보고서(회사합병결정)"), f("20251231000386", "증권발행실적보고서(합병등)")]
    assert classify_deal_status(hlb, rows, "20261027")["status"] == "철회·중단"  # 다음 거래의 완료를 붙이지 않는다
    gx = {"rcept_no": "20240726000291", "deal": {"type": "merger"}, "related_rcept_nos": []}
    rows = [f("20240701000001", "증권신고서(합병)"), f("20240729000148", "철회신고서"), f("20241002000001", "합병등종료보고서(합병)")]
    assert classify_deal_status(gx, rows, "20261027")["status"] == "완료"  # 철회 뒤 완료면 완료
    assert classify_deal_status(gx, [], "20240901")["status"] == "진행" and classify_deal_status(gx, [], "20261027")["status"] == "미확인"


def test_industry_section_groups():
    from dart_mcp.industry import matches

    assert matches("29271", "제조업") and matches("10897", "C") and not matches("58222", "제조업")
    assert matches("58222", "정보통신") and matches("64992", "금융보험") and matches("47122", "도소매")
    assert matches("26429", "26") and not matches("26429", "27")
    rows = [dict(_r("A", "외부평가", 8.0), induty_code="29271"), dict(_r("B", "외부평가", 9.0), induty_code="58222")]
    assert [r["rcept_no"] for r in filter_rows(rows, industries={"제조업"})] == ["A"]


# --------------------------------------------------------------------------- v1.6 조회 기능
def test_firm_filter_uses_subject_and_role_only():
    rows = [dict(_r("A", "외부평가", 8.0), subject="한미회계법인", firm="한미회계법인(존속), 한울회계법인(소멸)"),
            dict(_r("A", "외부평가", 12.0), subject="한울회계법인", firm="한미회계법인(존속), 한울회계법인(소멸)"),
            dict(_r("B", "재무자문", 9.0), subject="한미회계법인"), dict(_r("B", "외부평가", 11.0), subject="이촌회계법인")]
    ext = filter_rows(rows, firm="한미")
    assert [(r["rcept_no"], r["wacc"]) for r in ext] == [("A", 8.0)]  # 같은 거래의 한울 값·다른 역할은 빠진다
    assert deal_stats(ext)["variables"]["wacc"]["per_deal"] == {"A": 8.0}
    assert {r["wacc"] for r in filter_rows(rows, firm="한미", firm_role="any")} == {8.0, 9.0}
    assert [r["wacc"] for r in filter_rows(rows, firm="한미", firm_role="재무자문")] == [9.0]


def test_status_and_spac_filters():
    rows = [dict(_r("A", "외부평가", 8.0), status="완료", spac=True), dict(_r("B", "외부평가", 9.0), status="철회·중단", spac=False),
            dict(_r("C", "외부평가", 10.0), status=None, spac="unknown")]
    assert [r["rcept_no"] for r in filter_rows(rows, exclude_statuses={"철회·중단"})] == ["A", "C"]
    assert [r["rcept_no"] for r in filter_rows(rows, statuses={"none"})] == ["C"]
    assert [r["rcept_no"] for r in filter_rows(rows, spac={"true"})] == ["A"]
    assert [r["rcept_no"] for r in filter_rows(rows, spac={"unknown"})] == ["C"]


def test_derive_spac_by_name_text_and_unknown():
    from dart_mcp.casedb import derive_spac

    def case(name, cp, basis="", note="", ev=""):
        return {"company": {"name": name}, "deal": {"type": "merger", "counterparty": cp},
                "external_valuation": {"basis_text": ev}, "valuations": [{"weights": {"basis": basis}, "note": note}], "notes": []}
    assert derive_spac(case("바이오포트", "디비금융제11호기업인수목적(주)"))[0] is True
    v, b = derive_spac(case("지슨", "주식회사 지슨", ev="SPAC 합병으로 피합병법인은"))
    assert v is True and b.startswith("문구:")  # 이름엔 없고 문구로만
    assert derive_spac(case("넥상스코리아", "넥상스대영", note="상증세법 보충적 평가"))[0] is False
    assert derive_spac(case("A", "B"))[0] == "unknown"  # 볼 문구가 없다
    assert derive_spac({**case("A", "B"), "deal": {"type": "split", "counterparty": None}})[0] is False


def test_compare_percentile_nearest_and_small_sample():
    from dart_mcp.casedb import compare, percentile

    assert percentile([1, 2, 3, 4], 2.5) == 50 and percentile([1, 2, 2, 3], 2) == 50
    rows = [dict(_r(k, "외부평가", w), g=g, company=k, spac=True) for k, w, g in (("A", 10.0, 1.0), ("B", 11.0, 1.0), ("C", 14.0, 0.0))]
    out = compare(rows, {"wacc": 11.2, "g": 1.0}, n=2)
    assert out["variables"]["wacc"]["n"] == 3 and out["variables"]["wacc"]["note"].startswith("표본 부족")
    assert [x["rcept_no"] for x in out["nearest"]] == ["B", "A"] and out["warning"].startswith("표본 부족")


def test_export_csv_has_bom_and_columns(tmp_path):
    import csv

    from dart_mcp.casedb import EXPORT_COLUMNS, export_rows, write_csv

    case = copy.deepcopy(MIN_CASE)
    rows = export_rows([case])
    assert len(rows) == len(case["valuations"]) and rows[0]["WACC"] == 8.1543
    p = tmp_path / "x.csv"
    write_csv(rows, p)
    assert p.read_bytes()[:3] == b"\xef\xbb\xbf"
    assert next(csv.reader(open(p, encoding="utf-8-sig"))) == EXPORT_COLUMNS


def test_null_audit_negation_marks_absent(monkeypatch):
    from dart_mcp import nullaudit

    cite = {"section_id": "5", "offset": 0, "file_id": "main"}
    case = {"rcept_no": "X", "deal": {"type": "merger"}, "conclusion": {},
            "valuations": [{"purpose": "합병가액", "method": "DCF", "dcf": {"wacc": {"value": 9, "unit": "%", "text": "9%", "cite": cite},
                                                                       "size_premium": None, "peers": []}}]}
    monkeypatch.setattr(nullaudit, "_section_texts", lambda r, s: {"5": "자기자본비용 산정시 Size risk premium을 반영하지 않았습니다." + " " * 200 + "동종기업 Unlevered Beta 표"})
    got = {it["field"]: it for it in nullaudit.audit_case(case)["items"]}
    assert got["size_premium"]["reason"] == "원문에 없음" and "미적용 명시" in got["size_premium"]["basis"]
    assert got["peers"]["reason"] == "추출 안 함" and got["relative"]["reason"] == "원문에 없음"
