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


# 카카오뱅크(별도, 2025): 순이자손익·순수수료손익 소계 행이 없고 수익·비용 행만 있다 (retro 2026-11-04 B3)
KAKAOBANK = [
    row("BS", "자산총계", "70000000000000", "ifrs-full_Assets"),
    row("BS", "부채총계", "63000000000000", "ifrs-full_Liabilities"),
    row("BS", "자본총계", "7000000000000", "ifrs-full_Equity"),
    row("CIS", "1. 이자수익", "2456860000000", "ifrs-full_RevenueFromInterest"),
    row("CIS", "1. 이자비용", "1138216000000", "ifrs-full_InterestExpense"),
    row("CIS", "2. 수수료수익", "310459000000", "ifrs-full_FeeAndCommissionIncome"),
    row("CIS", "당기순이익", "450000000000", "ifrs-full_ProfitLoss"),
]


def test_net_interest_derived_from_income_and_expense_rows():
    fin = summarize_key_financials(KAKAOBANK, "2025", sector="financial")["financial_accounts"]
    nii = fin["net_interest_income"]
    assert nii["values"]["2025"] == 2456860000000 - 1138216000000
    assert nii["derived"] is True and "이자수익" in nii["formula"] and "이자비용" in nii["formula"]
    # 수수료비용 행이 없으면 순수수료이익은 null(계산하지 않음)
    fee = fin["net_fee_income"]
    assert fee["values"]["2025"] is None and fee["matched"] is None and not fee.get("derived")
    # 소계 행이 있으면 그 행을 쓰고 derived는 없다
    bank = summarize_key_financials(BANK, "2025", sector="financial")["financial_accounts"]
    assert bank["net_interest_income"]["values"]["2025"] == 13073093000000 and not bank["net_interest_income"].get("derived")


# 삼성화재(보험, KSIC 65) 2025: 이자수익−이자비용은 투자손익의 일부라 순이자이익이 아니다 (v1.6.3)
INSURER = [
    row("BS", "자산총계", "90000000000000", "ifrs-full_Assets"),
    row("BS", "부채총계", "70000000000000", "ifrs-full_Liabilities"),
    row("BS", "자본총계", "20000000000000", "ifrs-full_Equity"),
    row("CIS", "보험수익", "18639982044735", "ifrs-full_InsuranceRevenue"),
    row("CIS", "보험손익", "1483034088528", "ifrs-full_InsuranceServiceResult"),
    row("CIS", "투자손익", "1176108913616", "dart_InvestmentIncomeExpenses"),
    row("CIS", "이자수익", "2371311653539", "ifrs-full_RevenueFromInterest"),
    row("CIS", "이자비용", "599010152085", "ifrs-full_InterestExpense"),
    row("CIS", "당기순이익", "2000000000000", "ifrs-full_ProfitLoss"),
]


def test_insurer_separates_interest_and_uses_insurance_accounts():
    assert detect_sector("65110", INSURER)["subsector"] == "insurance"
    assert detect_sector("64110", BANK).get("subsector") == "bank"
    out = summarize_key_financials(INSURER, "2025", sector="financial", subsector="insurance")
    fin = out["financial_accounts"]
    assert fin["net_interest_income"]["values"]["2025"] is None and "보험손익" in fin["net_interest_income"]["note"]
    assert fin["interest_net_investment"]["values"]["2025"] == 2371311653539 - 599010152085
    assert fin["interest_net_investment"]["derived"] is True
    assert fin["insurance_service_result"]["values"]["2025"] == 1483034088528
    assert fin["investment_result"]["values"]["2025"] == 1176108913616
    assert "net_interest_income" not in out["financial_missing"]
    # 은행은 그대로(보험 계정 없음)
    bank = summarize_key_financials(KAKAOBANK, "2025", sector="financial", subsector="bank")["financial_accounts"]
    assert bank["net_interest_income"]["derived"] is True and "interest_net_investment" not in bank
