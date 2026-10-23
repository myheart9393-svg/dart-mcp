"""재무 API(fnlttSinglAcntAll) 결과 정리: 재무제표별 묶기, 핵심 계정 매칭, 비율 계산, 디스크 캐시.

네트워크는 client.py가 맡고, 여기는 순수 함수 + 파일 캐시만 둔다(단위테스트 대상).
캐시: data/fin/<corp_code>_<bsns_year>_<reprt_code>_<fs_div>.json (원본 list 그대로).
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .cache import default_data_dir

if TYPE_CHECKING:
    from .client import DartClient

log = logging.getLogger(__name__)

REPRT_CODES = {"11011": "사업보고서", "11012": "반기보고서", "11013": "1분기보고서", "11014": "3분기보고서"}
FS_DIVS = {"CFS": "연결재무제표", "OFS": "재무제표(별도)"}
STATEMENTS = ("BS", "IS", "CIS", "CF")  # SCE(자본변동표)는 행이 중복·과다해 기본 제외
# 당기·전기·전전기 금액 필드 → bsns_year에서 뺄 연수
PERIODS = (("thstrm_amount", 0), ("frmtrm_amount", 1), ("bfefrmtrm_amount", 2))
NO_DATA_STATUS = "013"


def parse_amount(value: str | None) -> int | None:
    """'1,234' / '-5678' → int. '-'는 공시 관행상 0(해당 금액 없음), ''·None은 값 없음(None)."""
    if value is None:
        return None
    s = str(value).replace(",", "").strip()
    if s == "-":
        return 0
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def period_years(bsns_year: str) -> list[str]:
    """'2024' → ['2024', '2023', '2022'] (당기·전기·전전기)."""
    y = int(bsns_year)
    return [str(y - back) for _, back in PERIODS]


def group_statements(items: list[dict], bsns_year: str, sj_divs: tuple[str, ...] = STATEMENTS) -> dict:
    """원본 list → {sj_div: {"sj_nm", "rows": [...]}}. 각 행에 연도별 숫자 amount_krw를 붙인다."""
    years = period_years(bsns_year)
    out: dict[str, dict] = {}
    for it in sorted(items, key=lambda x: (x.get("sj_div", ""), int(x.get("ord") or 0))):
        sj = it.get("sj_div")
        if sj not in sj_divs:
            continue
        group = out.setdefault(sj, {"sj_nm": it.get("sj_nm"), "rows": []})
        row = {
            "account_nm": it.get("account_nm"),
            "account_id": it.get("account_id"),
            **{f: it.get(f) for f, _ in PERIODS},
            "amount_krw": {years[i]: parse_amount(it.get(f)) for i, (f, _) in enumerate(PERIODS)},
        }
        group["rows"].append(row)
    return out


# --------------------------------------------------------------------------- 핵심 계정 매칭
@dataclass(frozen=True)
class KeyAccount:
    key: str
    label: str
    sj_divs: tuple[str, ...]  # 앞의 것이 우선 (IS가 있으면 CIS보다 먼저)
    ids: tuple[str, ...]
    names: tuple[str, ...]  # 정규화 후 완전일치 → 부분일치 순으로 쓴다
    exclude: tuple[str, ...] = field(default=())  # 부분일치 때 이 말이 들어가면 제외
    exclude_ids: tuple[str, ...] = field(default=())  # 이름 매칭 때 이 account_id인 행은 제외


_PL = ("IS", "CIS")
KEY_ACCOUNTS: tuple[KeyAccount, ...] = (
    KeyAccount("revenue", "매출액", _PL, ("ifrs-full_Revenue",),
               ("매출액", "수익(매출액)", "영업수익", "매출"), ("원가", "총이익", "채권", "할인", "에누리")),
    KeyAccount("operating_income", "영업이익", _PL, ("dart_OperatingIncomeLoss",),
               ("영업이익", "영업이익(손실)", "영업손익", "영업손실"), ("외", "계속", "중단")),
    KeyAccount("net_income", "당기순이익", _PL, ("ifrs-full_ProfitLoss",),
               ("당기순이익", "당기순이익(손실)", "당기순손익", "당기순손실"), ("지배", "비지배", "계속", "중단", "주당")),
    KeyAccount("total_assets", "자산총계", ("BS",), ("ifrs-full_Assets",), ("자산총계",), ("유동", "부채")),
    KeyAccount("total_liabilities", "부채총계", ("BS",), ("ifrs-full_Liabilities",), ("부채총계",), ("자본", "유동")),
    KeyAccount("total_equity", "자본총계", ("BS",), ("ifrs-full_Equity",), ("자본총계",), ("부채", "지배")),
    KeyAccount("operating_cf", "영업활동현금흐름", ("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
               ("영업활동현금흐름", "영업활동으로인한현금흐름"), ("창출", "자산부채", "기타")),
    KeyAccount("investing_cf", "투자활동현금흐름", ("CF",), ("ifrs-full_CashFlowsFromUsedInInvestingActivities",),
               ("투자활동현금흐름", "투자활동으로인한현금흐름"), ("기타",)),
    KeyAccount("capex", "유형자산취득(CAPEX 대용)", ("CF",),
               ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                "ifrs-full_PurchaseOfPropertyPlantAndEquipment"),
               ("유형자산의취득", "유형자산취득", "유형자산의증가", "설비자산의취득", "유형자산취득액"), ("처분", "무형")),
    KeyAccount("cash", "현금및현금성자산", ("BS",), ("ifrs-full_CashAndCashEquivalents",),
               ("현금및현금성자산",), ("기초", "기말", "증가", "감소", "환율", "외화")),
    # 지배주주 기준 ROE용. 종속회사가 없는 회사(별도만 공시)는 없는 게 정상이라 missing이 아닌 optional로 둔다.
    KeyAccount("net_income_parent", "당기순이익(지배주주)", _PL, ("ifrs-full_ProfitLossAttributableToOwnersOfParent",),
               ("지배기업소유주지분", "지배기업의소유주지분", "지배주주순이익", "지배기업소유주귀속당기순이익"),
               ("비지배", "주당", "포괄"), ("ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent",)),
    KeyAccount("equity_parent", "자본(지배주주)", ("BS",), ("ifrs-full_EquityAttributableToOwnersOfParent",),
               ("지배기업소유주지분", "지배기업의소유주지분", "지배기업의소유주에게귀속되는자본", "지배주주지분"),
               ("비지배",)),
)
OPTIONAL_ACCOUNTS = ("net_income_parent", "equity_parent")
# 현금흐름표는 있는데 이 계정 행이 아예 없으면 "취득 없음"으로 보고 0을 넣는다(missing이 아니라 assumed_zero).
# 소규모 회사는 해당 연도에 유형자산을 사지 않으면 행 자체를 안 둔다(미래아이앤지·얼라인드제네틱스 2025 실측: 원문에도 취득 0건).
ASSUMED_ZERO_ACCOUNTS = {"capex": "현금흐름표에 유형자산 취득 계정 없음(취득 없음으로 간주)"}
# BS에 현금및현금성자산 행이 없는 회사(은행: "현금 및 예치금")는 현금흐름표의 기말 현금으로 대체한다.
CASH_CF_FALLBACK = KeyAccount("cash", "현금및현금성자산", ("CF",), ("ifrs-full_CashAndCashEquivalents",),
                              ("기말현금및현금성자산", "기말의현금및현금성자산"))

# --------------------------------------------------------------------------- 금융업
# 금융업(은행·보험·증권·금융지주)은 "매출액"이 없고 영업이익률·순이익률·부채비율이 제조업과 뜻이 다르다.
# 업종은 기업개황(company.json)의 induty_code(KSIC)로 1차 판단한다: 64 금융업, 65 보험·연금, 66 금융 서비스.
# 단 64992(지주회사)는 SK·LG 같은 비금융 지주도 같은 코드이므로 손익계산서에 금융 계정이 있는지로 확인한다.
FINANCIAL_KSIC_PREFIXES = ("64", "65", "66")
HOLDING_KSIC = "64992"
_FIN_MARKER_IDS = ("ifrs-full_InterestRevenueExpense", "ifrs-full_InsuranceRevenue",
                   "ifrs-full_FeeAndCommissionIncomeExpense")
FINANCIAL_ACCOUNTS: tuple[KeyAccount, ...] = (
    KeyAccount("net_interest_income", "순이자이익", _PL, ("ifrs-full_InterestRevenueExpense",),
               ("순이자손익", "순이자이익", "이자손익"), ("보험", "외")),
    KeyAccount("net_fee_income", "순수수료이익", _PL, ("ifrs-full_FeeAndCommissionIncomeExpense",),
               ("순수수료손익", "순수수료이익", "수수료손익"), ("보험",)),
    KeyAccount("insurance_revenue", "보험수익", _PL, ("ifrs-full_InsuranceRevenue",), ("보험수익",), ("재보험", "금융")),
    KeyAccount("credit_loss_provision", "신용손실충당금전입", _PL,
               ("ifrs-full_ImpairmentLossImpairmentGainAndReversalOfImpairmentLossDeterminedInAccordanceWithIFRS9",),
               ("신용손실충당금전입액", "신용손실충당금(전)환입액", "대손충당금전입액"), ("반영전",)),
)
FINANCIAL_NOT_APPLICABLE = ("revenue",)  # 금융업에서 개념이 없는 핵심 계정
FINANCIAL_SKIP_RATIOS = ("operating_margin", "net_margin")
FINANCIAL_WARNING = (
    "금융업 회사로 판단했다({reason}). 매출액 개념이 없어 revenue는 계산하지 않고(not_applicable), "
    "영업이익률·순이익률도 비운다. 대신 financial_accounts에 순이자이익·순수수료이익·보험수익·신용손실충당금전입을 준다. "
    "부채비율은 예수부채·보험계약부채가 포함돼 제조업과 비교할 수 없고, 유형자산취득(capex)은 규모가 작아 의미가 약하다. "
    "보고서에는 '금융업 기준'임을 밝히고 일반 기업과 같은 표에서 비교하지 않는다."
)


def detect_sector(induty_code: str | None, items: list[dict]) -> dict:
    """{"sector": "financial"|"general"|"unknown", "induty_code", "reason"}.

    - induty_code가 64/65/66으로 시작하고 64992(지주회사)가 아니면 financial.
    - 64992면 손익계산서에 금융 계정(순이자손익·보험수익·순수수료손익 account_id)이 있고
      ifrs-full_Revenue(매출액)가 없을 때만 financial (비금융 지주회사와 구분).
    - induty_code를 모르면(조회 실패) 재무제표 신호만으로 판단하고 reason에 적는다.
    """
    code = (induty_code or "").strip()
    ids = {it.get("account_id") for it in items if it.get("sj_div") in _PL}
    fin_signal = any(m in ids for m in _FIN_MARKER_IDS) and "ifrs-full_Revenue" not in ids
    if code.startswith(FINANCIAL_KSIC_PREFIXES) and code != HOLDING_KSIC:
        return {"sector": "financial", "induty_code": code, "reason": f"induty_code {code}, KSIC 64–66 금융·보험"}
    if code == HOLDING_KSIC:
        if fin_signal:
            return {"sector": "financial", "induty_code": code,
                    "reason": f"induty_code {code}(지주회사) + 손익계산서에 금융 계정 있고 매출액 계정 없음"}
        return {"sector": "general", "induty_code": code, "reason": f"induty_code {code}(지주회사), 금융 계정 신호 없음"}
    if not code:
        if fin_signal:
            return {"sector": "financial", "induty_code": None, "reason": "업종코드 미확인, 재무제표 금융 계정 신호"}
        return {"sector": "unknown", "induty_code": None, "reason": "업종코드 미확인"}
    return {"sector": "general", "induty_code": code, "reason": f"induty_code {code}"}


def _match_key(items: list[dict], spec: KeyAccount) -> tuple[dict | None, str | None]:
    """match_account + cash는 BS에 없을 때 CF 기말현금으로 대체."""
    row, how = match_account(items, spec)
    if row is None and spec.key == "cash":
        row, how = match_account(items, CASH_CF_FALLBACK)
        if row is not None:
            how = f"{how}(CF 기말현금 대체)"
    return row, how


def _mark_financial_ratios(ratios: dict) -> None:
    for rkey in FINANCIAL_SKIP_RATIOS:
        if rkey in ratios:
            ratios[rkey]["values"] = {k: None for k in ratios[rkey]["values"]}
            ratios[rkey]["note"] = "금융업: 매출액 개념이 없어 계산하지 않음"


def normalize_name(name: str | None) -> str:
    """공백·중점·로마숫자 머리표 제거. '  Ⅰ. 매출액 ' → '매출액'."""
    s = re.sub(r"\s+", "", name or "")
    s = re.sub(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+|\d+)\.", "", s)
    return s.replace("·", "")


def _strip_paren(s: str) -> str:
    """'영업이익(손실)' → '영업이익', '수익(매출액)' → '수익'."""
    return re.sub(r"\(.*?\)", "", s)


def match_account(items: list[dict], spec: KeyAccount) -> tuple[dict | None, str | None]:
    """spec에 맞는 행 하나와 매칭 방식("account_id"/"name_exact"/"name_partial")을 돌려준다.

    1) sj_div 우선순위대로 account_id 완전일치
    2) 계정명 정규화 후 완전일치 (괄호 제거본 포함)
    3) 계정명 부분일치 (exclude 단어가 들어간 이름은 제외)
    같은 단계에서는 sj_div 우선순위 → ord 순으로 첫 행.
    """
    def ordered(sj: str) -> list[dict]:
        return sorted((x for x in items if x.get("sj_div") == sj), key=lambda x: int(x.get("ord") or 0))

    for sj in spec.sj_divs:
        for it in ordered(sj):
            if it.get("account_id") in spec.ids:
                return it, "account_id"
    targets = {normalize_name(n) for n in spec.names}
    for sj in spec.sj_divs:
        for it in ordered(sj):
            if it.get("account_id") in spec.exclude_ids:
                continue
            n = normalize_name(it.get("account_nm"))
            if n in targets or _strip_paren(n) in targets:
                return it, "name_exact"
    for sj in spec.sj_divs:
        for it in ordered(sj):
            n = normalize_name(it.get("account_nm"))
            if it.get("account_id") in spec.exclude_ids or any(e in n for e in spec.exclude):
                continue
            if any(t in n for t in targets):
                return it, "name_partial"
    return None, None


def _has_statement(items: list[dict], sj_divs: tuple[str, ...]) -> bool:
    return any(it.get("sj_div") in sj_divs for it in items)


def _ratio(num: float | None, den: float | None, equity_den: bool = False) -> float | None:
    """num/den×100. equity_den=True(분모가 자본)이면 분모가 음수(자본잠식)일 때 None — 부호가 뒤집혀 오해를 부른다."""
    if num is None or not den:
        return None
    if equity_den and den < 0:
        return None
    return round(num / den * 100, 2)


RATIOS = (
    ("operating_margin", "영업이익률(%)", "operating_income", "revenue"),
    ("net_margin", "순이익률(%)", "net_income", "revenue"),
    ("debt_ratio", "부채비율(%)", "total_liabilities", "total_equity"),
    ("equity_ratio", "자기자본비율(%)", "total_equity", "total_assets"),
    ("roe", "ROE(%)", "net_income", "total_equity"),
    ("roa", "ROA(%)", "net_income", "total_assets"),
)
# 자본(total_equity)이 분자·분모에 들어가는 비율: 자본잠식(자본 음수)이면 None
EQUITY_RATIOS = ("debt_ratio", "equity_ratio", "roe")
CAPITAL_IMPAIRMENT = "capital_impairment"
_PERIOD_LABEL_FIELDS = ("thstrm_nm", "thstrm_dt", "frmtrm_nm", "frmtrm_dt", "bfefrmtrm_nm", "bfefrmtrm_dt")


def _annual_entry(row: dict, how: str, label: str, years: list[str]) -> dict:
    return {
        "label": label,
        "values": {years[i]: parse_amount(row.get(f)) for i, (f, _) in enumerate(PERIODS)},
        "matched": {
            "by": how,
            "sj_div": row.get("sj_div"),
            "account_id": row.get("account_id"),
            "account_nm": row.get("account_nm"),
            **{f: row.get(f) for f in _PERIOD_LABEL_FIELDS},
        },
    }


def _average_balance(values: dict, years: list[str], i: int) -> tuple[float | None, str, bool]:
    """(평균잔액, 기준, 음수포함). 기초 = 같은 응답의 직전 연도 기말. 전전기(마지막 열)는 기초가 없어 기말 기준."""
    end = values.get(years[i])
    begin = values.get(years[i + 1]) if i + 1 < len(years) else None
    if end is None:
        return None, "n/a", False
    if begin is None:
        return float(end), "ending", end < 0
    return (begin + end) / 2, "average", end < 0 or begin < 0


def _return_ratio(accounts: dict, years: list[str], num_key: str, den_key: str,
                  equity_den: bool) -> tuple[dict, dict]:
    """ROE·ROA: 분자 / (기초+기말)/2. equity_den이면 기초·기말 중 하나라도 음수(자본잠식)일 때 None."""
    values, basis = {}, {}
    for i, y in enumerate(years):
        den, how, negative = _average_balance(accounts[den_key]["values"], years, i)
        basis[y] = how
        values[y] = None if (equity_den and negative) else _ratio(accounts[num_key]["values"][y], den, equity_den)
    return values, basis


def _months_between(start: str, end: str) -> int | None:
    try:
        sy, sm, _ = (int(x) for x in start.split("."))
        ey, em, _ = (int(x) for x in end.split("."))
    except ValueError:
        return None
    return (ey - sy) * 12 + (em - sm) + 1


def period_labels(items: list[dict], years: list[str], acc_mt: str | None) -> tuple[list[dict], list[str]]:
    """결산기 라벨 [{year, name, range, range_source}]과 경고 note 목록.

    fnlttSinglAcntAll은 thstrm_nm("제 56 기")만 주고 *_dt 필드는 없는 게 보통이다(2024·2025 응답 확인).
    *_dt가 있으면 그걸 쓰고(12개월이 아니면 note), 없으면 기업개황 acc_mt(결산월)로 12개월 기간을 추정한다.
    """
    sample = next((it for it in items if it.get("sj_div") in ("IS", "CIS", "CF") and it.get("thstrm_nm")), None)
    sample = sample or next((it for it in items if it.get("thstrm_nm")), {})
    mt = (acc_mt or "").strip()
    mm = int(mt) if mt.isdigit() and 1 <= int(mt) <= 12 else None
    periods, notes = [], []
    for (amount_field, _), y in zip(PERIODS, years):
        prefix = amount_field.removesuffix("_amount")
        name = re.sub(r"\s+", "", sample.get(f"{prefix}_nm") or "") or None
        dt = (sample.get(f"{prefix}_dt") or "").strip()
        entry = {"year": y, "name": name, "range": None, "range_source": None}
        if "~" in dt:
            entry.update(range=dt.replace(" ", ""), range_source="api(*_dt)")
            months = _months_between(*(d.strip() for d in dt.split("~", 1)))
            if months is not None and months != 12:
                notes.append(f"{y}({name}) 회계기간이 {months}개월이다({dt}). 연간 비교 시 주의.")
        elif mm is not None:
            end_y = int(y)
            start_y, start_m = (end_y, 1) if mm == 12 else (end_y - 1, mm + 1)
            last = calendar.monthrange(end_y, mm)[1]
            entry.update(range=f"{start_y}.{start_m:02d}.01~{end_y}.{mm:02d}.{last:02d}",
                         range_source="acc_mt(결산월로 추정, 12개월 여부는 API로 확인 불가)")
        periods.append(entry)
    if mm is not None and mm != 12:
        notes.append(f"{mm}월 결산 회사다(periods.range 참조). 12월 결산 회사와 같은 연도로 나란히 비교하면 "
                     "기간이 어긋난다.")
    return periods, notes


def summarize_key_financials(items: list[dict], bsns_year: str, sector: str = "general",
                             fs_div: str = "CFS", acc_mt: str | None = None) -> dict:
    """원본 list → 핵심 계정 3개년 + 비율. 못 찾은 계정은 값 None, missing 목록에 key.

    - net_income_parent·equity_parent는 optional(없어도 missing 아님, optional_missing에 적음).
      둘 다 있으면 ROE·ROA 분자는 지배주주 순이익·ROE 분모는 지배주주 자본, 아니면 총액 기준.
      분모는 (기초+기말)/2, 전전기는 기초가 없어 기말 기준.
    - 자본총계가 음수인 연도가 있으면 flags에 "capital_impairment"와 note. 자본이 들어가는 비율은 None.
    - periods: 결산기 라벨(제N기, 기간). 12월 결산이 아니거나 12개월이 아니면 note에 적는다.

    sector="financial"이면 revenue는 not_applicable(missing에 넣지 않음), 영업이익률·순이익률은 None,
    financial_accounts에 금융업 계정(순이자이익 등)과 financial_missing을 더한다.
    """
    years = period_years(bsns_year)
    financial = sector == "financial"
    accounts: dict[str, dict] = {}
    missing: list[str] = []
    assumed_zero: list[str] = []
    not_applicable: list[str] = []
    for spec in KEY_ACCOUNTS:
        if financial and spec.key in FINANCIAL_NOT_APPLICABLE:
            accounts[spec.key] = {"label": spec.label, "values": {y: None for y in years}, "matched": None,
                                  "note": "금융업: 해당 개념 없음"}
            not_applicable.append(spec.key)
            continue
        row, how = _match_key(items, spec)
        if row is None and spec.key in ASSUMED_ZERO_ACCOUNTS and _has_statement(items, spec.sj_divs):
            accounts[spec.key] = {"label": spec.label, "values": {y: 0 for y in years}, "matched": "assumed_zero",
                                  "note": ASSUMED_ZERO_ACCOUNTS[spec.key]}
            assumed_zero.append(spec.key)
            continue
        if row is None:
            accounts[spec.key] = {"label": spec.label, "values": {y: None for y in years}, "matched": None}
            if spec.key not in OPTIONAL_ACCOUNTS:
                missing.append(spec.key)
            continue
        accounts[spec.key] = _annual_entry(row, how, spec.label, years)

    def v(key: str, y: str) -> int | None:
        return accounts[key]["values"][y]

    impaired = [y for y in years if (v("total_equity", y) or 0) < 0]
    ratios: dict[str, dict] = {}
    for rkey, label, num, den in RATIOS:
        if rkey in ("roe", "roa"):
            continue
        vals = {y: (None if rkey in EQUITY_RATIOS and y in impaired
                    else _ratio(v(num, y), v(den, y), den == "total_equity")) for y in years}
        ratios[rkey] = {"label": label, "values": vals, "formula": f"{num}/{den}"}

    parent = all(accounts[k]["matched"] is not None for k in OPTIONAL_ACCOUNTS)
    ni, eq = ("net_income_parent", "equity_parent") if parent else ("net_income", "total_equity")
    scope = "지배주주 기준" if parent else ("연결 총액 기준" if fs_div == "CFS" else "별도 재무제표 기준")
    avg_note = f"평균잔액((기초+기말)/2, 기초=전기말), 전전기({years[-1]})는 기말 기준"
    for rkey, label, den in (("roe", "ROE(%)", eq), ("roa", "ROA(%)", "total_assets")):
        vals, basis = _return_ratio(accounts, years, ni, den, den in ("total_equity", "equity_parent"))
        ratios[rkey] = {"label": label, "values": vals, "denominator_basis": basis, "basis": scope,
                        "formula": f"{ni} / avg({den}) — {scope}, {avg_note}"}
    ratios = {rkey: ratios[rkey] for rkey, *_ in RATIOS}  # 원래 순서

    periods, notes = period_labels(items, years, acc_mt)
    impaired_parent = [y for y in years if parent and (v("equity_parent", y) or 0) < 0 and y not in impaired]
    flags: list[str] = []
    if impaired or impaired_parent:
        flags.append(CAPITAL_IMPAIRMENT)
        msg = (f"자본잠식(자본총계 음수): {', '.join(impaired)}. " if impaired else "") + (
            f"지배주주 자본 음수: {', '.join(impaired_parent)}. " if impaired_parent else "")
        notes.insert(0, msg + "자본이 음수인 연도(ROE는 기초 포함)의 부채비율·자기자본비율·ROE는 부호가 뒤집혀 "
                     "의미가 없어 계산하지 않음(None).")
    out = {"years": years, "periods": periods, "accounts": accounts, "ratios": ratios, "missing": missing,
           "assumed_zero": assumed_zero, "optional": list(OPTIONAL_ACCOUNTS),
           "optional_missing": [k for k in OPTIONAL_ACCOUNTS if accounts[k]["matched"] is None],
           "flags": flags}
    if notes:
        out["note"] = " ".join(notes)
    if financial:
        _mark_financial_ratios(ratios)
        fin: dict[str, dict] = {}
        for spec in FINANCIAL_ACCOUNTS:
            row, how = match_account(items, spec)
            fin[spec.key] = (_annual_entry(row, how, spec.label, years) if row is not None
                             else {"label": spec.label, "values": {y: None for y in years}, "matched": None})
        out.update(financial_accounts=fin, not_applicable=not_applicable,
                   financial_missing=[k for k, a in fin.items() if a["matched"] is None])
    return out


# --------------------------------------------------------------------------- 반기·분기
# 분기·반기 보고서 fnlttSinglAcntAll 필드 (2026 반기 실제 응답으로 확인):
#   IS/CIS: thstrm_amount=당분기(3개월), thstrm_add_amount=당기누적, frmtrm_q_amount=전년 동분기(3개월),
#           frmtrm_add_amount=전년 동기누적
#   CF:     thstrm_amount=당기누적, frmtrm_q_amount=전년 동기누적 (3개월 값은 없음)
#   BS:     thstrm_amount=당분기말, frmtrm_amount=전기말(직전 사업연도말 — 전년 동기말이 아님)
INTERIM_PERIOD_TYPES = ("cumulative", "quarter")
_INTERIM_FIELDS = {
    ("flow", "cumulative"): ("thstrm_add_amount", "frmtrm_add_amount"),
    ("flow", "quarter"): ("thstrm_amount", "frmtrm_q_amount"),
    ("cf", "cumulative"): ("thstrm_amount", "frmtrm_q_amount"),
    ("cf", "quarter"): (None, None),
    ("bs", "cumulative"): ("thstrm_amount", "frmtrm_amount"),
    ("bs", "quarter"): ("thstrm_amount", "frmtrm_amount"),
}
_INTERIM_RATIOS = ("operating_margin", "net_margin", "debt_ratio", "equity_ratio")  # ROE·ROA는 연환산 문제로 제외


def _statement_kind(sj_div: str | None) -> str:
    return {"BS": "bs", "CF": "cf"}.get(sj_div or "", "flow")


def summarize_interim_financials(items: list[dict], reprt_code: str, period_type: str,
                                 sector: str = "general") -> dict:
    """분기·반기 원본 list → 핵심 계정의 {current, prior} 두 값.

    flow(손익) 계정의 prior는 전년 동기(누적 또는 동분기), BS 계정의 prior는 전기말이다.
    CF는 누적만 공시되므로 period_type="quarter"면 값이 None이다.
    1분기보고서는 누적=당분기이므로 thstrm_add_amount가 비어 있으면 thstrm_amount로 채운다.
    """
    if period_type not in INTERIM_PERIOD_TYPES:
        raise ValueError(f"분기·반기 period_type은 {INTERIM_PERIOD_TYPES} 중 하나: {period_type!r}")
    financial = sector == "financial"
    accounts: dict[str, dict] = {}
    missing: list[str] = []
    assumed_zero: list[str] = []
    not_applicable: list[str] = []
    for spec in KEY_ACCOUNTS:
        if financial and spec.key in FINANCIAL_NOT_APPLICABLE:
            accounts[spec.key] = {"label": spec.label, "basis": None, "values": {"current": None, "prior": None},
                                  "matched": None, "note": "금융업: 해당 개념 없음"}
            not_applicable.append(spec.key)
            continue
        row, how = _match_key(items, spec)
        if row is None and spec.key in ASSUMED_ZERO_ACCOUNTS and _has_statement(items, spec.sj_divs):
            zero = None if period_type == "quarter" else 0  # CF는 누적만 공시: quarter면 다른 CF 계정처럼 None
            accounts[spec.key] = {"label": spec.label, "basis": None, "values": {"current": zero, "prior": zero},
                                  "matched": "assumed_zero", "note": ASSUMED_ZERO_ACCOUNTS[spec.key]}
            assumed_zero.append(spec.key)
            continue
        if row is None:
            accounts[spec.key] = {"label": spec.label, "basis": None, "values": {"current": None, "prior": None},
                                  "matched": None}
            if spec.key not in OPTIONAL_ACCOUNTS:
                missing.append(spec.key)
            continue
        accounts[spec.key] = _interim_entry(row, how, spec.label, reprt_code, period_type)

    def v(key: str, col: str) -> int | None:
        return accounts[key]["values"][col]

    cols = ("current", "prior")
    impaired = [c for c in cols if (v("total_equity", c) or 0) < 0]
    ratios = {
        rkey: {"label": label, "formula": f"{num}/{den}",
               "values": {c: (None if rkey in EQUITY_RATIOS and c in impaired
                              else _ratio(v(num, c), v(den, c), den == "total_equity")) for c in cols}}
        for rkey, label, num, den in RATIOS if rkey in _INTERIM_RATIOS
    }
    out = {"columns": list(cols), "accounts": accounts, "ratios": ratios, "missing": missing, "assumed_zero": assumed_zero,
           "flags": [CAPITAL_IMPAIRMENT] if impaired else []}
    if impaired:
        out["note"] = f"자본잠식(자본총계 음수): {', '.join(impaired)}. 부채비율·자기자본비율은 계산하지 않음(None)."
    if financial:
        _mark_financial_ratios(ratios)
        fin: dict[str, dict] = {}
        for spec in FINANCIAL_ACCOUNTS:
            row, how = match_account(items, spec)
            fin[spec.key] = (_interim_entry(row, how, spec.label, reprt_code, period_type) if row is not None
                             else {"label": spec.label, "basis": None, "values": {"current": None, "prior": None},
                                   "matched": None})
        out.update(financial_accounts=fin, not_applicable=not_applicable,
                   financial_missing=[k for k, a in fin.items() if a["matched"] is None])
    return out


def _interim_entry(row: dict, how: str | None, label: str, reprt_code: str, period_type: str) -> dict:
    """분기·반기 행 하나 → {label, basis, values{current, prior}, fields, matched}."""
    kind = _statement_kind(row.get("sj_div"))
    cur_f, prior_f = _INTERIM_FIELDS[(kind, period_type)]
    cur = parse_amount(row.get(cur_f)) if cur_f else None
    prior = parse_amount(row.get(prior_f)) if prior_f else None
    if kind == "flow" and period_type == "cumulative" and reprt_code == "11013":
        cur = cur if cur is not None else parse_amount(row.get("thstrm_amount"))
        prior = prior if prior is not None else parse_amount(row.get("frmtrm_q_amount"))
    basis = {"bs": "balance(당기말 vs 전기말)", "cf": "cumulative(누적만 공시)"}.get(
        kind, f"{period_type}(전년 동기 비교)")
    if kind == "cf" and "CF 기말현금" in (how or ""):
        # 현금흐름표의 기말 현금은 잔액: thstrm=당기말, frmtrm_q=전년 동기말 (BS 비교열인 전기말과 다르다)
        cur_f, prior_f = "thstrm_amount", "frmtrm_q_amount"
        cur, prior = parse_amount(row.get(cur_f)), parse_amount(row.get(prior_f))
        basis = "balance(CF 기말현금: 당기말 vs 전년 동기말)"
    elif kind == "cf" and period_type == "quarter":
        basis = "n/a(현금흐름표는 누적만 공시)"
    return {
        "label": label,
        "basis": basis,
        "values": {"current": cur, "prior": prior},
        "fields": {"current": cur_f, "prior": prior_f},
        "matched": {"by": how, "sj_div": row.get("sj_div"), "account_id": row.get("account_id"),
                    "account_nm": row.get("account_nm"), "thstrm_nm": row.get("thstrm_nm")},
    }


# --------------------------------------------------------------------------- 캐시
def fin_cache_path(corp_code: str, bsns_year: str, reprt_code: str, fs_div: str, data_dir: Path | None = None) -> Path:
    base = Path(data_dir) if data_dir else default_data_dir()
    return base / "fin" / f"{corp_code}_{bsns_year}_{reprt_code}_{fs_div}.json"


FIN_MAX_AGE_DAYS = 90


def count_changed_accounts(old: list[dict], new: list[dict]) -> int:
    """두 응답에서 금액이 달라졌거나 새로 생기거나 없어진 계정 수 (sj_div·account_id·계정명·ord 기준)."""
    def table(items: list[dict]) -> dict:
        out: dict[tuple, Counter] = {}
        for it in items:
            key = (it.get("sj_div"), it.get("account_id"), normalize_name(it.get("account_nm")), it.get("ord"))
            out.setdefault(key, Counter())[tuple(parse_amount(it.get(f)) for f, _ in PERIODS)] += 1
        return out
    a, b = table(old), table(new)
    return sum(1 for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def load_statements(
    client_factory, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str, data_dir: Path | None = None,
    refresh: bool = False,
) -> dict:
    """캐시 → 없거나 90일 지났거나 refresh=True면 client.get_financial_statements로 받아 저장.

    반환: {"status", "message", "rcept_no", "list", "cached"}. status "013"(데이터 없음)은 캐시하지 않는다
    (아직 제출 전인 보고서가 나중에 생길 수 있으므로).
    client_factory는 캐시를 못 쓸 때만 부른다(키 없는 환경에서도 캐시로 동작하게). 만료로 재조회하다
    실패하면(키 없음·네트워크) 옛 캐시를 stale=True로 돌려준다. refresh=True의 실패는 그대로 올린다.
    재조회 결과가 캐시와 다르면 바뀐 계정 수를 stderr 로그로 남기고 changed_accounts에 적는다.
    """
    path = fin_cache_path(corp_code, bsns_year, reprt_code, fs_div, data_dir)
    old: dict | None = None
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("fin cache %s unreadable (%s); re-fetching", path.name, exc)
    if old is not None:
        age_days = (time.time() - float(old.get("fetched_at") or 0)) / 86400
        if not refresh and age_days < FIN_MAX_AGE_DAYS:
            log.info("fin cache hit: %s", path.name)
            return {**old, "cached": True}
        log.info("fin cache %s: %s", path.name, "refresh=True" if refresh else f"{age_days:.0f}일 경과, 재조회")

    try:
        client: DartClient = client_factory()
        data = client.get_financial_statements(corp_code, bsns_year, reprt_code, fs_div)
    except Exception as exc:  # noqa: BLE001 — 만료 재조회 실패가 캐시 사용을 막지 않게
        if old is None or refresh:
            raise
        log.warning("fin re-fetch %s failed (%s); using stale cache", path.name, exc)
        return {**old, "cached": True, "stale": True}
    items = data.get("list") or []
    payload = {
        "status": str(data.get("status")),
        "message": str(data.get("message", "")),
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
        "rcept_no": items[0].get("rcept_no") if items else None,
        "fetched_at": time.time(),
        "list": items,
    }
    if old is not None:
        changed = count_changed_accounts(old.get("list") or [], items)
        if changed:
            log.warning("fin cache %s: 재조회 결과 %d개 계정이 캐시와 다름 (rcept_no %s → %s)",
                        path.name, changed, old.get("rcept_no"), payload["rcept_no"])
        payload["changed_accounts"] = changed
    if payload["status"] != NO_DATA_STATUS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {**payload, "cached": False}


COMPANY_MAX_AGE_DAYS = 30


def load_company(client_factory, corp_code: str, data_dir: Path | None = None) -> dict | None:
    """기업개황(company.json) 캐시 → 없거나 30일 지났으면 재조회. 실패하면 None (업종 판단은 재무제표 신호로)."""
    base = Path(data_dir) if data_dir else default_data_dir()
    path = base / "company" / f"{corp_code}.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(payload.get("fetched_at", 0)) < COMPANY_MAX_AGE_DAYS * 86400:
                return payload["company"]
        except (OSError, ValueError, KeyError):
            pass
    try:
        company = client_factory().get_company(corp_code)
    except Exception as exc:  # noqa: BLE001 — 업종 조회 실패가 재무 조회를 막지 않게
        log.warning("company.json %s failed: %s", corp_code, exc)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": time.time(), "company": company}, ensure_ascii=False), encoding="utf-8")
    return company
