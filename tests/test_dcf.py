"""DCF 엔진·xlsx 내보내기: 모델링 규칙과 엑셀 규칙, LibreOffice 재계산 = 엔진."""
from __future__ import annotations

import copy
import re

import pytest
from openpyxl import load_workbook

from dart_mcp import dcf, dcf_xlsx
from dart_mcp.dcf import SPECS, History, _extract, compute

YEARS = [str(y) for y in range(2020, 2026)]


def make_history(**base_overrides) -> History:
    base = {
        "revenue": 1000.0, "ebit": 150.0, "ebt": 160.0, "tax": 40.0, "ni_parent": 110.0,
        "dep": 40.0, "dep_rou": 5.0, "amort": 3.0, "dep_ip": 1.0, "capex_ppe": 45.0, "capex_int": 5.0,
        "ar": 100.0, "inventory": 80.0, "ap": 60.0, "cash": 200.0, "st_deposit": 50.0, "lt_deposit": 1.0,
        "fvpl_current": 4.0, "equity_method": 30.0, "inv_property": 10.0, "fvoci": 2.0, "borrowings": 70.0,
        "lease": 20.0, "nci": 15.0, "assets": 900.0, "liabilities": 300.0, "equity": 600.0,
    }
    base.update(base_overrides)
    values = {}
    for spec in SPECS:
        v = base[spec.key]
        values[spec.key] = {y: (v * (0.9 ** (2025 - int(y))) if v is not None else None) for y in YEARS}
    # 자산 = 부채 + 자본이 모든 연도에서 성립하도록
    for y in YEARS:
        values["assets"][y] = values["liabilities"][y] + values["equity"][y]
    return History("00000000", "CFS", YEARS, values, {y: f"2026000000{y[-2:]}" for y in YEARS})


def make_assumptions(**discount) -> dict:
    a = {
        "company": {"name": "테스트", "stock_code": "000000", "corp_code": "00000000"},
        "base_year": 2025, "valuation_date": "2025-12-31", "fs_div": "CFS",
        "shares": {"issued": 1_000_000, "treasury": 10_000, "cite": "test"},
        "unit_krw_per_mn": 1_000_000, "price": 50_000,
        "forecast": {
            "revenue_growth": [0.10, 0.08, 0.06, 0.05, 0.04],
            "operating_margin": [0.15, 0.15, 0.16, 0.16, 0.16],
            "lease_interest_pct": [0.001] * 5,
            "tax_rate": [0.25, 0.25, 0.25, 0.26, 0.26],
            "da_pct": [0.05] * 5, "capex_pct": [0.06, 0.06, 0.05, 0.05, 0.05], "nwc_pct": [0.12] * 5,
        },
        "discount": {"rf": 0.03, "mrp": 0.07, "beta": 1.0, "crp": 0.0, "kd": 0.05, "debt_weight": 0.2,
                     "terminal_growth": 0.02, "cf_timing_adj": 0.5, "tv_timing_adj": 0.5},
        "sensitivity": {"wacc_step": 0.005, "g_step": 0.005},
        "lease": {"base_interest": 2.0, "cite": "test"},
    }
    a["discount"].update(discount)
    return a


# ------------------------------------------------------------------ 엔진
def test_fcff_formula_and_signs():
    h, a = make_history(), make_assumptions()
    res = compute(h, a)
    f = a["forecast"]
    rev1 = 1000 * 1.10
    ebit1 = rev1 * 0.15 - rev1 * 0.001            # 보고 영업이익 − 리스 이자
    dnwc1 = rev1 * 0.12 - (100 + 80 - 60)
    expect = ebit1 * (1 - 0.25) + rev1 * 0.05 - rev1 * 0.06 - dnwc1
    assert res["fcff"][0] == pytest.approx(expect)
    assert res["capex"][0] > 0 and res["tax"][0] > 0            # 양수로 두고 차감
    for i in range(5):
        assert res["fcff"][i] == pytest.approx(
            res["ebit"][i] * (1 - f["tax_rate"][i]) + res["da"][i] - res["capex"][i] - res["dnwc"][i])


def test_mid_year_discounting_and_tv():
    h, a = make_history(), make_assumptions()
    res = compute(h, a)
    w, g = res["wacc"], 0.02
    assert res["wacc"] == pytest.approx((0.03 + 0.07) * 0.8 + 0.05 * (1 - 0.25) * 0.2)
    assert res["df"] == pytest.approx([1 / (1 + w) ** (t - 0.5) for t in range(1, 6)])
    assert res["tv"] == pytest.approx(res["fcff"][-1] * (1 + g) / (w - g))
    assert res["pv_tv"] == pytest.approx(res["tv"] / (1 + w) ** 4.5)
    end = compute(h, make_assumptions(cf_timing_adj=0.0, tv_timing_adj=0.0))
    assert end["df"][0] == pytest.approx(1 / (1 + w))
    assert end["ev"] < res["ev"]


