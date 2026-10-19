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
    (h,) = r["interim_after_annual"]
    assert h["rcept_no"] == "20260901000555" and h["supersedes"] == ["20260814003699"]
    assert {s["rcept_no"]: s["superseded_by"] for s in r["superseded"]} == {
        "20260310002820": "20260402000123",
        "20260814003699": "20260901000555",
    }


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
