from dart_mcp.financials import summarize_interim_financials
from dart_mcp.periodic import classify_periodic_reports


def f(rcept_no, report_nm):
    return {"rcept_no": rcept_no, "report_nm": report_nm, "rcept_dt": rcept_no[:8]}


def test_classify_latest_annual_and_following_interims():
    items = [
        f("20260814003699", "반기보고서 (2026.06)"),
        f("20260515002181", "분기보고서 (2026.03)"),
        f("20260310002820", "사업보고서 (2025.12)"),
        f("20251114002447", "분기보고서 (2025.09)"),  # 최신 사업보고서 이전 → 제외
        f("20250311001085", "사업보고서 (2024.12)"),
        f("20250401000001", "주요사항보고서(자기주식취득결정)"),  # 정기보고서 아님 → 무시
    ]
    r = classify_periodic_reports(items)
    a = r["latest_annual"]
    assert (a["rcept_no"], a["bsns_year"], a["reprt_code"], a["period"]) == ("20260310002820", "2025", "11011", "2025.12")
    assert [(x["period"], x["reprt_code"], x["bsns_year"]) for x in r["interim_after_annual"]] == [
        ("2026.03", "11013", "2026"),
        ("2026.06", "11012", "2026"),
    ]
    assert r["superseded"] == []
    assert r["fy_end_month"] == 12


def test_correction_supersedes_original():
    items = [
        f("20260310002820", "사업보고서 (2025.12)"),
        f("20260402000123", "[기재정정]사업보고서 (2025.12)"),
        f("20260814003699", "반기보고서 (2026.06)"),
        f("20260901000555", "[첨부정정]반기보고서 (2026.06)"),
    ]
    r = classify_periodic_reports(items)
    a = r["latest_annual"]
    assert a["rcept_no"] == "20260402000123" and a["is_correction"] and a["supersedes"] == ["20260310002820"]
    assert (a["prefix"], a["correction_kind"]) == ("[기재정정]", "기재정정")
    (h,) = r["interim_after_annual"]
    assert h["rcept_no"] == "20260901000555" and h["supersedes"] == ["20260814003699"]
    # 첨부정정은 본문이 그대로이므로 is_correction=False (호환 필드는 기재정정만 True)
    assert (h["prefix"], h["correction_kind"], h["is_correction"]) == ("[첨부정정]", "첨부정정", False)
    assert {s["rcept_no"]: s["superseded_by"] for s in r["superseded"]} == {
        "20260310002820": "20260402000123",
        "20260814003699": "20260901000555",
    }


def test_correction_kind_variants():
    from dart_mcp.periodic import correction_kind

    assert correction_kind("[기재정정]") == "기재정정"
    assert correction_kind("[첨부추가]") == "첨부추가"
    assert correction_kind("[기재정정][첨부추가]") == "기재정정"  # 본문 영향이 큰 쪽
    assert correction_kind("") is None and correction_kind("[발행조건확정]") is None
    r = classify_periodic_reports([f("20260310002820", "[첨부추가]사업보고서 (2025.12)")])
    a = r["latest_annual"]
    assert (a["correction_kind"], a["is_correction"], a["prefix"]) == ("첨부추가", False, "[첨부추가]")
    assert r["late_corrections"] == []


def test_late_corrections_of_past_periods():
    items = [
        f("20250311001085", "사업보고서 (2024.12)"),
        f("20251114002447", "분기보고서 (2025.09)"),
        f("20260310002820", "사업보고서 (2025.12)"),
        f("20260420000001", "[기재정정]사업보고서 (2024.12)"),   # 최신 사업보고서 이후 전기 정정 → 포함
        f("20260421000002", "[첨부정정]분기보고서 (2025.09)"),   # 과거 분기 첨부정정 → 포함(종류 표시)
        f("20251201000003", "[기재정정]분기보고서 (2025.09)"),   # 최신 사업보고서보다 먼저 접수 → 제외
        f("20260515002181", "[기재정정]분기보고서 (2026.03)"),   # 사업보고서 이후 기간 → 제외
    ]
    r = classify_periodic_reports(items)
    assert r["latest_annual"]["rcept_no"] == "20260310002820"
    assert r["late_corrections"] == [
        {"kind": "사업보고서", "period": "2024.12", "rcept_no": "20260420000001", "rcept_dt": "20260420",
         "correction_kind": "기재정정"},
        {"kind": "분기보고서", "period": "2025.09", "rcept_no": "20260421000002", "rcept_dt": "20260421",
         "correction_kind": "첨부정정"},
    ]


