import json
from datetime import date, timedelta

import pytest

from dart_mcp import krx


def make_cache(tmp_path, market, rows_by_day):
    for ymd, rows in rows_by_day.items():
        p = tmp_path / market / f"{ymd}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def row(code, close, vol, name="가나다", shares=1000):
    return {"ISU_CD": code, "ISU_NM": name, "TDD_CLSPRC": str(close), "ACC_TRDVOL": f"{vol:,}",
            "ACC_TRDVAL": str(close * vol), "MKTCAP": str(close * shares), "LIST_SHRS": str(shares)}


@pytest.fixture
def client(tmp_path):
    days = {}
    d = date(2024, 2, 1)
    i = 0
    while d <= date(2024, 3, 14):
        if d.weekday() < 5:
            days[d.strftime("%Y%m%d")] = [row("111111", 1000 + i * 10, 100 + i), row("KR7222222001", 500, 10, "라마바")]
            i += 1
        d += timedelta(days=1)
    make_cache(tmp_path, "KOSDAQ", days)
    return krx.KrxClient(cache_dir=tmp_path, offline=True), days


def test_month_back():
    assert krx.month_back(date(2024, 3, 31)) == date(2024, 2, 29)
    assert krx.month_back(date(2024, 1, 15)) == date(2023, 12, 15)


def test_base_price_matches_hand_calc(client):
    c, days = client
    r = krx.base_price(c, "111111", "20240314", "KOSDAQ")
    assert r["month"]["from"] == "20240215" and r["week"]["from"] == "20240308"
    def vw(lo):
        rs = [v[0] for k, v in days.items() if lo <= k <= "20240314"]
        return sum(float(x["TDD_CLSPRC"]) * float(x["ACC_TRDVOL"].replace(",", "")) for x in rs) / sum(float(x["ACC_TRDVOL"].replace(",", "")) for x in rs)
    exp = (vw("20240215") + vw("20240308") + float(days["20240314"][0]["TDD_CLSPRC"])) / 3
    assert r["base_price"] == pytest.approx(exp)
    assert r["week"]["days"] == 5 and r["api_calls"] == 0 and not r["warnings"]


def test_check_status_and_band(client):
    c, _ = client
    r = krx.base_price(c, "111111", "20240314", "KOSDAQ")
    bp = r["base_price"]
    assert krx.check_base_price(r, disclosed=r["base_price_floor"])["status"] == "일치"
    assert krx.check_base_price(r, disclosed=bp * 1.02)["status"] == "불일치"
    assert krx.check_base_price(r, merger_price=bp * 0.75)["within_band"] is True
    assert krx.check_base_price(r, merger_price=bp * 0.75, affiliated=True)["within_band"] is False


def test_round_half_up_and_rounding_label(client):
    assert krx.round_half_up(80582.64) == 80583 and krx.round_half_up(2112.5) == 2113 and krx.round_half_up(5331.49) == 5331
    c, _ = client
    r = krx.base_price(c, "111111", "20240314", "KOSDAQ")
    assert krx.check_base_price(r, disclosed=r["base_price_rounded"])["rounding"] == "반올림"
    if r["base_price_floor"] != r["base_price_rounded"]:
        assert krx.check_base_price(r, disclosed=r["base_price_floor"])["rounding"] == "절사"


def test_market_check_entry_validates_and_regime_skips_band(client):
    from dart_mcp.valuation import validate_case
    from tests.test_valuation import MIN_CASE

    c, _ = client
    r = krx.base_price(c, "111111", "20240314", "KOSDAQ")
    chk = krx.check_base_price(r, disclosed=r["base_price_rounded"], merger_price=r["base_price"] * 0.75, affiliated=True)
    e = krx.market_check_entry(r, chk, "가나다(주)", "기준시가", True, "20240101000001 §5 @100")
    assert e["within_band"] is False and e["band_pct"] == 10.0 and e["status"] == "일치" and e["disclosed_cite"].endswith("@100")
    chk2 = krx.check_base_price(r, disclosed=r["base_price_rounded"], merger_price=r["base_price"] * 0.75, band=False)
    assert "within_band" not in chk2
    e2 = krx.market_check_entry(r, chk2, None, "공정가액(2026.12.9 개정)")
    assert e2["within_band"] is None and e2["adjust_pct"] is None and e2["recomputed"] == r["base_price_rounded"]
    case = {**MIN_CASE, "market_check": {"base_price": [e, e2]}}
    assert validate_case(case) == []
    assert validate_case({**MIN_CASE, "market_check": None}) == []


def test_isin_match_and_market_autodetect(client):
    c, _ = client
    rows = krx.mktcap(c, ["222222"], "20240314")
    assert rows[0]["market"] == "KOSDAQ" and rows[0]["mktcap"] == 500 * 1000


def test_holiday_uses_previous_trading_day(client):
    c, _ = client
    r = krx.mktcap(c, ["111111"], "20240310", "KOSDAQ")[0]  # 일요일
    assert r["date"] == "20240308" and "직전 거래일" in r["note"]
    b = krx.base_price(c, "111111", "20240310", "KOSDAQ")
    assert any("최근일 종가" in w for w in b["warnings"])


def test_zero_volume_warning(tmp_path):
    days = {f"202403{d:02d}": [row("333333", 100, 0 if d == 12 else 10)] for d in (11, 12, 13, 14)}
    make_cache(tmp_path, "KOSPI", days)
    r = krx.base_price(krx.KrxClient(cache_dir=tmp_path, offline=True), "333333", "20240314", "KOSPI", month_start="20240311", week_start="20240311")
    assert r["base_price"] == pytest.approx(100) and any("거래량 0" in w for w in r["warnings"])


def test_offline_missing_and_cli(client, capsys, monkeypatch):
    monkeypatch.delenv("KRX_API_KEY", raising=False)  # 다른 테스트가 .env를 읽어 둔 경우 실제 호출을 막는다
    c, _ = client
    with pytest.raises(krx.KrxError):
        c.day("KOSPI", date(2024, 3, 14))
    with pytest.raises(krx.KrxError):
        krx.KrxClient(cache_dir=c.cache_dir, api_key="").day("KOSPI", date(2024, 3, 14))
