"""DCF 엔진 결과를 수식 기반 xlsx로 내보내고, LibreOffice 재계산값과 엔진 결과를 비교한다.

시트: 가정 · 과거재무 · 추정 · DCF · 민감도 (이 순서, 이 이름만).
- 입력값(숫자·텍스트)은 가정 시트에만 있다. 다른 시트의 값 셀은 전부 수식(숫자 상수 없음).
- 입력 셀은 파란 글씨, 수식 셀은 검정 글씨.
- 민감도(WACC × g)는 데이터 표 기능 없이 셀마다 닫힌 수식.
- DCF 시트 하단 체크 행: 0이 아니면 빨간색(조건부 서식).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from .dcf import FORECAST_YEARS, SENS_G_COLS, SENS_WACC_ROWS, SPECS, History

SHEETS = ("가정", "과거재무", "추정", "DCF", "민감도")
FONT = "Arial"
BLUE = "FF0000FF"
BLACK = "FF000000"
NUM = '#,##0;(#,##0);"-"'
PCT = '0.0%;(0.0%);"-"'
PCT2 = '0.00%;(0.00%);"-"'
MULT = '0.0"x"'
WON = '#,##0"원";(#,##0"원");"-"'
YEAR = '0"A"'
YEAR_E = '0"E"'
CHECK = '0.0000;(0.0000);0'
F_IN = Font(name=FONT, color=BLUE, size=10)
F_FX = Font(name=FONT, color=BLACK, size=10)
F_FX_B = Font(name=FONT, color=BLACK, size=10, bold=True)
F_LABEL = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_NOTE = Font(name=FONT, size=9, italic=True, color="FF595959")
F_TITLE = Font(name=FONT, size=14, bold=True)
F_HDR = Font(name=FONT, size=10, bold=True, color="FFFFFFFF")
FILL_HDR = PatternFill("solid", fgColor="FF1F3864")
FILL_HDR_FX = PatternFill("solid", fgColor="FFD9E1F2")
FILL_KEY = PatternFill("solid", fgColor="FFFFFF00")
TOP = Border(top=Side(style="thin", color="FF999999"))
RED_FONT = Font(name=FONT, color="FFFF0000", bold=True)
RED_FILL = PatternFill("solid", fgColor="FFFFC7CE")


class Sheet:
    """셀 쓰기 도우미: 값이 수식(=...)이면 검정, 아니면 입력(파랑)으로 칠한다."""

    def __init__(self, ws):
        self.ws = ws

    def label(self, r, c, text, font=F_LABEL):
        cell = self.ws.cell(row=r, column=c, value=text)
        cell.font = font
        return cell

    def put(self, r, c, value, fmt=None, bold=False, key=False):
        cell = self.ws.cell(row=r, column=c, value=value)
        is_formula = isinstance(value, str) and value.startswith("=")
        cell.font = (F_FX_B if bold else F_FX) if is_formula else F_IN
        if fmt:
            cell.number_format = fmt
        if key:
            cell.fill = FILL_KEY
        return cell

    def header(self, r, values, start=1):
        for i, v in enumerate(values):
            cell = self.ws.cell(row=r, column=start + i, value=v)
            cell.font = F_HDR
            cell.fill = FILL_HDR
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def widths(self, d):
        for k, v in d.items():
            self.ws.column_dimensions[k].width = v


def _abs(sheet: str, r: int, c: int) -> str:
    return f"{sheet}!${L(c)}${r}"


def export(h: History, a: dict, res: dict, out: str | Path) -> dict:
    """xlsx를 쓰고, 엔진 결과와 대조할 셀 주소표를 돌려준다."""
    n = FORECAST_YEARS
    wb = Workbook()
    ws_a = wb.active
    ws_a.title = "가정"
    for name in SHEETS[1:]:
        wb.create_sheet(name)
    A, HS, P, D, S = (Sheet(wb[s]) for s in SHEETS)
    ref: dict[str, str] = {}          # 가정 입력 이름 → 절대참조
    cells: dict[str, object] = {}     # 엔진 비교용 주소

    # ================================================================ 가정
    co = a["company"]
    A.label(1, 1, f"{co['name']}({co.get('stock_code', '')}) DCF — 가정", F_TITLE)
    A.label(2, 1, "파란 글씨 = 입력값(이 시트에만 있다). 검정 = 수식. 노란 칸 = 핵심 가정. "
                  "단위: 백만원(주당 값·주가는 원).", F_NOTE)
    r = 4
    A.header(r, ["일반", "값", "근거·출처"]); r += 1
    notes = a.get("notes", {})
    general = [
        ("company", "회사명", co["name"], None),
        ("stock_code", "종목코드", co.get("stock_code", ""), "@"),
        ("corp_code", "DART 고유번호", co["corp_code"], "@"),
        ("base_year", "기준 사업연도", int(a["base_year"]), "0"),
        ("valuation_date", "평가기준일", a["valuation_date"], "@"),
        ("fs_div", "재무제표", a.get("fs_div", "CFS"), "@"),
        ("issued", "발행주식총수(주)", a["shares"]["issued"], "#,##0"),
        ("treasury", "자기주식수(주)", a["shares"]["treasury"], "#,##0"),
        ("unit", "단위 환산(원/백만원)", a["unit_krw_per_mn"], "#,##0"),
        ("price", "현재 주가(원)", a.get("price"), WON),
    ]
    for key, lab, val, fmt in general:
        A.label(r, 1, lab)
        A.put(r, 2, val, fmt, key=key == "price")
        A.label(r, 3, notes.get(key, a["shares"].get("cite", "") if key in ("issued", "treasury") else ""), F_NOTE)
        ref[key] = _abs("가정", r, 2)
        r += 1

    r += 1
    A.header(r, ["추정 가정"] + [f"{i + 1}년차" for i in range(n)] + ["근거"])
    yr_row = r
    r += 1
    fc = a["forecast"]
    flabels = {"revenue_growth": "매출 성장률", "operating_margin": "영업이익률", "tax_rate": "법인세율(EBIT 적용)",
               "da_pct": "감가상각비 / 매출", "capex_pct": "CAPEX / 매출", "nwc_pct": "순운전자본 / 매출"}
    frow: dict[str, int] = {}
    for key, lab in flabels.items():
        A.label(r, 1, lab, F_BOLD)
        for i, v in enumerate(fc[key]):
            A.put(r, 2 + i, v, PCT, key=True)
        A.label(r, 2 + n, notes.get(key, ""), F_NOTE)
        frow[key] = r
        r += 1

    r += 1
    A.header(r, ["할인율·잔존가치", "값", "근거"]); r += 1
    dl = {"rf": ("무위험이자율 Rf", PCT2), "mrp": ("시장위험프리미엄 MRP", PCT2), "beta": ("베타 β", "0.00"),
          "crp": ("국가·특유위험 프리미엄", PCT2), "kd": ("세전 타인자본비용 Kd", PCT2),
          "debt_weight": ("목표 부채비중 D/(D+E)", PCT2), "terminal_growth": ("영구성장률 g", PCT2),
          "cf_timing_adj": ("현금흐름 할인시점 조정(년)", "0.00"), "tv_timing_adj": ("잔존가치 할인시점 조정(년)", "0.00")}
    for key, (lab, fmt) in dl.items():
        A.label(r, 1, lab)
        A.put(r, 2, a["discount"][key], fmt, key=key in ("rf", "mrp", "beta", "crp", "terminal_growth",
                                                         "cf_timing_adj", "tv_timing_adj"))
        A.label(r, 3, notes.get(key, ""), F_NOTE)
        ref[key] = _abs("가정", r, 2)
        r += 1
    for key, lab in (("wacc_step", "민감도 WACC 간격"), ("g_step", "민감도 g 간격")):
        A.label(r, 1, lab)
        A.put(r, 2, a["sensitivity"][key], PCT2)
        ref[key] = _abs("가정", r, 2)
        r += 1

    # 과거 재무 입력 (수집 단계에서 원 → 백만원 1회 환산된 값)
    r += 1
    hy = h.years
    A.header(r, ["과거 재무 입력 (DART 재무API, 백만원)"] + list(hy) + ["API 계정명"])
    hist_year_row = r
    r += 1
    A.label(r, 1, "사업연도")
    for j, y in enumerate(hy):
        A.put(r, 2 + j, int(y), "0")
    hist_year_row = r
    r += 1
    A.label(r, 1, "출처 rcept_no")
    for j, y in enumerate(hy):
        A.put(r, 2 + j, h.sources.get(y, ""), "@")
    r += 1
    hrow: dict[str, int] = {}
    for spec in SPECS:
        A.label(r, 1, spec.label)
        for j, y in enumerate(hy):
            v = h.values[spec.key].get(y)
            A.put(r, 2 + j, "n/a" if v is None else v, NUM)
        names = sorted(set((h.matched.get(spec.key) or {}).values()))
        A.label(r, 2 + len(hy), " / ".join(names) or "(없음)", F_NOTE)
        hrow[spec.key] = r
        r += 1
    A.label(r + 1, 1, "주: 'n/a'는 해당 연도 보고서에서 계정을 찾지 못한 것. 합산 계정(차입금·리스부채)은 행이 없으면 0.", F_NOTE)
    A.widths({"A": 34, "B": 14, "C": 14, "D": 14, "E": 14, "F": 14, "G": 14, "H": 50})
    A.ws.freeze_panes = "B5"

    def hin(key: str, j: int) -> str:     # 가정 시트 과거 입력 셀(상대열)
        return f"가정!{L(2 + j)}{hrow[key]}"

    # ================================================================ 과거재무
    HS.label(1, 1, "과거 재무 (연결, 백만원) — 가정 시트 입력을 참조하는 수식", F_TITLE)
    HS.header(3, ["항목"] + [""] * len(hy))
    for j in range(len(hy)):
        HS.put(3, 2 + j, f"=가정!{L(2 + j)}{hist_year_row}", YEAR)
        HS.ws.cell(row=3, column=2 + j).font = F_FX_B
        HS.ws.cell(row=3, column=2 + j).fill = FILL_HDR_FX
    hs: dict[str, int] = {}

    def hline(r, key, lab, fn, fmt=NUM, bold=False, first=0):
        HS.label(r, 1, lab, F_BOLD if bold else F_LABEL)
        for j in range(first, len(hy)):
            c = L(2 + j)
            HS.put(r, 2 + j, f"=IFERROR({fn(j, c)},\"n/a\")", fmt, bold=bold)
        hs[key] = r

    hline(4, "rev", "매출액", lambda j, c: hin("revenue", j), bold=True)
    hline(5, "g", "  매출 성장률", lambda j, c: f"{c}4/{L(1 + j)}4-1", PCT, first=1)
    hline(6, "ebit", "영업이익(EBIT)", lambda j, c: hin("ebit", j))
    hline(7, "opm", "  영업이익률", lambda j, c: f"{c}6/{c}4", PCT)
    hline(8, "da", "감가상각비(유형·사용권·무형·투자부동산)",
          lambda j, c: hin("dep", j) + "".join(f"+N({hin(k, j)})" for k in ("dep_rou", "amort", "dep_ip")))
    hline(9, "da%", "  감가상각비 / 매출", lambda j, c: f"{c}8/{c}4", PCT)
    hline(10, "ebitda", "EBITDA", lambda j, c: f"{c}6+{c}8")
    hline(11, "capex", "CAPEX(유형+무형 취득)",
          lambda j, c: f"{hin('capex_ppe', j)}+N({hin('capex_int', j)})")
    hline(12, "capex%", "  CAPEX / 매출", lambda j, c: f"{c}11/{c}4", PCT)
    hline(13, "nwc", "순운전자본(매출채권+재고−매입채무)",
          lambda j, c: f"{hin('ar', j)}+{hin('inventory', j)}-{hin('ap', j)}")
    hline(14, "nwc%", "  순운전자본 / 매출", lambda j, c: f"{c}13/{c}4", PCT)
    hline(15, "etr", "유효법인세율(법인세/세전이익)", lambda j, c: f"{hin('tax', j)}/{hin('ebt', j)}", PCT)
    hline(16, "nip", "지배주주 순이익", lambda j, c: hin("ni_parent", j))
    hline(18, "cash_like", "현금성자산(현금+단기·장기예치금+유동FVPL)",
          lambda j, c: hin("cash", j) + "".join(f"+N({hin(k, j)})" for k in ("st_deposit", "lt_deposit", "fvpl_current")))
    hline(19, "debt", "차입금+리스부채", lambda j, c: f"N({hin('borrowings', j)})+N({hin('lease', j)})")
    hline(20, "net_debt", "순차입금(음수 = 순현금)", lambda j, c: f"{c}19-{c}18", bold=True)
    hline(21, "nonop", "비영업자산(지분법·투자부동산·FVOCI)",
          lambda j, c: "+".join(f"N({hin(k, j)})" for k in ("equity_method", "inv_property", "fvoci")))
    hline(22, "nci", "비지배지분", lambda j, c: f"N({hin('nci', j)})")
    hline(24, "assets", "자산총계", lambda j, c: hin("assets", j))
    hline(25, "liab", "부채총계", lambda j, c: hin("liabilities", j))
    hline(26, "equity", "자본총계", lambda j, c: hin("equity", j))
    hline(27, "bs_chk", "체크: 자산 − (부채 + 자본)", lambda j, c: f"ROUND({c}24-{c}25-{c}26,4)", CHECK)
    HS.label(29, 1, "주: N()은 '없음(n/a)' 입력을 0으로 본다(해당 계정 없음). 매출·EBIT 등 필수 계정이 n/a면 그 연도 비율은 n/a.",
             F_NOTE)
    HS.widths({"A": 40, **{L(2 + j): 14 for j in range(len(hy))}})
    HS.ws.freeze_panes = "B4"
    base_col = L(1 + len(hy))  # 과거재무의 기준연도 열

    def hb(key: str) -> str:
        return f"과거재무!${base_col}${hs[key]}"

    # ================================================================ 추정
    P.label(1, 1, "추정 (백만원) — FCFF = EBIT×(1−법인세율) + 감가상각비 − CAPEX − 순운전자본 증가", F_TITLE)
    P.header(3, ["항목", "기준연도"] + [""] * n)
    fcol = [L(3 + i) for i in range(n)]
    for i, c in enumerate(fcol):
        P.put(3, 3 + i, f"=$B$4+{c}5", YEAR_E)
        P.ws.cell(row=3, column=3 + i).font = F_FX_B
        P.ws.cell(row=3, column=3 + i).fill = FILL_HDR_FX
    P.put(3, 2, f"={ref['base_year']}", YEAR, bold=True).fill = FILL_HDR_FX
    P.label(4, 1, "기준 사업연도")
    P.put(4, 2, f"={ref['base_year']}", "0")
    P.label(5, 1, "연차 t")
    for i, c in enumerate(fcol):
        P.put(5, 3 + i, f"=COLUMNS(${fcol[0]}$5:{c}5)", "0")
    rows = {}

    def prow(r, key, lab, base, fn, fmt=NUM, bold=False, border=False):
        P.label(r, 1, lab, F_BOLD if bold else F_LABEL)
        if base:
            P.put(r, 2, base, fmt, bold=bold)
        for i, c in enumerate(fcol):
            prev = L(2 + i)
            P.put(r, 3 + i, fn(i, c, prev), fmt, bold=bold)
        if border:
            for cc in range(1, 3 + n):
                P.ws.cell(row=r, column=cc).border = TOP
        rows[key] = r

    def asm(key, i):
        return f"가정!${L(2 + i)}${frow[key]}"

    prow(6, "rev", "매출액", f"={hb('rev')}", lambda i, c, p: f"={p}6*(1+{asm('revenue_growth', i)})", bold=True)
    prow(7, "g", "  성장률", f"={hb('g')}", lambda i, c, p: f"={c}6/{p}6-1", PCT)
    prow(8, "ebit", "영업이익(EBIT)", f"={hb('ebit')}", lambda i, c, p: f"={c}6*{asm('operating_margin', i)}")
    prow(9, "opm", "  영업이익률", f"={hb('opm')}", lambda i, c, p: f"={c}8/{c}6", PCT)
    prow(10, "taxr", "  법인세율", None, lambda i, c, p: f"={asm('tax_rate', i)}", PCT)
    prow(11, "tax", "법인세(EBIT 기준)", None, lambda i, c, p: f"={c}8*{c}10")
    prow(12, "nopat", "NOPAT = EBIT − 법인세", None, lambda i, c, p: f"={c}8-{c}11", bold=True, border=True)
    prow(13, "da", "감가상각비", f"={hb('da')}", lambda i, c, p: f"={c}6*{asm('da_pct', i)}")
    prow(14, "capex", "CAPEX", f"={hb('capex')}", lambda i, c, p: f"={c}6*{asm('capex_pct', i)}")
    prow(15, "nwc", "순운전자본(기말)", f"={hb('nwc')}", lambda i, c, p: f"={c}6*{asm('nwc_pct', i)}")
    prow(16, "dnwc", "순운전자본 증가(현금유출)", None, lambda i, c, p: f"={c}15-{p}15")
    prow(17, "fcff", "FCFF = NOPAT + 감가상각비 − CAPEX − 순운전자본 증가", None,
         lambda i, c, p: f"={c}12+{c}13-{c}14-{c}16", bold=True, border=True)
    prow(18, "ebitda", "참고: EBITDA", f"={hb('ebitda')}", lambda i, c, p: f"={c}8+{c}13")
    P.label(20, 1, "부호: 법인세·CAPEX·순운전자본 증가는 양수로 표시하고 FCFF 수식에서 차감한다.", F_NOTE)
    P.widths({"A": 50, "B": 14, **{c: 14 for c in fcol}})
    P.ws.freeze_panes = "C4"
    FC = f"추정!${fcol[0]}${rows['fcff']}:${fcol[-1]}${rows['fcff']}"
    TT = f"추정!${fcol[0]}$5:${fcol[-1]}$5"
    FN_ = f"추정!${fcol[-1]}${rows['fcff']}"
    TN = f"추정!${fcol[-1]}$5"
    cells["revenue"] = [("추정", f"{c}6") for c in fcol]
    cells["ebit"] = [("추정", f"{c}8") for c in fcol]
    cells["da"] = [("추정", f"{c}13") for c in fcol]
    cells["capex"] = [("추정", f"{c}14") for c in fcol]
    cells["dnwc"] = [("추정", f"{c}16") for c in fcol]
    cells["fcff"] = [("추정", f"{c}17") for c in fcol]

    # ================================================================ DCF
    D.label(1, 1, f"{co['name']} DCF — 기업가치 → 주주가치 (백만원)", F_TITLE)
    D.label(2, 1, "할인계수 = 1/(1+WACC)^(t − 현금흐름 할인시점 조정), 잔존가치는 (N − 잔존가치 할인시점 조정). "
                  "주주가치 = 기업가치 − 순차입금 + 비영업자산 − 비지배지분.", F_NOTE)
    r = 4
    D.header(r, ["할인율", "값", "식"]); r += 1
    dv = {}

    def drow(key, lab, formula, fmt=NUM, note="", bold=False, key_fill=False):
        nonlocal r
        D.label(r, 1, lab, F_BOLD if bold else F_LABEL)
        D.put(r, 2, formula, fmt, bold=bold, key=key_fill)
        if note:
            D.label(r, 3, note, F_NOTE)
        dv[key] = f"DCF!$B${r}"
        r += 1

    drow("ke", "자기자본비용 Ke", f"={ref['rf']}+{ref['beta']}*{ref['mrp']}+{ref['crp']}", PCT2, "Rf + β×MRP + 프리미엄")
    drow("kd_after", "세후 타인자본비용", f"={ref['kd']}*(1-{asm('tax_rate', 0)})", PCT2, "Kd × (1 − 1년차 법인세율)")
    drow("wacc", "WACC", f"={dv['ke']}*(1-{ref['debt_weight']})+{dv['kd_after']}*{ref['debt_weight']}", PCT2,
         "Ke×E/V + Kd(1−t)×D/V", bold=True, key_fill=True)
    drow("g", "영구성장률 g", f"={ref['terminal_growth']}", PCT2)
    cells["wacc"] = ("DCF", dv["wacc"].split("!")[1].replace("$", ""))
    cells["ke"] = ("DCF", dv["ke"].split("!")[1].replace("$", ""))

    r += 1
    D.header(r, ["현금흐름 할인", ""] + [""] * n)
    for i, c in enumerate(fcol):
        D.put(r, 3 + i, f"=추정!{c}3", YEAR_E)
        D.ws.cell(row=r, column=3 + i).font = F_FX_B
        D.ws.cell(row=r, column=3 + i).fill = FILL_HDR_FX
    r += 1
    fr = {}
    for key, lab, fn, fmt in (
        ("fcff", "FCFF", lambda c: f"=추정!{c}{rows['fcff']}", NUM),
        ("per", "할인기간 (t − 조정)", lambda c: f"=추정!{c}5-{ref['cf_timing_adj']}", "0.00"),
        ("df", "할인계수", lambda c: f"=1/(1+{dv['wacc']})^{c}{{per}}", "0.0000"),
        ("pv", "FCFF 현재가치", lambda c: f"={c}{{fcff}}*{c}{{df}}", NUM),
    ):
        D.label(r, 1, lab, F_BOLD if key == "pv" else F_LABEL)
        fr[key] = r
        for i, c in enumerate(fcol):
            D.put(r, 3 + i, fn(c).replace("{per}", str(fr.get("per", ""))).replace("{fcff}", str(fr.get("fcff", "")))
                  .replace("{df}", str(fr.get("df", ""))), fmt, bold=key == "pv")
        r += 1
    cells["pv"] = [("DCF", f"{c}{fr['pv']}") for c in fcol]
    PVR = f"DCF!${fcol[0]}${fr['pv']}:${fcol[-1]}${fr['pv']}"

    r += 1
    D.header(r, ["기업가치", "값", "비고"]); r += 1
    drow("sum_pv", "예측기간 현재가치 합", f"=SUM({PVR})")
    drow("tv", "잔존가치 TV (N년 말)",
         f"=IF({dv['g']}>={dv['wacc']},NA(),{FN_}*(1+{dv['g']})/({dv['wacc']}-{dv['g']}))", NUM,
         "FCFF_N × (1+g) / (WACC − g). g ≥ WACC면 #N/A(계산 안 함)")
    drow("tv_per", "잔존가치 할인기간", f"={TN}-{ref['tv_timing_adj']}", "0.00", "N − 잔존가치 할인시점 조정")
    drow("pv_tv", "잔존가치 현재가치", f"={dv['tv']}/(1+{dv['wacc']})^{dv['tv_per']}")
    drow("ev", "기업가치(EV)", f"={dv['sum_pv']}+{dv['pv_tv']}", NUM, bold=True)
    drow("tv_share", "  EV 중 잔존가치 비중", f"={dv['pv_tv']}/{dv['ev']}", PCT)
    r += 1
    D.header(r, ["주주가치", "값", "비고"]); r += 1
    drow("net_debt", "(−) 순차입금", f"={hb('net_debt')}", NUM, "차입금+리스부채 − 현금성자산. 음수면 순현금(가치 가산)")
    drow("nonop", "(+) 비영업자산", f"={hb('nonop')}", NUM, "지분법투자·투자부동산·FVOCI 장부가")
    drow("nci", "(−) 비지배지분", f"={hb('nci')}", NUM, "장부가")
    drow("equity", "주주가치(지배주주)", f"={dv['ev']}-{dv['net_debt']}+{dv['nonop']}-{dv['nci']}", NUM, bold=True)
    drow("shares", "유통주식수(주)", f"={ref['issued']}-{ref['treasury']}", "#,##0")
    drow("per_share", "주당 가치(원)", f"={dv['equity']}*{ref['unit']}/{dv['shares']}", WON, bold=True, key_fill=True)
    drow("price", "현재 주가(원)", f"=IF(ISNUMBER({ref['price']}),{ref['price']},\"\")", WON, "가정 시트 입력")
    drow("upside", "상승여력", f"=IF(ISNUMBER({dv['price']}),{dv['per_share']}/{dv['price']}-1,\"주가 입력 필요\")", PCT)
    r += 1
    D.header(r, ["내재 배수", "값", "비고"]); r += 1
    base_c = "B"
    drow("m_ebitda", "EV / EBITDA (기준연도)", f"={dv['ev']}/추정!{base_c}{rows['ebitda']}", MULT)
    drow("m_ebitda1", "EV / EBITDA (1년차)", f"={dv['ev']}/추정!{fcol[0]}{rows['ebitda']}", MULT)
    drow("m_per", "주주가치 / 지배주주순이익 (기준연도)", f"={dv['equity']}/{hb('nip')}", MULT)
    drow("m_tv", "잔존가치 내재 EV/EBITDA (N년차)", f"={dv['tv']}/추정!{fcol[-1]}{rows['ebitda']}", MULT)
    for k in ("sum_pv", "tv", "pv_tv", "ev", "net_debt", "nonop", "nci", "equity", "shares", "per_share", "m_ebitda"):
        cells[k] = ("DCF", dv[k].split("!")[1].replace("$", ""))

    # 민감도 중앙 칸 위치(아래 민감도 시트와 같은 배치)
    s_top, s_left = 5, 3
    s_center = f"민감도!${L(s_left + SENS_G_COLS // 2)}${s_top + SENS_WACC_ROWS // 2}"

    r += 1
    D.header(r, ["체크 (0이어야 함, 아니면 빨간색)", "차이", "내용"]); r += 1
    chk_first = r
    hy_first, hy_last = L(2), L(1 + len(hy))
    bs_rng = f"과거재무!${hy_first}${hs['bs_chk']}:${hy_last}${hs['bs_chk']}"
    checks = [
        ("자산 = 부채 + 자본 (과거 전 연도)", f"=ROUND(SUMIF({bs_rng},\">0\")-SUMIF({bs_rng},\"<0\"),4)",
         "과거재무 체크 행의 절대값 합"),
        ("현재가치 합계 = 기업가치",
         f"=ROUND(SUMPRODUCT({FC}/(1+{dv['wacc']})^({TT}-{ref['cf_timing_adj']}))+{dv['pv_tv']}-{dv['ev']},4)",
         "FCFF를 SUMPRODUCT로 독립 재할인 + TV 현재가치 − EV"),
        ("FCFF = EBIT(1−t) + 감가상각비 − CAPEX − ΔNWC",
         f"=ROUND(SUMPRODUCT(추정!${fcol[0]}$8:${fcol[-1]}$8*(1-추정!${fcol[0]}$10:${fcol[-1]}$10)"
         f"+추정!${fcol[0]}$13:${fcol[-1]}$13-추정!${fcol[0]}$14:${fcol[-1]}$14-추정!${fcol[0]}$16:${fcol[-1]}$16"
         f"-{FC.replace('추정!', '추정!')}),4)", "연도별 차이 합"),
        ("순차입금 = 차입금 + 리스부채 − 현금성자산 (가정 시트 원값)",
         f"=ROUND({dv['net_debt']}-(N({hin('borrowings', len(hy) - 1)})+N({hin('lease', len(hy) - 1)})"
         f"-N({hin('cash', len(hy) - 1)})-N({hin('st_deposit', len(hy) - 1)})-N({hin('lt_deposit', len(hy) - 1)})"
         f"-N({hin('fvpl_current', len(hy) - 1)})),4)", "기준연도"),
        ("주주가치 = EV − 순차입금 + 비영업자산 − 비지배지분",
         f"=ROUND({dv['ev']}-{dv['net_debt']}+{dv['nonop']}-{dv['nci']}-{dv['equity']},4)", ""),
        ("민감도 중앙 = 주당 가치", f"=ROUND({s_center}-{dv['per_share']},4)", "민감도 시트 기준 WACC·g 칸"),
        ("g < WACC", f"=IF({dv['g']}<{dv['wacc']},0,1)", "1이면 Gordon 모형 계산 불가"),
    ]
    for lab, formula, note in checks:
        D.label(r, 1, lab)
        D.put(r, 2, formula, CHECK)
        D.label(r, 3, note, F_NOTE)
        r += 1
    D.label(r, 1, "체크 합계", F_BOLD)
    D.put(r, 2, f"=SUMPRODUCT(ABS(B{chk_first}:B{r - 1}))", CHECK, bold=True)
    cells["checks"] = [("DCF", f"B{i}") for i in range(chk_first, r + 1)]
    D.ws.conditional_formatting.add(f"B{chk_first}:B{r}",
                                    CellIsRule(operator="notEqual", formula=["0"], font=RED_FONT, fill=RED_FILL))
    D.widths({"A": 46, "B": 16, **{c: 14 for c in fcol}})
    D.ws.column_dimensions["C"].width = 16

    # ================================================================ 민감도
    S.label(1, 1, "민감도 — 주당 가치(원): WACC × 영구성장률 g", F_TITLE)
    S.label(2, 1, "각 칸은 추정 시트 FCFF를 직접 재할인하는 닫힌 수식(데이터 표 기능 미사용). g ≥ WACC 칸은 #N/A. "
                  "간격은 가정 시트 입력.", F_NOTE)
    S.label(s_top - 1, 2, "WACC ↓ / g →", F_BOLD)
    gc, wc = SENS_G_COLS // 2, SENS_WACC_ROWS // 2
    for j in range(SENS_G_COLS):
        col = s_left + j
        if j == gc:
            f = f"={dv['g']}"
        elif j < gc:
            f = f"={L(col + 1)}{s_top - 1}-{ref['g_step']}"
        else:
            f = f"={L(col - 1)}{s_top - 1}+{ref['g_step']}"
        S.put(s_top - 1, col, f, PCT)
    for i in range(SENS_WACC_ROWS):
        row = s_top + i
        if i == wc:
            f = f"={dv['wacc']}"
        elif i < wc:
            f = f"=B{row + 1}-{ref['wacc_step']}"
        else:
            f = f"=B{row - 1}+{ref['wacc_step']}"
        S.put(row, 2, f, PCT2)
    # 위쪽 칸이 아래 칸을 참조하므로 순환은 없다(가운데가 기준).
    grid = []
    for i in range(SENS_WACC_ROWS):
        row = s_top + i
        line = []
        for j in range(SENS_G_COLS):
            col = s_left + j
            w, g = f"$B{row}", f"{L(col)}${s_top - 1}"
            f = (f"=IF({g}>={w},NA(),(SUMPRODUCT({FC}/(1+{w})^({TT}-{ref['cf_timing_adj']}))"
                 f"+{FN_}*(1+{g})/({w}-{g})/(1+{w})^({TN}-{ref['tv_timing_adj']})"
                 f"-{dv['net_debt']}+{dv['nonop']}-{dv['nci']})*{ref['unit']}/{dv['shares']})")
            S.put(row, col, f, "#,##0")
            line.append(("민감도", f"{L(col)}{row}"))
        grid.append(line)
    cells["sens_grid"] = grid
    cells["sens_wacc"] = [("민감도", f"B{s_top + i}") for i in range(SENS_WACC_ROWS)]
    cells["sens_g"] = [("민감도", f"{L(s_left + j)}{s_top - 1}") for j in range(SENS_G_COLS)]
    S.widths({"A": 3, "B": 16, **{L(s_left + j): 14 for j in range(SENS_G_COLS)}})

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return cells


# --------------------------------------------------------------------------- 재계산·비교
def find_soffice() -> str | None:
    env = os.environ.get("SOFFICE")
    if env and Path(env).exists():
        return env
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).exists():
            return p
    return None


def recalc_with_libreoffice(path: str | Path, outdir: str | Path | None = None, timeout: int = 120) -> Path:
    """LibreOffice headless로 열어 다시 저장(수식 계산값이 캐시됨). 재계산된 사본 경로를 돌려준다."""
    soffice = find_soffice()
    if not soffice:
        raise FileNotFoundError("LibreOffice(soffice)를 찾지 못했다. 설치하거나 SOFFICE 환경변수에 경로를 넣는다")
    src = Path(path).resolve()
    out = Path(outdir) if outdir else Path(tempfile.mkdtemp(prefix="dcf_lo_"))
    out.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="dcf_lo_profile_"))
    cmd = [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
           "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(src)]
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
    result = out / src.name
    if not result.exists():
        raise RuntimeError(f"LibreOffice 변환 결과가 없다: {result}")
    return result


def _close(a, b, rel=1e-9, abs_tol=1e-6) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def compare(recalced_path: str | Path, cells: dict, res: dict, rel: float = 1e-9) -> list[str]:
    """재계산된 xlsx의 캐시값과 엔진 결과(res)를 비교. 불일치 목록(비면 통과)."""
    wb = load_workbook(recalced_path, data_only=True)
    problems: list[str] = []

    def val(addr):
        sheet, coord = addr
        return wb[sheet][coord].value

    def check(name, addr, expect):
        got = val(addr)
        if expect is None:
            if not (got is None or (isinstance(got, str) and got.startswith("#N/A"))):
                problems.append(f"{name} {addr}: 기대 #N/A, 엑셀 {got!r}")
            return
        if not isinstance(got, (int, float)):
            problems.append(f"{name} {addr}: 숫자 아님 {got!r} (기대 {expect})")
        elif not _close(float(got), float(expect), rel):
            problems.append(f"{name} {addr}: 엑셀 {got} ≠ 엔진 {expect}")

    for key in ("revenue", "ebit", "da", "capex", "dnwc", "fcff", "pv"):
        for i, addr in enumerate(cells[key]):
            check(f"{key}[{i}]", addr, res[key][i])
    for key in ("wacc", "ke", "sum_pv", "tv", "pv_tv", "ev", "net_debt", "nonop", "nci", "equity", "shares",
                "per_share"):
        check(key, cells[key], res[key])
    check("ev_ebitda_base", cells["m_ebitda"], res["ev_ebitda_base"])
    for i, addr in enumerate(cells["sens_wacc"]):
        check(f"sens_wacc[{i}]", addr, res["sens_wacc"][i])
    for j, addr in enumerate(cells["sens_g"]):
        check(f"sens_g[{j}]", addr, res["sens_g"][j])
    for i, line in enumerate(cells["sens_grid"]):
        for j, addr in enumerate(line):
            check(f"sens[{i}][{j}]", addr, res["sens_grid"][i][j])
    for addr in cells["checks"]:
        got = val(addr)
        if got != 0:
            problems.append(f"체크 {addr}: {got!r} (0이어야 함)")
    return problems
