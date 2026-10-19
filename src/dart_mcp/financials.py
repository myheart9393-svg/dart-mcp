"""재무 API(fnlttSinglAcntAll) 결과 정리: 재무제표별 묶기, 핵심 계정 매칭, 비율 계산, 디스크 캐시.

네트워크는 client.py가 맡고, 여기는 순수 함수 + 파일 캐시만 둔다(단위테스트 대상).
캐시: data/fin/<corp_code>_<bsns_year>_<reprt_code>_<fs_div>.json (원본 list 그대로).
"""

from __future__ import annotations

import json
import logging
import re
import time
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
    """'1,234' / '-5678' / '' / '-' → int 또는 None."""
    if value is None:
        return None
    s = str(value).replace(",", "").strip()
    if s in ("", "-"):
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
               ("유형자산의취득", "유형자산취득"), ("처분", "무형")),
    KeyAccount("cash", "현금및현금성자산", ("BS",), ("ifrs-full_CashAndCashEquivalents",),
               ("현금및현금성자산",), ("기초", "기말", "증가", "감소", "환율", "외화")),
)
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
            n = normalize_name(it.get("account_nm"))
            if n in targets or _strip_paren(n) in targets:
                return it, "name_exact"
    for sj in spec.sj_divs:
        for it in ordered(sj):
            n = normalize_name(it.get("account_nm"))
            if any(e in n for e in spec.exclude):
                continue
            if any(t in n for t in targets):
                return it, "name_partial"
    return None, None


def _ratio(num: int | None, den: int | None) -> float | None:
    if num is None or not den:
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


def _annual_entry(row: dict, how: str, label: str, years: list[str]) -> dict:
    return {
        "label": label,
        "values": {years[i]: parse_amount(row.get(f)) for i, (f, _) in enumerate(PERIODS)},
        "matched": {
            "by": how,
            "sj_div": row.get("sj_div"),
            "account_id": row.get("account_id"),
            "account_nm": row.get("account_nm"),
        },
    }


def summarize_key_financials(items: list[dict], bsns_year: str, sector: str = "general") -> dict:
    """원본 list → 핵심 계정 3개년 + 비율. 못 찾은 계정은 값 None, missing 목록에 key.

    sector="financial"이면 revenue는 not_applicable(missing에 넣지 않음), 영업이익률·순이익률은 None,
    financial_accounts에 금융업 계정(순이자이익 등)과 financial_missing을 더한다.
    """
    years = period_years(bsns_year)
    financial = sector == "financial"
    accounts: dict[str, dict] = {}
    missing: list[str] = []
    not_applicable: list[str] = []
    for spec in KEY_ACCOUNTS:
        if financial and spec.key in FINANCIAL_NOT_APPLICABLE:
            accounts[spec.key] = {"label": spec.label, "values": {y: None for y in years}, "matched": None,
                                  "note": "금융업: 해당 개념 없음"}
            not_applicable.append(spec.key)
            continue
        row, how = _match_key(items, spec)
        if row is None:
            accounts[spec.key] = {"label": spec.label, "values": {y: None for y in years}, "matched": None}
            missing.append(spec.key)
            continue
        accounts[spec.key] = _annual_entry(row, how, spec.label, years)

    def v(key: str, y: str) -> int | None:
        return accounts[key]["values"][y]

    ratios = {
        rkey: {"label": label, "values": {y: _ratio(v(num, y), v(den, y)) for y in years}, "formula": f"{num}/{den}"}
        for rkey, label, num, den in RATIOS
    }
    out = {"years": years, "accounts": accounts, "ratios": ratios, "missing": missing}
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
    not_applicable: list[str] = []
    for spec in KEY_ACCOUNTS:
        if financial and spec.key in FINANCIAL_NOT_APPLICABLE:
            accounts[spec.key] = {"label": spec.label, "basis": None, "values": {"current": None, "prior": None},
                                  "matched": None, "note": "금융업: 해당 개념 없음"}
            not_applicable.append(spec.key)
            continue
        row, how = _match_key(items, spec)
        if row is None:
            accounts[spec.key] = {"label": spec.label, "basis": None, "values": {"current": None, "prior": None},
                                  "matched": None}
            missing.append(spec.key)
            continue
        accounts[spec.key] = _interim_entry(row, how, spec.label, reprt_code, period_type)

    def v(key: str, col: str) -> int | None:
        return accounts[key]["values"][col]

    ratios = {
        rkey: {"label": label, "values": {c: _ratio(v(num, c), v(den, c)) for c in ("current", "prior")},
               "formula": f"{num}/{den}"}
        for rkey, label, num, den in RATIOS if rkey in _INTERIM_RATIOS
    }
    out = {"columns": ["current", "prior"], "accounts": accounts, "ratios": ratios, "missing": missing}
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


def load_statements(
    client_factory, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str, data_dir: Path | None = None
) -> dict:
    """캐시 → 없으면 client.get_financial_statements로 받아 저장.

    반환: {"status", "message", "rcept_no", "list", "cached"}. status "013"(데이터 없음)은 캐시하지 않는다
    (아직 제출 전인 보고서가 나중에 생길 수 있으므로).
    client_factory는 캐시 미스일 때만 부른다(키 없는 환경에서도 캐시로 동작하게).
    """
    path = fin_cache_path(corp_code, bsns_year, reprt_code, fs_div, data_dir)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            log.info("fin cache hit: %s", path.name)
            return {**payload, "cached": True}
        except (OSError, ValueError) as exc:
            log.warning("fin cache %s unreadable (%s); re-fetching", path.name, exc)

    client: DartClient = client_factory()
    data = client.get_financial_statements(corp_code, bsns_year, reprt_code, fs_div)
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