def test_equity_bridge():
    res = compute(make_history(), make_assumptions())
    assert res["net_debt"] == pytest.approx(70 - (200 + 50 + 1 + 4))     # 리스부채 20 제외
    assert res["lease_excluded"] == pytest.approx(20)
    assert res["nonop"] == pytest.approx(30 + 10 + 2)
    assert res["equity"] == pytest.approx(res["ev"] - res["net_debt"] + res["nonop"] - res["nci"])
    assert res["per_share"] == pytest.approx(res["equity"] * 1_000_000 / 990_000)


def test_lease_method_two_is_consistent():
    """리스 방법 2: 사용권자산 상각비·리스부채는 가치에 영향 없고, 리스 이자는 EBIT에서 빠진다."""
    a = make_assumptions()
    base = compute(make_history(), a)
    assert compute(make_history(dep_rou=500.0), a)["per_share"] == pytest.approx(base["per_share"])
    assert compute(make_history(lease=900.0), a)["per_share"] == pytest.approx(base["per_share"])
    assert base["base_ebit"] == pytest.approx(150 - 2.0)
    assert base["base_ebitda"] == pytest.approx(150 - 2.0 + 40 + 3 + 1)      # dep_rou 5 미가산
    for i in range(5):
        assert base["ebit"][i] == pytest.approx(base["ebit_reported"][i] - base["lease_interest"][i])
    more = copy.deepcopy(a)
    more["forecast"]["lease_interest_pct"] = [0.01] * 5
    assert compute(make_history(), more)["per_share"] < base["per_share"]


def test_lease_base_interest_required():
    a = make_assumptions()
    del a["lease"]
    with pytest.raises(ValueError, match="lease"):
        compute(make_history(), a)


def test_g_not_less_than_wacc_raises():
    a = make_assumptions(terminal_growth=0.2)
    with pytest.raises(ValueError, match="WACC"):
        compute(make_history(), a)


def test_sensitivity_grid_marks_invalid_cells():
    a = make_assumptions(terminal_growth=0.05, rf=0.02, mrp=0.04, beta=1.0, debt_weight=0.0)  # WACC 6%
    res = compute(make_history(), a)
    assert res["sens_grid"][0][-1] is None            # WACC 4.5%, g 6% → 계산 안 함
    assert res["sens_grid"][3][2] == pytest.approx(res["per_share"])


def test_assumptions_must_have_five_years():
    a = make_assumptions()
    a["forecast"]["capex_pct"] = [0.05] * 4
    with pytest.raises(ValueError, match="5개"):
        compute(make_history(), a)


def test_extract_converts_won_to_million_once():
    items = [
        {"sj_div": "CIS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
         "thstrm_amount": "3332442536373", "frmtrm_amount": "3104338576129", "bfefrmtrm_amount": "2912358051475"},
        {"sj_div": "BS", "account_id": "-", "account_nm": "유동리스부채",
         "thstrm_amount": "13695740434", "frmtrm_amount": "1", "bfefrmtrm_amount": "2"},
        {"sj_div": "BS", "account_id": "-", "account_nm": "비유동리스부채",
         "thstrm_amount": "21820294542", "frmtrm_amount": "1", "bfefrmtrm_amount": "2"},
    ]
    values, _ = _extract(items, ["2025", "2024", "2023"])
    assert values["revenue"]["2025"] == pytest.approx(3332442.536373)
    assert values["lease"]["2025"] == pytest.approx(35516.034976)
    assert values["borrowings"]["2025"] == 0          # 합산 계정에 행이 없으면 0
    assert values["ebit"]["2025"] is None


# ------------------------------------------------------------------ 엑셀 규칙
@pytest.fixture()
def exported(tmp_path):
    h, a = make_history(capex_int=None), make_assumptions()
    res = compute(h, a)
    out = tmp_path / "dcf.xlsx"
    cells = dcf_xlsx.export(h, a, res, out)
    return out, cells, res


def _formula_literals(f: str) -> set[str]:
    s = re.sub(r"'[^']*'!|[가-힣A-Za-z_]+!", "", f)            # 시트 이름
    s = re.sub(r'"[^"]*"', "", s)                              # 문자열
    s = re.sub(r"\$?[A-Z]{1,3}\$?\d+", "", s)                  # 셀 참조
    return set(re.findall(r"(?<![A-Za-z_])\d+(?:\.\d+)?", s))


def test_sheet_names(exported):
    out, _, _ = exported
    assert load_workbook(out).sheetnames == list(dcf_xlsx.SHEETS)


