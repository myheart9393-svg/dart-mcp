"""KRX Open API 일별매매정보 클라이언트 + 기준주가 재계산·시가총액 조회.

- 하루 = 호출 1번(그 시장의 전 종목). 응답을 `data/krx/<시장>/<YYYYMMDD>.json`에 통째로 저장하므로
  한 번 받은 날짜는 어느 회사를 조회해도 다시 호출하지 않는다.
- 가격은 수정 전 원래 가격이다. 기준주가(자본시장법 시행령 제176조의5) 산식은 원래 가격 기준이라 그대로 쓴다.
- 출처 표기: (KRX Open API, 일별매매정보, <기준일>)

사용:
  python -m dart_mcp.krx base-price --code 005930 --date 20240314 [--disclosed 72345] [--merger-price 70000] [--affiliated]
         [--regime 기준시가] [--company 이름] [--json]   # --json이면 market_check_entry(사례 JSON 원소)도 출력
  (실제 응답으로 확인: 2024-11 KOSPI 959종목, 필드 ISU_CD(6자리)·TDD_CLSPRC·ACC_TRDVOL·MKTCAP·LIST_SHRS, 키 OutBlock_1)
  python -m dart_mcp.krx mktcap --codes 005930,000660 --date 20240314
  python -m dart_mcp.krx fetch --from 20240201 --to 20240314 --market KOSPI
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
ENDPOINTS = {"KOSPI": "sto/stk_bydd_trd", "KOSDAQ": "sto/ksq_bydd_trd", "KONEX": "sto/knx_bydd_trd"}
CACHE_DIR = Path(os.environ.get("KRX_CACHE_DIR", "data/krx"))
SOURCE = "KRX Open API, 일별매매정보"


class KrxError(RuntimeError):
    pass


def _d(s: str | date) -> date:
    return s if isinstance(s, date) else datetime.strptime(str(s).replace("-", ""), "%Y%m%d").date()


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def month_back(d: date) -> date:
    """d의 한 달 전 같은 날(없는 날이면 그 달 말일)."""
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


class KrxClient:
    def __init__(self, api_key: str | None = None, cache_dir: Path | None = None, offline: bool = False, sleep: float = 0.2):
        self.api_key = api_key or os.environ.get("KRX_API_KEY", "")
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.offline = offline
        self.sleep = sleep
        self.calls = 0

    def _path(self, market: str, ymd: str) -> Path:
        return self.cache_dir / market / f"{ymd}.json"

    def day(self, market: str, d: date) -> list[dict]:
        """그 날 그 시장의 전 종목 행. 휴장일은 빈 목록."""
        market = market.upper()
        if market not in ENDPOINTS:
            raise KrxError(f"market은 {list(ENDPOINTS)} 중 하나: {market}")
        ymd = _ymd(d)
        p = self._path(market, ymd)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        if d.weekday() >= 5:
            return []
        if self.offline:
            raise KrxError(f"캐시에 없음(offline): {market} {ymd}")
        if not self.api_key:
            raise KrxError("KRX_API_KEY가 없습니다(.env 또는 환경변수).")
        import httpx

        last = None
        for i in range(3):
            try:
                r = httpx.get(f"{BASE_URL}/{ENDPOINTS[market]}", params={"basDd": ymd}, headers={"AUTH_KEY": self.api_key}, timeout=30.0)
                self.calls += 1
                if r.status_code in (401, 403):
                    raise KrxError(f"KRX 인증 실패({r.status_code}). 키와 해당 서비스 이용 승인 여부를 확인하세요: {ENDPOINTS[market]}")
                r.raise_for_status()
                rows = r.json().get("OutBlock_1", [])
                break
            except KrxError:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.0 * (i + 1))
        else:
            raise KrxError(f"KRX 호출 실패 {market} {ymd}: {last}")
        # 지난 날짜만 저장(당일은 장중·집계 전일 수 있다)
        if d < date.today():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        time.sleep(self.sleep)
        return rows

    @staticmethod
    def _match(row: dict, code: str) -> bool:
        isu = str(row.get("ISU_CD", "")).strip()
        return isu == code or (len(isu) == 12 and isu[3:9] == code) or str(row.get("ISU_SRT_CD", "")).strip() == code

    def find_market(self, code: str, d: date) -> str:
        for back in range(0, 10):
            dd = d - timedelta(days=back)
            for m in ENDPOINTS:
                try:
                    rows = self.day(m, dd)
                except KrxError:
                    if self.offline:
                        continue  # 캐시에 없는 시장·날짜는 건너뛴다
                    raise
                if any(self._match(r, code) for r in rows):
                    return m
        raise KrxError(f"{code}: {_ymd(d)} 직전 10일 안에 어느 시장에서도 찾지 못했습니다(비상장·상장 전·코드 오류).")

    def series(self, code: str, start: date, end: date, market: str | None = None) -> list[dict]:
        """[start, end] 거래일별 {date, close, volume, value, mktcap, shares, name}."""
        market = (market or self.find_market(code, end)).upper()
        out = []
        d = start
        while d <= end:
            for r in self.day(market, d):
                if self._match(r, code):
                    out.append({
                        "date": _ymd(d), "close": _num(r.get("TDD_CLSPRC")), "volume": _num(r.get("ACC_TRDVOL")),
                        "value": _num(r.get("ACC_TRDVAL")), "mktcap": _num(r.get("MKTCAP")), "shares": _num(r.get("LIST_SHRS")),
                        "name": r.get("ISU_NM"), "market": market,
                    })
                    break
            d += timedelta(days=1)
        return out


def round_half_up(x: float | None) -> int | None:
    """원 미만 반올림(사사오입). 공시 3건(2024 DN오토모티브·한국정보인증, 2023 KB제22호스팩)이 모두 반올림이었다."""
    if x is None:
        return None
    return int(Decimal(repr(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def vwap_close(rows: list[dict]) -> float | None:
    """거래량 가중산술평균종가 = Σ(종가×거래량)/Σ거래량."""
    vol = sum(r["volume"] or 0 for r in rows)
    if vol <= 0:
        return None
    return sum((r["close"] or 0) * (r["volume"] or 0) for r in rows) / vol


def base_price(client: KrxClient, code: str, ref_date, market: str | None = None,
               month_start=None, week_start=None) -> dict:
    """시행령 제176조의5 제1항 제1호 기준주가: (1개월 가중평균 + 1주일 가중평균 + 최근일 종가) / 3.

    ref_date = 기산일(이사회 결의일과 합병계약 체결일 중 앞선 날의 전일).
    기간은 기산일 포함 소급: 1개월 = 한 달 전 다음 날부터, 1주일 = 6일 전부터. 공시의 기간과 다르면 month_start/week_start로 맞춘다.
    """
    ref = _d(ref_date)
    ms = _d(month_start) if month_start else month_back(ref) + timedelta(days=1)
    ws = _d(week_start) if week_start else ref - timedelta(days=6)
    rows = client.series(code, min(ms, ws), ref, market)
    warnings = []
    if not rows:
        raise KrxError(f"{code}: {_ymd(ms)}–{_ymd(ref)} 거래 자료가 없습니다.")
    mrows = [r for r in rows if r["date"] >= _ymd(ms)]
    wrows = [r for r in rows if r["date"] >= _ymd(ws)]
    last = rows[-1]
    if last["date"] != _ymd(ref):
        warnings.append(f"기산일 {_ymd(ref)}에 거래 자료가 없어 최근일 종가는 {last['date']} 값입니다(휴장일·거래정지 여부 확인).")
    zero = [r["date"] for r in mrows if not r["volume"]]
    if zero:
        warnings.append(f"거래량 0인 날 {len(zero)}일({zero[0]} 등): 거래정지 기간이면 법정 산식 적용이 달라질 수 있습니다.")
    if len(mrows) < 15:
        warnings.append(f"1개월 구간 거래일이 {len(mrows)}일뿐입니다(상장 직후이거나 거래정지).")
    m, w, c = vwap_close(mrows), vwap_close(wrows), last["close"]
    parts = [x for x in (m, w, c) if x is not None]
    if len(parts) < 3:
        warnings.append("세 값 중 계산할 수 없는 값이 있어 기준주가를 내지 않습니다.")
    bp = sum(parts) / 3 if len(parts) == 3 else None
    return {
        "code": code, "name": last["name"], "market": last["market"], "ref_date": _ymd(ref),
        "month": {"from": _ymd(ms), "to": _ymd(ref), "days": len(mrows), "vwap": m},
        "week": {"from": _ymd(ws), "to": _ymd(ref), "days": len(wrows), "vwap": w},
        "latest": {"date": last["date"], "close": c},
        "base_price": bp, "base_price_rounded": round_half_up(bp),
        "base_price_floor": math.floor(bp) if bp is not None else None,
        "price_basis": "수정 전 원래 가격", "source": f"({SOURCE}, {_ymd(ms)}–{_ymd(ref)})",
        "warnings": warnings, "api_calls": client.calls,
    }


def check_base_price(result: dict, disclosed: float | None = None, merger_price: float | None = None,
                     affiliated: bool = False, tol: float = 1.0, band: bool = True) -> dict:
    """공시 기준주가·합병가액과 대조.

    공시값이 원 미만 반올림값이나 절사값과 같으면 "일치"(rounding에 어느 쪽인지), 그 밖에 차이 tol원 이하도 "일치"(rounding="오차").
    band=False(기준시가 산식 의무 대상이 아닌 거래)면 할인·할증 한도 판정을 하지 않는다.
    """
    out = {}
    bp = result.get("base_price")
    if bp is None:
        return {"status": "계산 불가"}
    if disclosed is not None:
        diff = disclosed - bp
        out["disclosed"] = disclosed
        out["diff"] = diff
        out["diff_pct"] = diff / bp * 100
        if disclosed == result.get("base_price_rounded"):
            out["status"], out["rounding"] = "일치", "반올림"
        elif disclosed == math.floor(bp):
            out["status"], out["rounding"] = "일치", "절사"
        elif abs(diff) <= tol:
            out["status"], out["rounding"] = "일치", "오차"
        else:
            out["status"], out["rounding"] = "불일치", None
    if merger_price is not None and band:
        base = disclosed if disclosed is not None else bp
        adj = (merger_price / base - 1) * 100
        band = 10.0 if affiliated else 30.0
        out["merger_price"] = merger_price
        out["adjust_pct"] = adj
        out["band_pct"] = band
        out["band_basis"] = "계열회사 간 ±10%" if affiliated else "±30%"
        out["within_band"] = abs(adj) <= band + 1e-9
    elif merger_price is not None:
        out["merger_price"] = merger_price
        out["band_basis"] = "한도 판정 안 함(기준시가 산식 의무 대상 아님)"
    return out


BAND_REGIMES = ("기준시가",)


def market_check_entry(result: dict, chk: dict, company: str | None = None, regime: str | None = "기준시가",
                       affiliated: bool | None = None) -> dict:
    """사례 JSON market_check.base_price[] 원소. regime이 기준시가가 아니면 한도 칸은 null(재계산값만 기록)."""
    banded = regime in BAND_REGIMES
    return {
        "company": company or result.get("name"), "stock_code": result["code"], "ref_date": result["ref_date"],
        "recomputed": result.get("base_price_rounded"), "recomputed_raw": result.get("base_price"),
        "disclosed": chk.get("disclosed"),
        "diff_pct": round(chk["diff_pct"], 4) if chk.get("diff_pct") is not None else None,
        "status": chk.get("status") if chk.get("disclosed") is not None else ("계산 불가" if result.get("base_price") is None else "공시값 없음"),
        "rounding": chk.get("rounding"),
        "merger_price": chk.get("merger_price"),
        "adjust_pct": round(chk["adjust_pct"], 4) if banded and chk.get("adjust_pct") is not None else None,
        "band_pct": chk.get("band_pct") if banded else None,
        "within_band": chk.get("within_band") if banded else None,
        "affiliated": affiliated,
        "regime": regime,
        "warnings": result.get("warnings") or [],
        "source": result.get("source"),
    }


def latest_row(client: KrxClient, code: str, ref: date, market: str | None = None, max_back: int = 10) -> dict | None:
    """ref부터 하루씩 거슬러 처음 거래 자료가 있는 날의 행(휴장일이면 직전 거래일)."""
    market = (market or client.find_market(code, ref)).upper()
    for back in range(max_back):
        rows = client.series(code, ref - timedelta(days=back), ref - timedelta(days=back), market)
        if rows:
            return rows[0]
    return None


def mktcap(client: KrxClient, codes: list[str], d, market: str | None = None) -> list[dict]:
    """기준일(휴장일이면 직전 거래일)의 종가·상장주식수·시가총액."""
    ref = _d(d)
    out = []
    for code in codes:
        try:
            r = latest_row(client, code, ref, market)
        except KrxError as e:
            out.append({"code": code, "error": str(e)})
            continue
        if r is None:
            out.append({"code": code, "error": "거래 자료 없음"})
            continue
        out.append({"code": code, "name": r["name"], "market": r["market"], "date": r["date"], "close": r["close"],
                    "shares": r["shares"], "mktcap": r["mktcap"], "unit": "원",
                    "note": None if r["date"] == _ymd(ref) else f"기준일 {_ymd(ref)} 휴장: 직전 거래일 값",
                    "source": f"({SOURCE}, {r['date']})"})
    return out


def _fmt(x, nd=0):
    return "-" if x is None else f"{x:,.{nd}f}"


def _print_base(r: dict, chk: dict) -> None:
    print(f"{r['name']} ({r['code']}, {r['market']}) 기준주가 재계산 — 기산일 {r['ref_date']}")
    print(f"  1개월 가중평균종가 ({r['month']['from']}–{r['month']['to']}, {r['month']['days']}거래일): {_fmt(r['month']['vwap'], 2)}")
    print(f"  1주일 가중평균종가 ({r['week']['from']}–{r['week']['to']}, {r['week']['days']}거래일): {_fmt(r['week']['vwap'], 2)}")
    print(f"  최근일 종가 ({r['latest']['date']}): {_fmt(r['latest']['close'])}")
    print(f"  기준주가(산술평균): {_fmt(r['base_price'], 2)}  (원 미만 반올림 {_fmt(r['base_price_rounded'])} · 절사 {_fmt(r['base_price_floor'])})")
    if "disclosed" in chk:
        how = f"({chk['rounding']})" if chk.get("rounding") else ""
        print(f"  공시 기준주가 {_fmt(chk['disclosed'])} → 차이 {chk['diff']:+,.2f}원 ({chk['diff_pct']:+.3f}%) : {chk['status']}{how}")
    if "within_band" in chk:
        print(f"  합병가액 {_fmt(chk['merger_price'])} → 할인·할증 {chk['adjust_pct']:+.2f}% / 한도 {chk['band_basis']} : {'범위 안' if chk['within_band'] else '범위 밖'}")
    elif "merger_price" in chk:
        print(f"  합병가액 {_fmt(chk['merger_price'])} : {chk['band_basis']}")
    for w in r["warnings"]:
        print(f"  경고: {w}")
    print(f"  출처: {r['source']} · {r['price_basis']} · API 호출 {r['api_calls']}회")


def main(argv=None) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(prog="dart_mcp.krx", description="KRX 일별 시세: 기준주가 재계산, 시가총액 조회")
    ap.add_argument("--offline", action="store_true", help="캐시만 사용")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    # 서브커맨드 뒤에 써도 되게(값이 없으면 앞의 전역 값을 덮지 않는다)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--offline", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("base-price", parents=[common], help="시행령 제176조의5 기준주가 재계산")
    b.add_argument("--code", required=True)
    b.add_argument("--date", required=True, help="기산일 YYYYMMDD")
    b.add_argument("--market")
    b.add_argument("--month-start")
    b.add_argument("--week-start")
    b.add_argument("--disclosed", type=float, help="공시된 기준주가")
    b.add_argument("--merger-price", type=float, help="합병가액(할인·할증 적용 후)")
    b.add_argument("--affiliated", action="store_true", help="계열회사 간 합병(한도 10퍼센트)")
    b.add_argument("--regime", default="기준시가", help="deal.regime. 기준시가가 아니면 한도 판정 안 함(재계산값만)")
    b.add_argument("--company", help="market_check 원소의 회사명(생략하면 KRX 종목명)")
    m = sub.add_parser("mktcap", parents=[common], help="기준일 종가·상장주식수·시가총액")
    m.add_argument("--codes", required=True, help="쉼표로 구분한 종목코드")
    m.add_argument("--date", required=True)
    m.add_argument("--market")
    f = sub.add_parser("fetch", parents=[common], help="기간의 시장 전체 시세를 캐시에 미리 받기")
    f.add_argument("--from", dest="start", required=True)
    f.add_argument("--to", dest="end", required=True)
    f.add_argument("--market", required=True)
    a = ap.parse_args(argv)
    c = KrxClient(offline=a.offline)
    try:
        if a.cmd == "base-price":
            r = base_price(c, a.code, a.date, a.market, a.month_start, a.week_start)
            chk = check_base_price(r, a.disclosed, a.merger_price, a.affiliated, band=a.regime in BAND_REGIMES)
            if a.json:
                entry = market_check_entry(r, chk, a.company, a.regime, a.affiliated)
                print(json.dumps({**r, "check": chk, "market_check_entry": entry}, ensure_ascii=False, indent=1))
            else:
                _print_base(r, chk)
            return 1 if chk.get("status") == "불일치" or chk.get("within_band") is False else 0
        if a.cmd == "mktcap":
            rows = mktcap(c, [x.strip() for x in a.codes.split(",") if x.strip()], a.date, a.market)
            if a.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
            else:
                for r in rows:
                    if "error" in r:
                        print(f"{r['code']}: {r['error']}")
                    else:
                        print(f"{r['name']} ({r['code']}, {r['market']}) {r['date']} 종가 {_fmt(r['close'])}원 · 상장주식수 {_fmt(r['shares'])}주 · 시가총액 {_fmt(r['mktcap'])}원" + (f" · {r['note']}" if r["note"] else ""))
            return 0
        if a.cmd == "fetch":
            d, e, n = _d(a.start), _d(a.end), 0
            while d <= e:
                n += 1 if c.day(a.market, d) else 0
                d += timedelta(days=1)
            print(f"{a.market} {a.start}–{a.end}: 거래일 {n}일, API 호출 {c.calls}회")
            return 0
    except KrxError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
