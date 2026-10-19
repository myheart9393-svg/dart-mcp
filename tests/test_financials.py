import json

import pytest

from dart_mcp.financials import (
    KEY_ACCOUNTS,
    load_statements,
    match_account,
    parse_amount,
    summarize_key_financials,
)

SPEC = {a.key: a for a in KEY_ACCOUNTS}


def row(sj_div, account_nm, thstrm, account_id="-표준계정코드 미사용-", ord_=1, frmtrm="", bfefrmtrm=""):
    return {
        "sj_div": sj_div, "account_nm": account_nm, "account_id": account_id, "ord": str(ord_),
        "thstrm_amount": thstrm, "frmtrm_amount": frmtrm, "bfefrmtrm_amount": bfefrmtrm,
    }


@pytest.mark.parametrize(
    "key, variants",
    [
        # (1) 표준 account_id, (2) 계정명 완전일치 변형, (3) 계정명 부분일치 변형
        ("revenue", [
            [row("IS", "아무이름", "100", account_id="ifrs-full_Revenue")],
            [row("CIS", "수익(매출액)", "100")],
            [row("IS", "Ⅰ. 매출액 합계", "100")],
        ]),
        ("operating_income", [
            [row("IS", "영업이익", "100", account_id="dart_OperatingIncomeLoss")],
            [row("CIS", "영업이익(손실)", "100")],
            [row("IS", " 영업 이익(손실) 합계", "100")],
        ]),
    ],
)
def test_name_variants_match_same_account(key, variants):
    noise = [
        row("IS", "매출원가", "-60", ord_=0),
        row("IS", "매출총이익", "40", ord_=0),
        row("IS", "영업외수익", "5", ord_=0),
    ]
    got = []
    for items in variants:
        hit, how = match_account(noise + items, SPEC[key])
        assert hit is not None, (key, items[0]["account_nm"])
        got.append((parse_amount(hit["thstrm_amount"]), how))
    assert [v for v, _ in got] == [100, 100, 100]
    assert [h for _, h in got] == ["account_id", "name_exact", "name_partial"]


def test_missing_accounts_listed_and_null():
    items = [
        row("BS", "자산총계", "1,000", account_id="ifrs-full_Assets", frmtrm="900", bfefrmtrm="800"),
        row("BS", "부채총계", "400", account_id="ifrs-full_Liabilities", frmtrm="300", bfefrmtrm="-"),
        row("BS", "자본총계", "600", account_id="ifrs-full_Equity", frmtrm="600", bfefrmtrm="500"),
        row("CIS", "매출액", "500", account_id="ifrs-full_Revenue"),
        row("CIS", "당기순이익(손실)", "-50"),
        # 영업이익·현금흐름표·현금 계정이 없다
    ]
    out = summarize_key_financials(items, "2024")
    assert out["years"] == ["2024", "2023", "2022"]
    assert set(out["missing"]) == {"operating_income", "operating_cf", "investing_cf", "capex", "cash"}
    assert out["accounts"]["operating_income"]["values"] == {"2024": None, "2023": None, "2022": None}
    assert out["accounts"]["operating_income"]["matched"] is None
    assert out["accounts"]["total_assets"]["values"] == {"2024": 1000, "2023": 900, "2022": 800}
    assert out["accounts"]["net_income"]["values"]["2024"] == -50
    r = out["ratios"]
    assert r["debt_ratio"]["values"] == {"2024": 66.67, "2023": 50.0, "2022": None}
    assert r["operating_margin"]["values"]["2024"] is None  # 분자 없음 → None
    assert r["net_margin"]["values"]["2024"] == -10.0


def test_load_statements_caches_and_skips_no_data(tmp_path):
    calls = []

    class FakeClient:
        def get_financial_statements(self, corp_code, bsns_year, reprt_code, fs_div):
            calls.append((corp_code, bsns_year, reprt_code, fs_div))
            if fs_div == "OFS":
                return {"status": "013", "message": "조회된 데이타가 없습니다."}
            return {"status": "000", "message": "정상", "list": [row("BS", "자산총계", "1", account_id="ifrs-full_Assets")]}

    a = load_statements(FakeClient, "00000001", "2024", "11011", "CFS", tmp_path)
    b = load_statements(lambda: pytest.fail("cache miss"), "00000001", "2024", "11011", "CFS", tmp_path)
    assert a["cached"] is False and b["cached"] is True and b["list"] == a["list"]
    saved = json.loads((tmp_path / "fin" / "00000001_2024_11011_CFS.json").read_text(encoding="utf-8"))
    assert saved["status"] == "000"

    c = load_statements(FakeClient, "00000001", "2024", "11011", "OFS", tmp_path)
    assert c["status"] == "013" and c["list"] == []
    assert not (tmp_path / "fin" / "00000001_2024_11011_OFS.json").exists()
    assert len(calls) == 2