def test_inputs_only_on_assumption_sheet_and_colors(exported):
    out, _, _ = exported
    wb = load_workbook(out)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if v is None:
                    continue
                is_formula = isinstance(v, str) and v.startswith("=")
                if ws.title != "가정":
                    assert not isinstance(v, (int, float)), f"{ws.title}!{c.coordinate} 숫자 하드코딩 {v}"
                    if is_formula:
                        # 0·1(수학 상수), 4(ROUND 자릿수)만 허용 — 가정 값은 모두 셀 참조
                        assert _formula_literals(v) <= {"0", "1", "4"}, f"{ws.title}!{c.coordinate}: {v}"
                if is_formula:
                    assert c.font.color.rgb == dcf_xlsx.BLACK, f"{ws.title}!{c.coordinate} 수식은 검정"
                elif ws.title == "가정" and isinstance(v, (int, float)):
                    assert c.font.color.rgb == dcf_xlsx.BLUE, f"가정!{c.coordinate} 입력은 파랑"


def test_sensitivity_uses_closed_formulas(exported):
    out, cells, _ = exported
    wb = load_workbook(out)
    ws = wb["민감도"]
    for line in cells["sens_grid"]:
        for _, coord in line:
            f = ws[coord].value
            assert f.startswith("=IF(") and "SUMPRODUCT(" in f and "NA()" in f
    assert not ws.data_validations.dataValidation
    assert "TABLE(" not in "".join(str(c.value) for r in ws.iter_rows() for c in r)


def test_check_rows_red_when_nonzero(exported):
    out, cells, _ = exported
    ws = load_workbook(out)["DCF"]
    coords = [c for _, c in cells["checks"]]
    rules = [r for rng in ws.conditional_formatting for r in rng.rules
             if any(coords[0] in str(cr) or coords[0] in cr.coord for cr in rng.sqref.ranges)]
    assert rules and rules[0].operator == "notEqual" and rules[0].formula == ["0"]
    assert rules[0].dxf.font.color.rgb == "FFFF0000"


# ------------------------------------------------------------------ LibreOffice 재계산 = 엔진
@pytest.mark.skipif(dcf_xlsx.find_soffice() is None, reason="LibreOffice(soffice) 없음")
def test_libreoffice_recalc_matches_engine(exported, tmp_path):
    out, cells, res = exported
    recalced = dcf_xlsx.recalc_with_libreoffice(out, tmp_path / "lo")
    assert dcf_xlsx.compare(recalced, cells, res) == []


@pytest.mark.skipif(dcf_xlsx.find_soffice() is None, reason="LibreOffice(soffice) 없음")
def test_libreoffice_recalc_end_of_year_variant(tmp_path):
    h, a = make_history(), make_assumptions(cf_timing_adj=0.0, tv_timing_adj=0.0)
    res = compute(h, a)
    out = tmp_path / "eoy.xlsx"
    cells = dcf_xlsx.export(h, a, res, out)
    assert dcf_xlsx.compare(dcf_xlsx.recalc_with_libreoffice(out, tmp_path / "lo"), cells, res) == []


def test_compare_detects_mismatch(exported, tmp_path):
    """비교기가 실제로 틀린 값을 잡는지(엑셀 없이): 캐시값을 직접 넣은 사본으로 확인."""
    out, cells, res = exported
    wb = load_workbook(out)
    bad = copy.deepcopy(res)
    for key in ("revenue", "ebit_reported", "lease_interest", "ebit", "da", "capex", "dnwc", "fcff", "pv"):
        for (sheet, coord), v in zip(cells[key], res[key]):
            wb[sheet][coord].value = v
    for key in ("wacc", "ke", "sum_pv", "tv", "pv_tv", "ev", "net_debt", "nonop", "nci", "equity", "shares",
                "per_share", "base_ebit", "base_ebitda"):
        sheet, coord = cells[key]
        wb[sheet][coord].value = res[key]
    wb[cells["m_ebitda"][0]][cells["m_ebitda"][1]].value = res["ev_ebitda_base"]
    for (s, c), v in zip(cells["sens_wacc"], res["sens_wacc"]):
        wb[s][c].value = v
    for (s, c), v in zip(cells["sens_g"], res["sens_g"]):
        wb[s][c].value = v
    for line, vals in zip(cells["sens_grid"], res["sens_grid"]):
        for (s, c), v in zip(line, vals):
            wb[s][c].value = v
    for s, c in cells["checks"]:
        wb[s][c].value = 0
    good = tmp_path / "good.xlsx"
    wb.save(good)
    assert dcf_xlsx.compare(good, cells, res) == []
    bad["ev"] *= 1.001
    assert any(p.startswith("ev ") for p in dcf_xlsx.compare(good, cells, bad))
