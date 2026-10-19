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
    assert r["debt_ratio"]["values"] == {"2024": 66.67, "2023": 50.0, "2022": 0.0}  # '-' = 0
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


# --------------------------------------------------------------------------- 회계 리뷰 반영
def bs_pl(equity, net_income, parent=None, assets=("1000", "1000", "1000"), liabilities=("500", "500", "500")):
    """BS·IS 최소 세트. equity/net_income/parent의 값은 (당기, 전기, 전전기) 문자열 튜플."""
    def r3(sj, nm, aid, vals, ord_=1):
        return row(sj, nm, vals[0], account_id=aid, ord_=ord_, frmtrm=vals[1], bfefrmtrm=vals[2])
    items = [
        r3("BS", "자산총계", "ifrs-full_Assets", assets),
        r3("BS", "부채총계", "ifrs-full_Liabilities", liabilities),
        r3("BS", "자본총계", "ifrs-full_Equity", equity),
        r3("IS", "당기순이익", "ifrs-full_ProfitLoss", net_income),
    ]
    if parent:
        items += [r3("BS", "지배기업 소유주지분", "-표준계정코드 미사용-", parent["equity"], ord_=2),
                  r3("IS", "지배기업소유주지분", "-표준계정코드 미사용-", parent["net_income"], ord_=2)]
    return items


def test_roe_uses_parent_accounts_and_average_equity():
    items = bs_pl(equity=("1200", "1000", "800"), net_income=("220", "110", "90"),
                  parent={"equity": ("1100", "900", "700"), "net_income": ("200", "100", "80")})
    out = summarize_key_financials(items, "2024")
    roe = out["ratios"]["roe"]
    # 2024: 200 / ((900+1100)/2) = 20.0, 2023: 100 / ((700+900)/2) = 12.5, 2022: 80/700 (기말 기준)
    assert roe["values"] == {"2024": 20.0, "2023": 12.5, "2022": 11.43}
    assert roe["denominator_basis"] == {"2024": "average", "2023": "average", "2022": "ending"}
    assert "지배주주 기준" in roe["formula"] and "전전기(2022)는 기말 기준" in roe["formula"]
    assert out["accounts"]["net_income_parent"]["matched"]["by"] == "name_exact"
    assert out["optional_missing"] == [] and "equity_parent" not in out["missing"]


def test_roe_falls_back_to_total_when_parent_missing():
    items = bs_pl(equity=("1200", "1000", "800"), net_income=("220", "110", "90"))
    out = summarize_key_financials(items, "2024", fs_div="OFS")
    roe = out["ratios"]["roe"]
    assert roe["values"]["2024"] == 20.0  # 220 / 1100
    assert roe["basis"] == "별도 재무제표 기준"
    assert set(out["optional_missing"]) == {"net_income_parent", "equity_parent"}
    assert not set(out["optional_missing"]) & set(out["missing"])
    assert "연결 총액 기준" in summarize_key_financials(items, "2024")["ratios"]["roe"]["formula"]


def test_capital_impairment_flag_nulls_equity_ratios():
    items = bs_pl(equity=("-200", "100", "300"), net_income=("-300", "-200", "10"),
                  liabilities=("1200", "900", "700"))
    out = summarize_key_financials(items, "2024")
    assert out["flags"] == ["capital_impairment"]
    assert "자본잠식(자본총계 음수): 2024" in out["note"]
    r = out["ratios"]
    assert r["debt_ratio"]["values"] == {"2024": None, "2023": 900.0, "2022": 233.33}
    assert r["equity_ratio"]["values"]["2024"] is None and r["equity_ratio"]["values"]["2023"] == 10.0
    assert r["roe"]["values"]["2024"] is None  # 기초 100, 기말 -200 → 계산 안 함
    assert r["roa"]["values"]["2024"] == -30.0  # 자산이 분모라 그대로
    clean = summarize_key_financials(bs_pl(("1", "1", "1"), ("1", "1", "1")), "2024")
    assert clean["flags"] == [] and "note" not in clean


def test_fin_cache_expires_after_90_days_and_logs_changes(tmp_path, caplog):
    version = {"amount": "100"}

    class FakeClient:
        def get_financial_statements(self, *args):
            return {"status": "000", "message": "정상",
                    "list": [row("BS", "자산총계", version["amount"], account_id="ifrs-full_Assets")]}

    load_statements(FakeClient, "00000001", "2024", "11011", "CFS", tmp_path)
    path = tmp_path / "fin" / "00000001_2024_11011_CFS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] -= 89 * 86400
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_statements(lambda: pytest.fail("fresh cache"), "00000001", "2024", "11011", "CFS", tmp_path)["cached"]

    payload["fetched_at"] -= 2 * 86400  # 91일
    path.write_text(json.dumps(payload), encoding="utf-8")
    version["amount"] = "120"  # 정정공시로 숫자가 바뀜
    with caplog.at_level("WARNING", logger="dart_mcp.financials"):
        got = load_statements(FakeClient, "00000001", "2024", "11011", "CFS", tmp_path)
    assert got["cached"] is False and got["changed_accounts"] == 1
    assert "1개 계정이 캐시와 다름" in caplog.text
    assert load_statements(FakeClient, "00000001", "2024", "11011", "CFS", tmp_path, refresh=True)["changed_accounts"] == 0

    def no_key():
        raise RuntimeError("DART_API_KEY 없음")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] -= 100 * 86400
    path.write_text(json.dumps(payload), encoding="utf-8")
    stale = load_statements(no_key, "00000001", "2024", "11011", "CFS", tmp_path)
    assert stale["stale"] is True and stale["list"][0]["thstrm_amount"] == "120"


def test_period_labels_note_non_december_and_short_period():
    items = bs_pl(("1", "1", "1"), ("1", "1", "1"))
    for it in items:
        it.update(thstrm_nm="제 30 기", frmtrm_nm="제 29 기", bfefrmtrm_nm="제 28 기")
    out = summarize_key_financials(items, "2024", acc_mt="03")
    assert out["periods"][0] == {"year": "2024", "name": "제30기", "range": "2023.04.01~2024.03.31",
                                 "range_source": "acc_mt(결산월로 추정, 12개월 여부는 API로 확인 불가)"}
    assert out["periods"][2]["range"] == "2021.04.01~2022.03.31"
    assert "3월 결산" in out["note"]
    assert "note" not in summarize_key_financials(items, "2024", acc_mt="12")

    items[3]["thstrm_dt"] = "2024.04.01 ~ 2024.12.31"  # 결산기 변경으로 9개월
    out = summarize_key_financials(items, "2024", acc_mt="12")
    assert out["periods"][0]["range"] == "2024.04.01~2024.12.31"
    assert "9개월" in out["note"]
    assert out["accounts"]["net_income"]["matched"]["thstrm_dt"] == "2024.04.01 ~ 2024.12.31"


def test_parse_amount_dash_is_zero_but_empty_is_none():
    assert parse_amount("-") == 0
    assert parse_amount(" - ") == 0
    assert parse_amount("") is None and parse_amount(None) is None
    assert parse_amount("-1,234") == -1234
