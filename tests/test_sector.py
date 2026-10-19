"""금융업 판단(detect_sector)과 금융업 계정 요약, 현금 CF 대체, company.json 캐시."""

import json

from dart_mcp.financials import (
    detect_sector,
    load_company,
    summarize_interim_financials,
    summarize_key_financials,
)


def row(sj_div, account_nm, thstrm, account_id="-표준계정코드 미사용-", ord_=1, **extra):
    return {"sj_div": sj_div, "account_nm": account_nm, "account_id": account_id, "ord": str(ord_),
            "thstrm_amount": thstrm, "frmtrm_amount": "", "bfefrmtrm_amount": "", **extra}


# KB금융 2025 사업보고서 응답(00688996_2025_11011_CFS)의 계정 구성을 줄인 것: 매출액 없음, BS에 현금및현금성자산 없음
BANK = [
    row("BS", "현금 및 예치금", "34776877000000", "dart_CashAndDuefromBanks"),
    row("BS", "자산총계", "797923033000000", "ifrs-full_Assets"),
    row("BS", "부채총계", "737093044000000", "ifrs-full_Liabilities"),
    row("BS", "자본총계", "60829989000000", "ifrs-full_Equity"),
    row("CIS", "순이자손익", "13073093000000", "ifrs-full_InterestRevenueExpense"),
    row("CIS", "이자수익", "29156100000000", "ifrs-full_RevenueFromInterest"),
    row("CIS", "순수수료손익", "4098287000000", "ifrs-full_FeeAndCommissionIncomeExpense"),
    row("CIS", "보험수익", "11651881000000", "ifrs-full_InsuranceRevenue"),
    row("CIS", "신용손실충당금 반영전 영업이익", "10880589000000"),
    row("CIS", "영업이익", "8517711000000", "ifrs-full_ProfitLossFromOperatingActivities"),
    row("CIS", "당기순이익", "5840715000000", "ifrs-full_ProfitLoss"),
    row("CF", "기초 현금 및 현금성자산", "24608867000000", "dart_CashAndCashEquivalentsAtBeginningOfPeriodCf"),
    row("CF", "기말 현금 및 현금성자산", "29020564000000", "ifrs-full_CashAndCashEquivalents"),
]
# 비금융 지주회사(SK·LG 등도 induty_code 64992): 매출액이 있다
HOLDING = [row("CIS", "매출액", "100", "ifrs-full_Revenue"), row("CIS", "이자수익", "1", "ifrs-full_RevenueFromInterest")]


def test_detect_sector_by_induty_code_and_holding_signal():
    assert detect_sector("64992", BANK)["sector"] == "financial"     # KB금융: 금융지주
    assert detect_sector("64992", HOLDING)["sector"] == "general"    # 비금융 지주
    assert detect_sector("65110", HOLDING)["sector"] == "financial"  # 보험업은 코드만으로
    assert detect_sector("264", BANK)["sector"] == "general"         # 제조업 코드면 계정과 무관
    assert detect_sector(None, BANK)["sector"] == "financial"        # 업종 조회 실패 → 계정 신호
    assert detect_sector(None, HOLDING)["sector"] == "unknown"


def test_financial_summary_marks_revenue_not_applicable_and_adds_bank_accounts():
    out = summarize_key_financials(BANK, "2025", sector="financial")
    assert "revenue" not in out["missing"] and out["not_applicable"] == ["revenue"]
    assert out["ratios"]["operating_margin"]["values"]["2025"] is None
    assert "금융업" in out["ratios"]["net_margin"]["note"]
    fin = out["financial_accounts"]
    assert fin["net_interest_income"]["values"]["2025"] == 13073093000000
    assert fin["net_fee_income"]["values"]["2025"] == 4098287000000
    assert fin["insurance_revenue"]["values"]["2025"] == 11651881000000
    assert out["financial_missing"] == ["credit_loss_provision"]
    # 같은 데이터를 일반 기업으로 요약하면 revenue가 missing으로 남는다(기존 동작)
    assert "revenue" in summarize_key_financials(BANK, "2025")["missing"]


def test_cash_falls_back_to_cf_closing_balance():
    out = summarize_key_financials(BANK, "2025")
    cash = out["accounts"]["cash"]
    assert cash["values"]["2025"] == 29020564000000
    assert cash["matched"]["sj_div"] == "CF" and "CF 기말현금" in cash["matched"]["by"]
    assert "cash" not in out["missing"]


def test_interim_cash_from_cf_compares_prior_year_same_period_end():
    items = [row("CF", "기말 현금 및 현금성자산", "35", "ifrs-full_CashAndCashEquivalents", frmtrm_q_amount="29")]
    out = summarize_interim_financials(items, "11012", "cumulative", sector="financial")
    cash = out["accounts"]["cash"]
    assert cash["values"] == {"current": 35, "prior": 29}
    assert cash["basis"].startswith("balance(CF 기말현금")
    assert out["not_applicable"] == ["revenue"]


def test_load_company_caches_and_survives_failure(tmp_path):
    calls = []

    class Fake:
        def get_company(self, corp_code):
            calls.append(corp_code)
            return {"status": "000", "corp_code": corp_code, "induty_code": "64992", "corp_cls": "Y"}

    assert load_company(Fake, "00688996", tmp_path)["induty_code"] == "64992"
    assert load_company(lambda: (_ for _ in ()).throw(AssertionError("cache miss")), "00688996", tmp_path)["corp_cls"] == "Y"
    assert len(calls) == 1
    assert json.loads((tmp_path / "company" / "00688996.json").read_text(encoding="utf-8"))["company"]["corp_cls"] == "Y"

    class Broken:
        def get_company(self, corp_code):
            raise RuntimeError("network down")

    assert load_company(Broken, "00000001", tmp_path) is None