def test_late_corrections_same_day_bulk_correction():
    # GS건설 패턴: 최신 사업보고서 정정본과 과거 기간 정정본을 같은 날 일괄 접수, 과거 것의 rcept_no가 더 작다
    items = [
        f("20260316001192", "사업보고서 (2025.12)"),
        f("20260701000624", "[기재정정]사업보고서 (2025.12)"),
        f("20260630000500", "[기재정정]사업보고서 (2023.12)"),
        f("20260701000495", "[기재정정]반기보고서 (2024.06)"),
        f("20260701000540", "[기재정정]사업보고서 (2024.12)"),
        f("20260701000569", "[기재정정]반기보고서 (2025.06)"),
        f("20250813000906", "[기재정정]사업보고서 (2024.12)"),  # 최초 제출일(2026-03-16) 이전 → 제외
    ]
    r = classify_periodic_reports(items)
    a = r["latest_annual"]
    assert a["rcept_no"] == "20260701000624"
    assert (a["original_rcept_no"], a["original_rcept_dt"]) == ("20260316001192", "20260316")
    assert [(x["period"], x["rcept_no"]) for x in r["late_corrections"]] == [
        ("2023.12", "20260630000500"),
        ("2024.06", "20260701000495"),
        ("2024.12", "20260701000540"),
        ("2025.06", "20260701000569"),
    ]


def test_original_fields_without_correction():
    r = classify_periodic_reports([f("20260310002820", "사업보고서 (2025.12)")])
    a = r["latest_annual"]
    assert (a["original_rcept_no"], a["original_rcept_dt"]) == ("20260310002820", "20260310")


def test_interim_cumulative_vs_quarter_fields():
    # 실제 반기 응답 모양: IS는 3개월/누적 분리, CF는 thstrm_amount가 누적, BS prior는 전기말
    items = [
        {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "ord": "1",
         "thstrm_amount": "30", "thstrm_add_amount": "55", "frmtrm_q_amount": "20", "frmtrm_add_amount": "40"},
        {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm": "영업활동현금흐름", "ord": "1", "thstrm_amount": "70", "frmtrm_q_amount": "33"},
        {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "ord": "1",
         "thstrm_amount": "900", "frmtrm_amount": "800"},
    ]
    cum = summarize_interim_financials(items, "11012", "cumulative")["accounts"]
    q = summarize_interim_financials(items, "11012", "quarter")["accounts"]
    assert cum["revenue"]["values"] == {"current": 55, "prior": 40}
    assert q["revenue"]["values"] == {"current": 30, "prior": 20}
    assert cum["operating_cf"]["values"] == {"current": 70, "prior": 33}
    assert q["operating_cf"]["values"] == {"current": None, "prior": None}
    assert cum["total_assets"]["values"] == q["total_assets"]["values"] == {"current": 900, "prior": 800}


def test_null_reprt_code_gives_clear_error():
    # get_latest_reports가 결산기 변경 등으로 reprt_code=None을 준 항목을 그대로 넘긴 경우 (API 호출 전에 막힌다)
    from dart_mcp import server

    for tool in (server.get_key_financials, server.get_financial_statements):
        r = tool("00126380", "2026", reprt_code=None)
        assert "reprt_code가 null" in r["error"] and "search_disclosures" in r["error"]


def test_body_and_attachment_sources_by_correction_kind():
    items = [
        f("20260310000001", "사업보고서 (2025.12)"),
        f("20260402000002", "[기재정정]사업보고서 (2025.12)"),
        f("20260415000003", "[첨부정정]사업보고서 (2025.12)"),
    ]
    a = classify_periodic_reports(items)["latest_annual"]
    assert a["rcept_no"] == "20260415000003"  # 최신본은 여전히 가장 늦은 접수
    assert (a["body_rcept_no"], a["attachment_rcept_no"]) == ("20260402000002", "20260415000003")


def test_body_and_attachment_sources_without_or_with_one_correction():
    plain = classify_periodic_reports([f("20260310000001", "사업보고서 (2025.12)")])["latest_annual"]
    assert plain["body_rcept_no"] == plain["attachment_rcept_no"] == "20260310000001"
    only_body = classify_periodic_reports([
        f("20260310000001", "사업보고서 (2025.12)"),
        f("20260331000002", "[기재정정]사업보고서 (2025.12)"),
        f("20260814000003", "반기보고서 (2026.06)"),
        f("20260820000004", "[첨부추가]반기보고서 (2026.06)"),
    ])
    a = only_body["latest_annual"]
    assert (a["body_rcept_no"], a["attachment_rcept_no"]) == ("20260331000002", "20260310000001")
    (h,) = only_body["interim_after_annual"]
    assert (h["body_rcept_no"], h["attachment_rcept_no"]) == ("20260814000003", "20260820000004")
