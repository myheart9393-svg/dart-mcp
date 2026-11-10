"""5개년 FCFF DCF 엔진 — 수집(DART 재무 API 캐시) · 계산 · CLI.

모델링 규칙 (docs/dcf.md):
  FCFF = EBIT × (1 − 법인세율) + 감가상각비 − CAPEX − 순운전자본 증가
  TV   = FCFF_N × (1 + g) / (WACC − g)          (g ≥ WACC면 ValueError)
  할인계수 = 1 / (1 + WACC)^(t − cf_timing_adj), TV는 (N − tv_timing_adj)  (기중 가정이면 둘 다 0.5)
  주주가치 = 기업가치 − 순차입금 + 비영업자산 − 비지배지분
  비용·CAPEX·순운전자본 증가는 양수로 두고 수식에서 차감한다.
  단위는 백만원. DART 원자료(원)는 collect_history에서 한 번만 환산한다.
  법인세율·WACC·성장률 등 모든 가정은 assumptions JSON에서 온다(코드 상수 없음).

CLI:
  uv run python -m dart_mcp.dcf build <assumptions.json> --out <파일.xlsx> [--verify]
    --verify: LibreOffice headless로 재계산한 값과 엔진 결과를 비교(불일치·soffice 없음이면 종료코드 1).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .financials import PERIODS, load_statements, normalize_name, parse_amount

FORECAST_YEARS = 5
HISTORY_YEARS = 6
WON_PER_MN = 1_000_000  # 수집 단계 환산에만 쓴다(원 → 백만원). 엑셀에서는 가정 시트 입력값을 쓴다.


# --------------------------------------------------------------------------- 수집
@dataclass(frozen=True)
class AccountSpec:
    key: str
    label: str
    sj_divs: tuple[str, ...]
    ids: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    contains: tuple[str, ...] = ()        # 이름에 이 문자열이 들어간 행을 모두 합산
    excludes: tuple[str, ...] = ()


INCOME = ("CIS", "IS")
SPECS: tuple[AccountSpec, ...] = (
    AccountSpec("revenue", "매출액", INCOME, ("ifrs-full_Revenue",), ("매출액", "수익(매출액)", "수익")),
    AccountSpec("ebit", "영업이익", INCOME, ("dart_OperatingIncomeLoss",), ("영업이익", "영업이익(손실)")),
    AccountSpec("ebt", "법인세비용차감전순이익", INCOME, ("ifrs-full_ProfitLossBeforeTax",),
                ("법인세비용차감전순이익(손실)", "법인세비용차감전순이익")),
    AccountSpec("tax", "법인세비용", INCOME, ("ifrs-full_IncomeTaxExpenseContinuingOperations",), ("법인세비용",)),
    AccountSpec("ni_parent", "지배주주 순이익", INCOME, ("ifrs-full_ProfitLossAttributableToOwnersOfParent",)),
    AccountSpec("dep", "유형자산 감가상각비", ("CF",), ("ifrs-full_AdjustmentsForDepreciationExpense",),
                ("감가상각비에 대한 조정", "감가상각비 조정", "감가상각비")),
    AccountSpec("dep_rou", "사용권자산 감가상각비", ("CF",), (), ("사용권자산감가상각비 조정", "사용권자산감가상각비")),
    AccountSpec("amort", "무형자산상각비", ("CF",), ("ifrs-full_AdjustmentsForAmortisationExpense",),
                ("무형자산상각비에 대한 조정", "무형자산상각비")),
    AccountSpec("dep_ip", "투자부동산 감가상각비", ("CF",), (), ("투자부동산감가상각비 조정", "투자부동산감가상각비")),
    AccountSpec("capex_ppe", "유형자산 취득", ("CF",),
                ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",), ("유형자산의 취득",)),
    AccountSpec("capex_int", "무형자산 취득", ("CF",),
                ("ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",), ("무형자산의 취득",)),
    AccountSpec("ar", "매출채권", ("BS",), ("ifrs-full_CurrentTradeReceivables", "ifrs-full_TradeAndOtherCurrentReceivables"),
                ("유동매출채권", "매출채권", "매출채권 및 기타유동채권")),
    AccountSpec("inventory", "재고자산", ("BS",), ("ifrs-full_Inventories",), ("유동재고자산", "재고자산")),
    AccountSpec("ap", "매입채무", ("BS",), ("ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers",),
                ("유동매입채무", "매입채무")),
    AccountSpec("cash", "현금및현금성자산", ("BS",), ("ifrs-full_CashAndCashEquivalents",)),
    AccountSpec("st_deposit", "단기금융예치금", ("BS",), (), ("단기금융예치금", "단기금융상품")),
    AccountSpec("lt_deposit", "장기금융예치금", ("BS",), (), ("장기금융예치금", "장기금융상품")),
    AccountSpec("fvpl_current", "유동 당기손익인식금융자산", ("BS",), (), ("유동 당기손익인식금융자산", "당기손익-공정가치 측정 금융자산")),
    AccountSpec("equity_method", "지분법적용 투자지분", ("BS",), ("ifrs-full_InvestmentsAccountedForUsingEquityMethod",),
                ("지분법적용 투자지분", "관계기업투자", "공동기업투자")),
    AccountSpec("inv_property", "투자부동산", ("BS",), ("ifrs-full_InvestmentProperty",)),
    AccountSpec("fvoci", "FVOCI 지분상품", ("BS",), (), ("기타포괄손익-공정가치 지정 비유동지분상품투자", "기타포괄손익-공정가치 측정 금융자산")),
    AccountSpec("borrowings", "차입금·사채(합산)", ("BS",), contains=("차입금", "사채"), excludes=("리스", "할인", "합계")),
    AccountSpec("lease", "리스부채(유동+비유동)", ("BS",), contains=("리스부채",)),
    AccountSpec("nci", "비지배지분", ("BS",), ("ifrs-full_NoncontrollingInterests",), ("비지배지분",)),
    AccountSpec("assets", "자산총계", ("BS",), ("ifrs-full_Assets",)),
    AccountSpec("liabilities", "부채총계", ("BS",), ("ifrs-full_Liabilities",)),
    AccountSpec("equity", "자본총계", ("BS",), ("ifrs-full_Equity",)),
)
SPEC_BY_KEY = {s.key: s for s in SPECS}
# 기준연도에 반드시 있어야 하는 계정(없으면 0으로 볼 수 있는 것은 제외)
REQUIRED_BASE = ("revenue", "ebit", "ar", "inventory", "ap", "cash", "assets", "liabilities", "equity")


@dataclass
class History:
    corp_code: str
    fs_div: str
    years: list[str]                                   # 오래된 순
    values: dict[str, dict[str, float | None]]         # key → {year: 백만원}
    sources: dict[str, str]                            # year → rcept_no
    matched: dict[str, dict[str, str]] = field(default_factory=dict)  # key → {year: 맞춘 계정명}

    def base(self, key: str) -> float:
        v = self.values[key][self.years[-1]]
        if v is None:
            raise ValueError(f"기준연도 {self.years[-1]} '{SPEC_BY_KEY[key].label}' 값이 없다")
        return v

    def base_or_zero(self, key: str) -> float:
        v = self.values[key][self.years[-1]]
        return 0.0 if v is None else v


def _pick(items: list[dict], spec: AccountSpec) -> tuple[list[dict], str | None]:
    rows = [it for it in items if it.get("sj_div") in spec.sj_divs]
    if spec.contains:
        hit = [it for it in rows
               if any(c in (it.get("account_nm") or "") for c in spec.contains)
               and not any(e in (it.get("account_nm") or "") for e in spec.excludes)]
        return hit, " + ".join(it.get("account_nm", "") for it in hit) or None
    for sj in spec.sj_divs:   # 손익은 CIS → IS 순서로
        for it in rows:
            if it.get("sj_div") == sj and it.get("account_id") in spec.ids:
                return [it], it.get("account_nm")
        wanted = {normalize_name(n) for n in spec.names}
        for it in rows:
            if it.get("sj_div") == sj and normalize_name(it.get("account_nm")) in wanted:
                return [it], it.get("account_nm")
    return [], None


def _extract(items: list[dict], years: list[str]) -> tuple[dict, dict]:
    """한 보고서(당기·전기·전전기)에서 계정별 값(원 → 백만원 환산 1회)."""
    values: dict[str, dict[str, float | None]] = {}
    matched: dict[str, dict[str, str]] = {}
    for spec in SPECS:
        rows, name = _pick(items, spec)
        values[spec.key] = {}
        for field_name, idx in PERIODS:
            if idx >= len(years):
                continue
            amounts = [parse_amount(r.get(field_name)) for r in rows]
            amounts = [a for a in amounts if a is not None]
            if spec.contains:  # 합산 계정: 행이 하나도 없으면 0(해당 부채 없음)
                values[spec.key][years[idx]] = sum(amounts) / WON_PER_MN
            else:
                values[spec.key][years[idx]] = amounts[0] / WON_PER_MN if amounts else None
            if name:
                matched.setdefault(spec.key, {})[years[idx]] = name
    return values, matched


def collect_history(corp_code: str, bsns_year: int, fs_div: str = "CFS", data_dir: Path | None = None,
                    client_factory=None) -> History:
    """기준 사업연도와 3년 전 사업보고서(11011)로 6개년 계정을 모은다. 캐시(data/fin) 우선."""
    if client_factory is None:
        from .client import DartClient
        client_factory = DartClient
    years_all: list[str] = []
    values: dict[str, dict[str, float | None]] = {s.key: {} for s in SPECS}
    matched: dict[str, dict[str, str]] = {}
    sources: dict[str, str] = {}
    for report_year in (bsns_year - 3, bsns_year):   # 옛 보고서 먼저 → 새 보고서가 덮어씀
        data = load_statements(client_factory, corp_code, str(report_year), "11011", fs_div, data_dir)
        items = data.get("list") or []
        if not items:
            continue
        ys = [str(report_year - i) for i in range(3)]
        v, m = _extract(items, ys)
        for k in values:
            values[k].update(v[k])
        for k, d in m.items():
            matched.setdefault(k, {}).update(d)
        for y in ys:
            sources[y] = data.get("rcept_no") or ""
            if y not in years_all:
                years_all.append(y)
    years = sorted(years_all)[-HISTORY_YEARS:]
    if str(bsns_year) not in years:
        raise ValueError(f"{corp_code} {bsns_year} 사업보고서 재무제표가 없다")
    values = {k: {y: d.get(y) for y in years} for k, d in values.items()}
    hist = History(corp_code, fs_div, years, values, {y: sources[y] for y in years}, matched)
    for key in REQUIRED_BASE:
        hist.base(key)
    return hist


def history_to_json(h: History) -> dict:
    return {"corp_code": h.corp_code, "fs_div": h.fs_div, "years": h.years, "values": h.values,
            "sources": h.sources, "matched": h.matched}


def history_from_json(d: dict) -> History:
    return History(d["corp_code"], d["fs_div"], list(d["years"]), d["values"], d["sources"], d.get("matched", {}))


# --------------------------------------------------------------------------- 가정
FORECAST_KEYS = ("revenue_growth", "operating_margin", "tax_rate", "da_pct", "capex_pct", "nwc_pct")
DISCOUNT_KEYS = ("rf", "mrp", "beta", "crp", "kd", "debt_weight", "terminal_growth", "cf_timing_adj", "tv_timing_adj")


def load_assumptions(path: str | Path) -> dict:
    a = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_assumptions(a)
    return a


def validate_assumptions(a: dict) -> None:
    for k in ("company", "base_year", "valuation_date", "shares", "forecast", "discount", "sensitivity", "unit_krw_per_mn"):
        if k not in a:
            raise ValueError(f"assumptions: '{k}' 없음")
    for k in FORECAST_KEYS:
        vals = a["forecast"].get(k)
        if not isinstance(vals, list) or len(vals) != FORECAST_YEARS:
            raise ValueError(f"assumptions.forecast.{k}: {FORECAST_YEARS}개 값이 필요하다")
    for k in DISCOUNT_KEYS:
        if not isinstance(a["discount"].get(k), (int, float)):
            raise ValueError(f"assumptions.discount.{k}: 숫자가 필요하다")
    for k in ("wacc_step", "g_step"):
        if not isinstance(a["sensitivity"].get(k), (int, float)):
            raise ValueError(f"assumptions.sensitivity.{k}: 숫자가 필요하다")
    for k in ("issued", "treasury"):
        if not isinstance(a["shares"].get(k), int):
            raise ValueError(f"assumptions.shares.{k}: 정수가 필요하다")


# --------------------------------------------------------------------------- 계산
SENS_WACC_ROWS = 7   # 기준 WACC를 가운데 두고 위아래 3칸
SENS_G_COLS = 5      # 기준 g를 가운데 두고 좌우 2칸


def wacc_of(a: dict) -> dict:
    d = a["discount"]
    ke = d["rf"] + d["beta"] * d["mrp"] + d["crp"]
    kd_after = d["kd"] * (1 - a["forecast"]["tax_rate"][0])
    wacc = ke * (1 - d["debt_weight"]) + kd_after * d["debt_weight"]
    return {"ke": ke, "kd_after": kd_after, "wacc": wacc}


def bridge_items(h: History) -> dict:
    cash_like = sum(h.base_or_zero(k) for k in ("cash", "st_deposit", "lt_deposit", "fvpl_current"))
    debt = h.base_or_zero("borrowings") + h.base_or_zero("lease")
    nonop = sum(h.base_or_zero(k) for k in ("equity_method", "inv_property", "fvoci"))
    return {"cash_like": cash_like, "debt": debt, "net_debt": debt - cash_like, "nonop": nonop,
            "nci": h.base_or_zero("nci")}


def value_at(fcff: list[float], periods: list[float], tv_period: float, wacc: float, g: float, bridge: dict,
             shares: int, unit: float) -> dict:
    if g >= wacc:
        raise ValueError(f"영구성장률 g({g:.4%}) ≥ WACC({wacc:.4%}): Gordon 모형을 계산할 수 없다")
    df = [1 / (1 + wacc) ** p for p in periods]
    pv = [f * x for f, x in zip(fcff, df)]
    tv = fcff[-1] * (1 + g) / (wacc - g)
    df_tv = 1 / (1 + wacc) ** tv_period
    ev = sum(pv) + tv * df_tv
    equity = ev - bridge["net_debt"] + bridge["nonop"] - bridge["nci"]
    return {"df": df, "pv": pv, "tv": tv, "df_tv": df_tv, "pv_tv": tv * df_tv, "ev": ev, "equity": equity,
            "per_share": equity * unit / shares}


def compute(h: History, a: dict) -> dict:
    validate_assumptions(a)
    f, d = a["forecast"], a["discount"]
    n = FORECAST_YEARS
    rev, ebit, tax, nopat, da, capex, nwc, dnwc, fcff = ([] for _ in range(9))
    prev_rev = h.base("revenue")
    prev_nwc = h.base("ar") + h.base("inventory") - h.base("ap")
    for i in range(n):
        r = prev_rev * (1 + f["revenue_growth"][i])
        e = r * f["operating_margin"][i]
        t = e * f["tax_rate"][i]
        w = r * f["nwc_pct"][i]
        rev.append(r); ebit.append(e); tax.append(t); nopat.append(e - t)
        da.append(r * f["da_pct"][i]); capex.append(r * f["capex_pct"][i])
        nwc.append(w); dnwc.append(w - prev_nwc)
        fcff.append(e * (1 - f["tax_rate"][i]) + da[-1] - capex[-1] - dnwc[-1])
        prev_rev, prev_nwc = r, w
    rates = wacc_of(a)
    t_index = list(range(1, n + 1))
    periods = [t - d["cf_timing_adj"] for t in t_index]
    tv_period = n - d["tv_timing_adj"]
    bridge = bridge_items(h)
    shares = a["shares"]["issued"] - a["shares"]["treasury"]
    unit = a["unit_krw_per_mn"]
    val = value_at(fcff, periods, tv_period, rates["wacc"], d["terminal_growth"], bridge, shares, unit)

    w_step, g_step = a["sensitivity"]["wacc_step"], a["sensitivity"]["g_step"]
    wc, gc = SENS_WACC_ROWS // 2, SENS_G_COLS // 2
    sens_w = [rates["wacc"] + (i - wc) * w_step for i in range(SENS_WACC_ROWS)]
    sens_g = [d["terminal_growth"] + (j - gc) * g_step for j in range(SENS_G_COLS)]
    grid = []
    for w in sens_w:
        row = []
        for g in sens_g:
            row.append(None if g >= w else value_at(fcff, periods, tv_period, w, g, bridge, shares, unit)["per_share"])
        grid.append(row)

    base_ebitda = h.base("ebit") + sum(h.base_or_zero(k) for k in ("dep", "dep_rou", "amort", "dep_ip"))
    return {
        "revenue": rev, "ebit": ebit, "tax": tax, "nopat": nopat, "da": da, "capex": capex, "nwc": nwc,
        "dnwc": dnwc, "fcff": fcff, "t": t_index, "periods": periods, "tv_period": tv_period,
        **rates, "g": d["terminal_growth"], **bridge, "shares": shares, **val,
        "sum_pv": sum(val["pv"]), "ev_ebitda_base": val["ev"] / base_ebitda,
        "sens_wacc": sens_w, "sens_g": sens_g, "sens_grid": grid,
    }


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dart_mcp.dcf")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="가정 JSON → 수집 → 계산 → xlsx")
    b.add_argument("assumptions")
    b.add_argument("--out", required=True)
    b.add_argument("--verify", action="store_true", help="LibreOffice headless 재계산값과 엔진 결과 비교")
    args = p.parse_args(argv)

    from . import dcf_xlsx
    a = load_assumptions(args.assumptions)
    c = a["company"]
    h = collect_history(c["corp_code"], int(a["base_year"]), a.get("fs_div", "CFS"))
    try:
        res = compute(h, a)
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    cells = dcf_xlsx.export(h, a, res, args.out)
    print(json.dumps({"out": args.out, "ev": round(res["ev"], 1), "equity": round(res["equity"], 1),
                      "per_share": round(res["per_share"]), "wacc": round(res["wacc"], 6)}, ensure_ascii=False))
    if args.verify:
        try:
            recalced = dcf_xlsx.recalc_with_libreoffice(args.out)
        except FileNotFoundError as exc:
            print(f"검증 불가: {exc}", file=sys.stderr)
            return 1
        problems = dcf_xlsx.compare(recalced, cells, res)
        if problems:
            print("엔진과 불일치:\n  " + "\n  ".join(problems[:30]), file=sys.stderr)
            return 1
        print("verify ok: LibreOffice 재계산값 = 엔진 결과", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
