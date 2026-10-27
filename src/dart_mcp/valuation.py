"""가치평가 공시(합병·분할·영업양수도·주식교환·증권신고서) 찾기와 사례 JSON 검증.

공시 구조(2026-10 실측):
- 주요사항보고서(B001)는 API ZIP에 본문 XML만 있다. 외부평가기관의 평가의견서 첨부는 들어 있지 않고,
  평가의견서를 고친 [첨부정정] 접수번호는 원문 요청이 status=014로 실패한다. 그래서 본문의 "외부평가에 관한 사항"
  표(5행)와 결론만 얻을 수 있다 → source_grade="summary".
- 증권신고서(C001 지분증권, C004 합병등)는 평가 내용(할인율·영구성장률·베타·멀티플)이 본문 섹션에 그대로 있다
  → source_grade="full".
- list.json은 corp_code 없이 조회하면 기간이 3개월로 제한되고, pblntf_ty를 함께 주면 pblntf_detail_ty가 무시된다
  (B001만 주면 B 전체 2,180건 → 1,916건, C001+C004면 C 6,808건 → 396건).

순수 함수(classify_*, group_*, pair_*)는 단위테스트 대상이다. scan_valuation_disclosures만 API를 부른다.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
import sys
from pathlib import Path
from typing import Any, Callable

from .periodic import CORRECTION_KINDS

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("valuation_schema.json")
EXTRACTOR_VERSION = "1.1"  # 1.1: valuations[].purpose
# 조회·통계 기본값에서 빼는 평가 목적(거래가액을 정하는 평가가 아니다)
NON_DEAL_PURPOSES = {"공정가치평가", "손상검사"}
REGIME_FAIR = "공정가액(2026.12.9 개정)"  # 2026.12.9 이후 이사회 결의분 합병가액 체계 — 기준시가 사례와 통계를 나눈다

# (report_nm에 들어가는 문자열, deal_type) — 앞에서부터 처음 맞는 것. "분할합병"은 "분할"·"합병"보다 먼저 본다.
_B_PATTERNS = (
    ("분할합병결정", "split_merger"),
    ("합병결정", "merger"),
    ("분할결정", "split"),
    ("영업양수결정", "business_transfer"),
    ("영업양도결정", "business_transfer"),
    ("주식교환", "share_exchange"),
    ("주식이전", "share_exchange"),
)
_C_PATTERNS = (
    ("증권신고서(합병)", "merger"),
    ("증권신고서(분할)", "split"),
    ("증권신고서(주식의포괄적교환", "share_exchange"),
    ("증권신고서(지분증권)", "equity"),
)
DEAL_LABELS = {
    "merger": "합병", "split": "분할", "split_merger": "분할합병", "business_transfer": "영업양수도",
    "share_exchange": "주식교환·이전", "ipo": "IPO", "rights_offering": "유상증자",
}
# kinds 인자로 받는 한글 별칭
_KIND_ALIASES = {
    "합병": "merger", "분할": "split", "분할합병": "split_merger", "영업양수": "business_transfer",
    "영업양도": "business_transfer", "영업양수도": "business_transfer", "주식교환": "share_exchange",
    "주식이전": "share_exchange", "ipo": "ipo", "공모": "ipo", "유상증자": "rights_offering",
}
# B↔C 짝: B의 deal_type → 짝이 될 수 있는 C의 deal_type
_PAIRABLE = {
    "merger": {"merger"}, "split": {"split"}, "split_merger": {"split", "merger"},
    "share_exchange": {"share_exchange"},
}
PAIR_WINDOW_DAYS = 120  # 주요사항보고서 접수 후 이 기간 안의 같은 회사 증권신고서를 짝으로 본다
LISTED_CLS = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}
# 꼬리표 중 본문을 대체하는 것(최신 본문 선택용). 증권신고서의 [발행조건확정]은 확정 가격을 반영한 본문이다
_BODY_PREFIXES = ("기재정정", "발행조건확정")
_PREFIX_RE = re.compile(r"^\s*((?:\[[^\]]*\]\s*)*)")
DETAIL_TYPES_LISTED = ("B001", "C001", "C004")
DETAIL_TYPES_ALL = ("B001", "B002", "C001", "C004")


def split_prefix(report_nm: str) -> tuple[str, str]:
    """'[기재정정]주요사항보고서(회사합병결정)' → ('[기재정정]', '주요사항보고서(회사합병결정)')."""
    m = _PREFIX_RE.match(report_nm or "")
    prefix = m.group(1)
    return prefix.replace(" ", ""), (report_nm or "")[m.end():].strip()


def prefix_kind(prefix: str) -> str | None:
    """꼬리표 종류: 기재정정·첨부정정·첨부추가·발행조건확정 중 첫 번째, 없으면 None."""
    for kind in (*CORRECTION_KINDS, "발행조건확정"):
        if f"[{kind}]" in prefix:
            return kind
    return None


def classify_valuation_filing(report_nm: str, corp_cls: str | None = None) -> dict | None:
    """보고서명 → {filing_type, deal_type, source_grade, base_name, prefix, prefix_kind}. 대상이 아니면 None.

    증권신고서(지분증권)은 회사가 비상장(corp_cls E·N·없음)이면 IPO, 상장(Y·K)이면 유상증자로 **잠정** 분류한다.
    corp_cls는 조회 시점 상태라 이미 상장한 IPO도 유상증자로 나온다 → 확정은 equity_kind(본문)로(/dart-valuation-batch).
    투자설명서·증권발행실적보고서·소액공모는 대상이 아니다(평가 내용은 증권신고서에 있다).
    """
    prefix, base = split_prefix(report_nm)
    if base.startswith("증권신고서"):
        for key, deal in _C_PATTERNS:
            if base.startswith(key):
                if deal == "equity":
                    deal = "rights_offering" if corp_cls in ("Y", "K") else "ipo"
                return {"filing_type": "증권신고서", "deal_type": deal, "source_grade": "full",
                        "base_name": base, "prefix": prefix, "prefix_kind": prefix_kind(prefix)}
        return None
    if any(base.startswith(x) for x in ("투자설명서", "증권발행실적", "소액공모", "일괄신고")):
        return None
    for key, deal in _B_PATTERNS:
        if key in base:
            return {"filing_type": "주요사항보고서", "deal_type": deal, "source_grade": "summary",
                    "base_name": base, "prefix": prefix, "prefix_kind": prefix_kind(prefix)}
    return None


# 증권신고서(지분증권)의 IPO/유상증자 구분은 본문으로 한다. list.json의 corp_cls는 **조회 시점** 상태라 올해 상장을 마친
# IPO 회사도 K·Y로 온다(2026-10 실측: 피스피스스튜디오·폴레드·에이치엘지노믹스 등 2026 상장사 75건 중 다수). 주요사항보고서
# (유상증자결정) 유무도 양쪽으로 틀린다(케이뱅크 IPO는 있음, 뉴로메카·루닛 유상증자는 구간 안에 없음).
IPO_MARKERS = ("희망공모가액", "상장예비심사", "공모희망가액")
RIGHTS_MARKERS = ("구주주", "주주배정", "예정발행가액", "신주인수권증서")
SPAC_RE = re.compile(r"기업인수목적|스팩")


def equity_kind(text: str) -> str | None:
    """증권신고서(지분증권) 본문(앞부분이면 충분) → "ipo" | "rights_offering" | None(판단 불가). 표지 단어 빈도를 비교한다."""
    ipo = sum(text.count(k) for k in IPO_MARKERS)
    rights = sum(text.count(k) for k in RIGHTS_MARKERS)
    if ipo == 0 and rights == 0:
        return None
    return "ipo" if ipo >= rights else "rights_offering"


def _date(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y%m%d").date()


def group_filings(items: list[dict]) -> list[dict]:
    """같은 회사·같은 보고서명(꼬리표 제외)의 원본과 정정본을 한 거래로 묶는다 → 거래 목록(최신 접수순).

    items: list.json 항목 + classify 결과({rcept_no, rcept_dt, report_nm, corp_code, ..., base_name, prefix_kind}).
    규칙(periodic과 같은 방향): 최신본(rcept_no) = 그룹에서 가장 늦은 접수, original = 꼬리표 없는 원본,
    body_rcept_no = 꼬리표 없음·[기재정정]·[발행조건확정] 중 최신, attachment_rcept_no = 꼬리표 없음·[첨부정정]·[첨부추가] 중 최신.
    정정본은 같은 회사·같은 이름의 원본 중 자기보다 먼저(같은 날 포함) 접수된 가장 늦은 것에 붙인다.
    같은 날 같은 이름의 원본이 둘 이상이면(실측: 주성코퍼레이션 회사합병결정 2건) 어느 원본의 정정인지 목록만으로는
    알 수 없어 note에 적는다. 원본이 조회 구간 밖이면 original_rcept_no=None(목록에 정정본만 있는 경우도 같다).
    body·attachment 후보가 없으면 그룹의 최신본을 쓴다.
    """
    by_key: dict[tuple[str, str], list[dict]] = {}
    for it in items:
        by_key.setdefault((it.get("corp_code") or it.get("corp_name") or "", it["base_name"]), []).append(it)

    deals: list[dict] = []
    for _key, rows in by_key.items():
        rows.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]))
        groups: list[list[dict]] = []
        orphans: list[dict] = []
        for r in rows:
            if r["prefix_kind"] is None:
                groups.append([r])
            elif groups:
                groups[-1].append(r)
            else:
                orphans.append(r)
        if orphans:
            groups.insert(0, orphans)
        for g in groups:
            originals = [r for r in g if r["prefix_kind"] is None]
            head = max(g, key=lambda r: (r["rcept_dt"], r["rcept_no"]))
            notes: list[str] = []
            if not originals:
                notes.append("목록에 원본(꼬리표 없는 최초 제출본)이 없음: 조회 구간 밖이거나 정정본만 공시됨")
            same_day = [r for r in rows if r["prefix_kind"] is None and originals
                        and r["rcept_dt"] == originals[0]["rcept_dt"] and r is not originals[0]]
            if same_day and len(g) > 1:
                notes.append(f"같은 날 같은 보고서명 원본이 {len(same_day) + 1}건이라 정정본 연결이 불확실함")

            def latest(allowed: tuple[str, ...]) -> str:
                # 후보가 없으면(예: 목록에 [첨부추가]본만 있음 — 알테오젠 합병 2026-10 실측, 그 ZIP에도 본문이 있었다) 최신본
                cand = [r for r in g if r["prefix_kind"] is None or r["prefix_kind"] in allowed] or [head]
                return max(cand, key=lambda r: (r["rcept_dt"], r["rcept_no"]))["rcept_no"]

            deals.append({
                **{k: head.get(k) for k in ("rcept_no", "report_nm", "rcept_dt", "corp_code", "corp_name",
                                            "corp_cls", "flr_nm")},
                "market": LISTED_CLS.get(head.get("corp_cls") or "", None),
                "filing_type": head["filing_type"],
                "deal_type": head["deal_type"],
                "deal_label": DEAL_LABELS[head["deal_type"]],
                "source_grade": head["source_grade"],
                "correction_kind": head["prefix_kind"],
                "original_rcept_no": originals[0]["rcept_no"] if originals else None,
                "original_rcept_dt": originals[0]["rcept_dt"] if originals else None,
                "body_rcept_no": latest(_BODY_PREFIXES),
                "attachment_rcept_no": latest(("첨부정정", "첨부추가")),
                "supersedes": [r["rcept_no"] for r in g if r is not head],
                "related_rcept_nos": [],
                "notes": notes + (["상장사 지분증권 신고서: 올해 상장한 IPO일 수 있음(corp_cls는 조회 시점) → 본문 equity_kind로 확인"]
                                  if head["deal_type"] == "rights_offering" else []),
            })
    deals.sort(key=lambda d: (d["rcept_dt"], d["rcept_no"]), reverse=True)
    return deals


def pair_related(deals: list[dict], window_days: int = PAIR_WINDOW_DAYS) -> None:
    """같은 회사의 주요사항보고서(B)와 증권신고서(C)를 짝지어 related_rcept_nos에 서로의 최신 rcept_no를 넣는다(제자리 수정).

    C는 B 최초 접수일(없으면 최신 접수일) 이후 window_days 안에 접수된 것, deal_type이 짝이 되는 것만.
    B 하나에 후보 C가 여럿이면 가장 가까운 것 하나.
    """
    cs = [d for d in deals if d["filing_type"] == "증권신고서"]
    for b in (d for d in deals if d["filing_type"] == "주요사항보고서"):
        ok = _PAIRABLE.get(b["deal_type"], set())
        start = _date(b["original_rcept_dt"] or b["rcept_dt"])
        best = None
        for c in cs:
            if c["corp_code"] != b["corp_code"] or c["deal_type"] not in ok:
                continue
            gap = (_date(c["original_rcept_dt"] or c["rcept_dt"]) - start).days
            if 0 <= gap <= window_days and (best is None or gap < best[0]):
                best = (gap, c)
        if best:
            c = best[1]
            b["related_rcept_nos"].append(c["rcept_no"])
            c["related_rcept_nos"].append(b["rcept_no"])


# kinds를 생략했을 때 빼는 유형: 상장사 유상증자 증권신고서는 회사 가치평가가 아니라 발행가 할인 산정이라 사례 수집 대상이 아니다
# (2026-07–10 실측 178건 중 55건). kinds=["유상증자"]로 명시하면 나온다
_OPT_IN_KINDS = {"rights_offering"}


def normalize_kinds(kinds: list[str] | str | None) -> set[str]:
    """kinds 인자(영문 코드·한글 별칭, 쉼표 문자열 허용) → deal_type 집합. 생략하면 유상증자를 뺀 전부."""
    if kinds is None or kinds == [] or kinds == "":
        return set(DEAL_LABELS) - _OPT_IN_KINDS
    if isinstance(kinds, str):
        kinds = [k for k in re.split(r"[,\s]+", kinds) if k]
    out: set[str] = set()
    for k in kinds:
        key = k.strip()
        code = key if key in DEAL_LABELS else _KIND_ALIASES.get(key.lower())
        if code is None:
            raise ValueError(f"kinds {key!r}를 모름. 사용 가능: {sorted(DEAL_LABELS)} 또는 {sorted(_KIND_ALIASES)}")
        out.add(code)
    return out


def date_windows(bgn_de: str, end_de: str, max_days: int = 89) -> list[tuple[str, str]]:
    """[bgn, end]를 corp_code 없는 list.json 한도(3개월) 안의 구간들로 나눈다(최신 구간부터)."""
    b, e = _date(bgn_de), _date(end_de)
    if b > e:
        raise ValueError(f"bgn_de({bgn_de})가 end_de({end_de})보다 늦습니다")
    out: list[tuple[str, str]] = []
    while e >= b:
        s = max(b, e - dt.timedelta(days=max_days))
        out.append((s.strftime("%Y%m%d"), e.strftime("%Y%m%d")))
        e = s - dt.timedelta(days=1)
    return out


def scan_valuation_disclosures(
    list_page: Callable[..., dict],
    bgn_de: str,
    end_de: str,
    *,
    kinds: list[str] | str | None = None,
    corp_code: str | None = None,
    listed_only: bool = True,
) -> dict:
    """list_page(**params) → list.json 응답. 구간·페이지를 모두 돌아 가치평가 공시 거래 목록을 만든다.

    반환: {deals[], api_calls, windows[], scanned{detail_ty: 건수}}.
    listed_only: 상장사(Y·K) 공시만. 단 IPO(비상장사의 증권신고서(지분증권))는 남긴다.
    """
    wanted = normalize_kinds(kinds)
    detail_types = DETAIL_TYPES_LISTED if listed_only else DETAIL_TYPES_ALL
    windows = [(bgn_de, end_de)] if corp_code else date_windows(bgn_de, end_de)
    rows: list[dict] = []
    calls = 0
    scanned: dict[str, int] = {}
    for w_bgn, w_end in windows:
        for detail in detail_types:
            page = 1
            while True:
                data = list_page(corp_code=corp_code, bgn_de=w_bgn, end_de=w_end, pblntf_detail_ty=detail,
                                 page_no=page, page_count=100)
                calls += 1
                batch = data.get("list", [])
                scanned[detail] = scanned.get(detail, 0) + len(batch)
                for it in batch:
                    c = classify_valuation_filing(it.get("report_nm", ""), it.get("corp_cls"))
                    if c is None:
                        continue
                    rows.append({**{k: it.get(k) for k in ("rcept_no", "report_nm", "rcept_dt", "corp_code",
                                                           "corp_name", "corp_cls", "flr_nm")}, **c})
                if not batch or page >= int(data.get("total_page", 1) or 1):
                    break
                page += 1
    deals = group_filings(rows)
    pair_related(deals)
    if listed_only:
        # 비상장사 공시는 빼되, 비상장 단계에 낸 IPO 신고서는 남긴다(SPAC 상장은 평가가 없어 뺀다)
        deals = [d for d in deals if d["corp_cls"] in ("Y", "K")
                 or (d["deal_type"] == "ipo" and not SPAC_RE.search(d["corp_name"] or ""))]
    deals = [d for d in deals if d["deal_type"] in wanted]
    return {"deals": deals, "api_calls": calls, "windows": windows, "scanned": scanned}


def industry_label(code: str | None) -> str | None:
    from .industry import label

    return label(code)


# --------------------------------------------------------------------------- 사례 JSON 검증
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_case(case: dict) -> list[str]:
    """스키마 위반 메시지 목록(비면 통과). jsonschema가 없으면 ImportError."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(load_schema())
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
              for e in sorted(validator.iter_errors(case), key=lambda e: list(e.absolute_path))]
    return errors + range_order_errors(case)


def range_order_errors(node: Any, path: str = "") -> list[str]:
    """{min, max} 범위에서 min.value > max.value인 곳(JSON Schema로는 값 비교를 못 한다).

    배치 1차 실측: IPO 할인율 "29.83% ~ 11.74%"를 원문 표기 순서대로 min=29.83으로 넣은 건이 15건 나왔다.
    범위는 숫자 크기 순서다(min ≤ max). 어느 끝이 하단 공모가에 대응하는지는 note에 적는다.
    """
    out: list[str] = []
    if isinstance(node, dict):
        if set(node) == {"min", "max"} and all(isinstance(node[k], dict) for k in ("min", "max")):
            a, b = node["min"].get("value"), node["max"].get("value")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a > b:
                out.append(f"{path or '(root)'}: 범위 min({a}) > max({b}) — 숫자 크기 순서로 넣는다")
        for k, v in node.items():
            out += range_order_errors(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += range_order_errors(v, f"{path}/{i}")
    return out


WACC_RANGE = (0.0, 30.0)      # %
G_MAX = 5.0                   # %
DISCOUNT_RANGE = (0.0, 70.0)  # %


def _pct(field: Any) -> float | None:
    """{value, unit} → % 값. unit "%"는 그대로, 단위 없는 소수(|v| < 1)는 ×100. 그 밖의 단위는 None(검사 안 함)."""
    if not isinstance(field, dict) or not isinstance(field.get("value"), (int, float)):
        return None
    v, u = float(field["value"]), (field.get("unit") or "").strip()
    if u == "%":
        return v
    if not u and abs(v) < 1:
        return v * 100
    return None


def distribution_warnings(case: dict) -> list[str]:
    """값 분포 밖의 숫자(FAIL 아님 — 원문이 그럴 수 있다). 원문 대조가 필요한 곳을 찍는다.

    WACC 0–30% 밖, g ≥ WACC(같은 원소), g > 5%, 적용 멀티플 ≤ 0, 할인율 0–70% 밖,
    자산가치 자본총계 + 조정항목 ≠ 조정 순자산(같은 단위, 분할 제외 — 분할은 equity_book이 분할 전 회사라 맞지 않는 게 정상).
    2026-10 배치 리뷰 실측: 조정항목 부호 누락("(81,583,335)"를 양수로) 2건, 가산항목 한 줄만 넣음 1건. 원문 표 자체가 안 맞는 건도 있다(note).
    """
    out: list[str] = []

    def discount(rng: Any, path: str) -> None:
        for end in ("min", "max"):
            d = _pct((rng or {}).get(end))
            if d is not None and not DISCOUNT_RANGE[0] <= d <= DISCOUNT_RANGE[1]:
                out.append(f"{path}/{end}: 할인율 {d:g}% — {DISCOUNT_RANGE[0]:g}–{DISCOUNT_RANGE[1]:g}% 밖")

    def multiple(field: Any, path: str) -> None:
        m = (field or {}).get("value")
        if isinstance(m, (int, float)) and m <= 0:
            out.append(f"{path}: 멀티플 {m:g} ≤ 0")

    for i, val in enumerate(case.get("valuations") or []):
        dcf, rel, p = val.get("dcf") or {}, val.get("relative") or {}, f"valuations/{i}"
        w, g = _pct(dcf.get("wacc")), _pct(dcf.get("g"))
        if w is not None and not WACC_RANGE[0] <= w <= WACC_RANGE[1]:
            out.append(f"{p}/dcf/wacc: WACC {w:g}% — {WACC_RANGE[0]:g}–{WACC_RANGE[1]:g}% 밖")
        if g is not None and g > G_MAX:
            out.append(f"{p}/dcf/g: g {g:g}% > {G_MAX:g}%")
        if g is not None and w is not None and g >= w:
            out.append(f"{p}/dcf/g: g {g:g}% ≥ WACC {w:g}%")
        av = val.get("asset_value") or {}
        eq, adj, tot = (av.get(k) if isinstance(av.get(k), dict) else {} for k in ("equity_book", "adjustments", "total"))
        nums = [x.get("value") for x in (eq, adj, tot)]
        if (case.get("deal") or {}).get("type") != "split" and all(isinstance(x, (int, float)) for x in nums)                 and len({eq.get("unit"), adj.get("unit"), tot.get("unit")}) == 1                 and abs(nums[0] + nums[1] - nums[2]) > max(2, abs(nums[2]) * 1e-6):
            out.append(f"{p}/asset_value: 자본총계 {nums[0]:,} + 조정항목 {nums[1]:,} ≠ 조정 순자산 {nums[2]:,} — 부호·합계 확인")
        multiple(rel.get("multiple"), f"{p}/relative/multiple")
        discount(rel.get("discount_range"), f"{p}/relative/discount_range")
    ipo = case.get("ipo") or {}
    multiple(ipo.get("multiple"), "ipo/multiple")
    discount(ipo.get("discount_range"), "ipo/discount_range")
    return out


def iter_numbers(node: Any, path: str = "") -> list[tuple[str, dict]]:
    """사례 JSON에서 {"value", "cite"} 숫자 필드를 모두 찾는다 → [(경로, 필드)]. value가 null인 것은 뺀다."""
    out: list[tuple[str, dict]] = []
    if isinstance(node, dict):
        if "value" in node and "cite" in node:
            if node["value"] is not None:
                out.append((path, node))
            return out
        for k, v in node.items():
            out += iter_numbers(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += iter_numbers(v, f"{path}/{i}")
    return out


def number_variants(field: dict) -> list[str]:
    """숫자 필드를 원문에서 찾을 후보 문자열. text(원문 표기)가 있으면 그것을 먼저."""
    out: list[str] = []
    if field.get("text"):
        out.append(str(field["text"]))
    v = field["value"]
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            out += [f"{int(v):,}", str(int(v))]
        else:
            s = f"{v}"
            out += [s, f"{v:,}"]
            if "." in s:
                out.append(s.rstrip("0").rstrip("."))
    else:
        out.append(str(v))
    return list(dict.fromkeys(out))


def check_citation(field: dict, section_text: str, window: int = 500) -> bool:
    """cite.offset ±window 안에 숫자(후보 표기 중 하나)가 실제로 있는지."""
    off = int(field["cite"].get("offset") or 0)
    chunk = section_text[max(0, off - window): off + window]
    return any(v in chunk for v in number_variants(field))


def verify_citations(case: dict, get_text: Callable[[str, str, str], str | None], *,
                     sample: int = 8, seed: int | None = None, window: int = 500) -> dict:
    """value가 있는 숫자 필드 중 무작위 sample개의 cite를 원문에서 확인한다.

    get_text(rcept_no, file_id, section_id) → 섹션 텍스트(없으면 None). cite.rcept_no가 없으면 case의 rcept_no.
    반환: {total, missing_cite[], sampled[{path, value, cite, ok, reason}]}.
    """
    nums = iter_numbers(case)
    missing = [p for p, f in nums if not f.get("cite")]
    cited = [(p, f) for p, f in nums if f.get("cite")]
    rng = random.Random(seed)
    picked = rng.sample(cited, min(sample, len(cited)))
    results = []
    for p, f in picked:
        cite = f["cite"]
        text = get_text(cite.get("rcept_no") or case["rcept_no"], cite.get("file_id") or "main", cite["section_id"])
        if text is None:
            results.append({"path": p, "value": f["value"], "cite": cite, "ok": False, "reason": "섹션 없음"})
            continue
        ok = check_citation(f, text, window)
        results.append({"path": p, "value": f["value"], "cite": cite, "ok": ok,
                        "reason": "" if ok else f"±{window}자 안에 {number_variants(f)} 없음"})
    return {"total": len(nums), "missing_cite": missing, "sampled": results}


def flatten_case(case: dict) -> list[dict]:
    """사례 JSON → 평가 주체·대상별 한 행씩(조회 표용). 숫자는 value만."""
    def v(x: Any) -> Any:
        return x.get("value") if isinstance(x, dict) else x

    rows = []
    base = {
        "rcept_no": case["rcept_no"], "company": case["company"]["name"],
        "induty_code": case["company"].get("induty_code"), "deal_type": case["deal"]["type"],
        "industry": industry_label(case["company"].get("induty_code")),
        "board_date": case["deal"].get("board_date"), "regime": case["deal"].get("regime"),
        "firm": (case.get("external_valuation") or {}).get("firm"), "source_grade": case["source_grade"],
    }
    for val in case.get("valuations") or [{}]:
        dcf = val.get("dcf") or {}
        rel = val.get("relative") or {}
        res = val.get("result") or {}
        rows.append({
            **base, "subject": val.get("subject"), "target": val.get("target"), "role": val.get("role"),
            "purpose": val.get("purpose"),
            "method": val.get("method"), "wacc": v(dcf.get("wacc")), "g": v(dcf.get("g")),
            "multiple_type": rel.get("multiple_type"), "multiple": v(rel.get("multiple")),
            "result": v(res.get("value")), "result_unit": res.get("unit"),
        })
    return rows


def _deal_date(row: dict) -> str:
    """조회 기간 기준일: 이사회 결의일, 없으면 접수일(rcept_no 앞 8자리)."""
    r = row["rcept_no"]
    return row.get("board_date") or f"{r[:4]}-{r[4:6]}-{r[6:8]}"


def _quantiles(xs: list[float]) -> dict:
    """n, 중앙값, 1·3사분위(선형 보간), 최소·최대."""
    import statistics

    s = sorted(xs)
    if not s:
        return {"n": 0}
    q = statistics.quantiles(s, n=4, method="inclusive") if len(s) > 1 else [s[0], s[0], s[0]]
    return {"n": len(s), "median": statistics.median(s), "q1": q[0], "q3": q[2], "min": s[0], "max": s[-1]}


def representative(values: list[tuple[str | None, float]]) -> float | None:
    """한 거래의 값 여럿 → 대표값. 외부평가 역할 값이 있으면 그 값들의 중앙값, 없으면 전체 중앙값."""
    import statistics

    if not values:
        return None
    ext = [x for role, x in values if role == "외부평가"]
    return statistics.median(ext or [x for _, x in values])


def filter_rows(rows: list[dict], *, date_from: str | None = None, date_to: str | None = None,
                deal_types: set[str] | None = None, methods: set[str] | None = None,
                purposes: set[str] | None = None, firm: str | None = None,
                regimes: set[str] | None = None, industries: set[str] | None = None) -> list[dict]:
    """평가 행 거르기. purposes=None이면 거래가액 평가만(공정가치평가·손상검사 제외), {"all"}이면 전부.

    regimes: deal.regime 값 집합(예: {"기준시가"}). "none"은 regime이 null인 행.
    industries: KSIC 코드 접두 집합(예: {"26", "21"}, {"582"}) — induty_code가 그중 하나로 시작하는 행."""
    out = []
    for r in rows:
        d = _deal_date(r)
        if (date_from and d < date_from) or (date_to and d > date_to):
            continue
        if deal_types and r["deal_type"] not in deal_types:
            continue
        if methods and r.get("method") not in methods:
            continue
        p = r.get("purpose")
        if purposes is None:
            if p in NON_DEAL_PURPOSES:
                continue
        elif "all" not in purposes and p not in purposes:
            continue
        if firm and firm not in (r.get("firm") or "") and firm not in (r.get("subject") or ""):
            continue
        if regimes and (r.get("regime") or "none") not in regimes:
            continue
        if industries and not any((r.get("induty_code") or "").startswith(x) for x in industries):
            continue
        out.append(r)
    return out


def deal_stats(rows: list[dict], variables: tuple[str, ...] = ("wacc", "g", "multiple")) -> dict:
    """거래(rcept_no) 단위 통계. 변수마다 거래별 대표값(representative)으로 분위수를 내고 "N건 거래, M개 값"을 함께 준다.

    multiple은 multiple_type별로 따로 센다. firms: 거래별 외부평가기관(external_valuation.firm) 건수.
    """
    by_deal: dict[str, list[dict]] = {}
    for r in rows:
        by_deal.setdefault(r["rcept_no"], []).append(r)
    out: dict[str, Any] = {"deals": len(by_deal), "values": len(rows), "variables": {}, "firms": {}}
    for var in variables:
        groups: dict[str, dict[str, list]] = {}
        for rno, rs in by_deal.items():
            for r in rs:
                if r.get(var) is None:
                    continue
                key = f"{var}:{r.get('multiple_type') or '?'}" if var == "multiple" else var
                groups.setdefault(key, {}).setdefault(rno, []).append((r.get("role"), float(r[var])))
        for key, per_deal in groups.items():
            reps = {rno: representative(vals) for rno, vals in per_deal.items()}
            out["variables"][key] = {**_quantiles(list(reps.values())), "deals": len(reps),
                                     "values": sum(len(v) for v in per_deal.values()), "per_deal": reps}
    # 평가기관별 거래 수: 그 거래의 외부평가 원소 subject(거래당 중복 없이). external_valuation.firm은 자유 문구라
    # ("한미회계법인(존속회사 선임), 한울회계법인(소멸회사 선임)" 등 — 배치 실측) 세지 않는다. 외부평가 원소가 없으면 "(외부평가 없음)"
    for rs in by_deal.values():
        names = sorted({r["subject"] for r in rs if r.get("role") == "외부평가" and r.get("subject")}) or ["(외부평가 없음)"]
        for f in names:
            out["firms"][f] = out["firms"].get(f, 0) + 1
    return out


def ipo_stats(cases: list[dict]) -> dict:
    """IPO 사례(case.ipo)의 거래 단위 통계: 적용 멀티플 종류 분포, 종류별 멀티플 분위수, 할인율 하단·상단 분위수."""
    kinds: dict[str, int] = {}
    mult: dict[str, list[float]] = {}
    lo: list[float] = []
    hi: list[float] = []
    for c in cases:
        ipo = c.get("ipo") or {}
        mt = ipo.get("multiple_type") or "(없음)"
        kinds[mt] = kinds.get(mt, 0) + 1
        m = (ipo.get("multiple") or {}).get("value")
        if m is not None:
            mult.setdefault(mt, []).append(float(m))
        dr = ipo.get("discount_range") or {}
        if (dr.get("min") or {}).get("value") is not None:
            lo.append(float(dr["min"]["value"]))
        if (dr.get("max") or {}).get("value") is not None:
            hi.append(float(dr["max"]["value"]))
    return {"deals": len(cases), "multiple_types": kinds, "multiple": {k: _quantiles(v) for k, v in mult.items()},
            "discount_min": _quantiles(lo), "discount_max": _quantiles(hi)}


def _fmt(x: Any) -> str:
    """숫자 필드 → 원문 표기(text) 또는 value+unit. null이면 '원문 없음'."""
    if not isinstance(x, dict) or x.get("value") is None:
        return "원문 없음"
    if x.get("text"):
        t = str(x["text"])
        unit = x.get("unit") or ""
        # 원문 표기가 이미 단위 표지로 끝나면("12.85x", "8.43%", "261,345원") 붙이지 않는다("12.85x배" 방지)
        return t if (not unit or t.endswith(unit) or not t[-1:].isdigit()) else f"{t}{unit}"
    return f"{x['value']}{x.get('unit') or ''}"


def _fmt_range(r: dict | None) -> str:
    if not r:
        return "–"
    return f"{_fmt(r.get('min'))}–{_fmt(r.get('max'))}"


def _cite_s(x: Any) -> str:
    if isinstance(x, dict) and set(x) == {"min", "max"}:  # 범위면 양 끝 cite(같으면 하나)
        a, b = _cite_s(x.get("min")), _cite_s(x.get("max"))
        return a if a == b or not b else f"{a} {b}".strip()
    c = x.get("cite") if isinstance(x, dict) else None
    if not c:
        return ""
    pre = f"{c['rcept_no']}, " if c.get("rcept_no") else ""
    return f"({pre}§{c['section_id']} @{c['offset']})"


def _yn(x: bool | None) -> str:
    return "–" if x is None else ("예" if x else "아니오")


def render_markdown(case: dict) -> str:
    """사례 JSON → 사람용 md(/dart-valuation 고정 목차). 값이 null이면 '원문 없음'."""
    d, ev, co = case["deal"], case["external_valuation"], case["conclusion"]
    label = DEAL_LABELS.get(d["type"], d["type"])
    out = [f"# {case['company']['name']} {label} 가치평가 (rcept_no {case['rcept_no']}, {case['filing_type']}, 등급 {case['source_grade']})",
           f"> 원본 {case.get('original_rcept_no') or '–'} / 짝 공시 {', '.join(case.get('related_rcept_nos') or []) or '없음'} / "
           f"이사회 {d.get('board_date') or '원문 없음'} / 체계 {d.get('regime') or '원문 없음'} / 추출 {case['extracted_at']} (v{case['extractor_version']})",
           "", "## 1. 거래 개요", "", "| 항목 | 내용 |", "|---|---|",
           f"| 회사 | {case['company']['name']} ({case['company'].get('market') or '–'}, {case['company'].get('corp_code') or '–'}) |",
           f"| 거래 | {label} — 상대방 {d.get('counterparty') or '–'} (상장 {_yn(d.get('counterparty_listed'))}) |",
           f"| 관계 | {d.get('relation_text') or '–'} (특수관계 {_yn(d.get('related_party'))}) |",
           f"| 비율 | {d.get('ratio_text') or '–'} |",
           f"| 외부평가 | {'예' if ev.get('required') else ('아니오/미해당' if ev.get('required') is False else '원문 없음')}"
           f"{' — ' + ev['exemption_reason'] if ev.get('exemption_reason') else ''} |",
           f"| 평가기관 | {ev.get('firm') or '–'} ({ev.get('firm_type') or '–'}) |",
           f"| 근거(원문) | {ev.get('basis_text') or '원문 없음'} |",
           f"| 평가 기간 | {ev.get('period') or '원문 없음'} |",
           f"| 감사위원회 동의 | {'원문 없음' if ev.get('audit_committee_consent') is None else _yn(ev['audit_committee_consent'])} |",
           f"| 준수 기준 | {', '.join(ev.get('standards_cited') or []) or '원문 없음'} |",
           f"| 의견 요지 | {ev.get('opinion_text') or '원문 없음'} {_cite_s(ev)} |",
           "", "## 2. 평가 주체별 방법·가정", "",
           "| 주체 | 대상 | 역할 | 목적 | 방법 | 가중(자산:수익) | WACC | g | β(U/L) | 멀티플 | 결과 | 범위 | 출처 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in case["valuations"]:
        dcf, rel, res, w = v.get("dcf") or {}, v.get("relative") or {}, v["result"], v.get("weights")
        beta = f"{_fmt(dcf.get('beta_unlevered'))}/{_fmt(dcf.get('beta_levered'))}" if dcf else "–"
        mult = f"{rel.get('multiple_type') or ''} {_fmt(rel.get('multiple'))}".strip() if rel else "–"
        cites = [x for x in (dcf.get("wacc"), res.get("value"), (res.get("range") or {}).get("min"))
                 if isinstance(x, dict) and x.get("cite")][:2]
        out.append(f"| {v['subject']} | {v['target']} | {v['role']} | {v.get('purpose') or '–'} | {v['method']} | "
                   f"{f'{w['asset']}:{w['income']}' if w else '–'} | {_fmt(dcf.get('wacc')) if dcf else '–'} | "
                   f"{_fmt(dcf.get('g')) if dcf else '–'} | {beta} | {mult} | {_fmt(res.get('value'))} | "
                   f"{_fmt_range(res.get('range'))} | {' '.join(_cite_s(x) for x in cites)} |")
    notes_v = [f"- {v['subject']} / {v['target']} / {v['method']}: {v['note']}" for v in case["valuations"] if v.get("note")]
    if notes_v:
        out += ["", *notes_v]
    wacc_rows = [v for v in case["valuations"] if v.get("dcf") and any((v["dcf"].get(k) or {}).get("value") is not None
                                                                      for k in ("rf", "mrp", "beta_levered"))]
    for v in wacc_rows:
        dcf = v["dcf"]
        out += ["", f"**WACC 구성 — {v['subject']} / {v['target']}**", "", "| 항목 | 값 | 출처 |", "|---|---|---|"]
        for k, lab in (("rf", "무위험이자율"), ("mrp", "시장위험프리미엄"), ("beta_unlevered", "Unlevered β"),
                       ("beta_levered", "Relevered β"), ("size_premium", "규모위험프리미엄"), ("ke", "자기자본비용"),
                       ("kd", "세전타인자본비용"), ("tax_rate", "세율"), ("target_de", "목표 D/E"), ("target_dv", "목표 D/(D+E)"), ("wacc", "WACC"), ("g", "영구성장률")):
            out.append(f"| {lab} | {_fmt(dcf.get(k))} | {_cite_s(dcf.get(k))} |")
        if dcf.get("peers"):
            out.append("")
            out.append("유사기업: " + ", ".join(f"{p['name']} {_fmt(p.get('value'))}" for p in dcf["peers"]))
    out += ["", "## 3. 결론", "", "| 회사/주체 | 기준 | 주당 가액·범위 | 출처 |", "|---|---|---|---|"]
    out += [f"| {p['company']} | {p.get('basis') or '–'} | {_fmt(p['value'])} | {_cite_s(p['value'])} |" for p in co["price_per_share"]]
    for r in co["range"]:
        out.append(f"| {r.get('subject') or '–'} | {r['label']} | {_fmt_range(r['range'])} | {_cite_s(r['range'])} |")
    if co.get("ratio"):
        out.append(f"| – | 비율 | {_fmt(co['ratio'])} | {_cite_s(co['ratio'])} |")
    if co.get("transaction_value"):
        out.append(f"| – | 거래금액 | {_fmt(co['transaction_value'])} | {_cite_s(co['transaction_value'])} |")
    out += ["", f"의견: {co.get('opinion_text') or '원문 없음'}", "", "## 4. 민감도", ""]
    if case["sensitivity"]:
        out += ["| 주체 | 대상 | 변수 | 범위 | 출처 |", "|---|---|---|---|---|"]
        out += [f"| {s['subject']} | {s['target']} | {s['variables']} | {_fmt_range(s['range'])} | {_cite_s(s['range'])} |"
                for s in case["sensitivity"]]
    else:
        out.append("원문 없음")
    ipo = case.get("ipo")
    if ipo:
        out += ["", "## 5. 공모가 산정 (IPO)", "", "| 항목 | 값 | 출처 |", "|---|---|---|",
                f"| 주관사 | {ipo.get('underwriter') or '–'} | |", f"| 방법 | {ipo.get('method') or '–'} {ipo.get('multiple_type') or ''} | |",
                f"| 제외 지표 | {', '.join(ipo.get('excluded_multiples') or []) or '–'} | |"]
        for k, lab in (("applied_earnings", "적용 이익"), ("multiple", "적용 멀티플"), ("shares", "적용 주식수"),
                       ("value_per_share", "주당 평가가액")):
            out.append(f"| {lab} | {_fmt(ipo.get(k))} | {_cite_s(ipo.get(k))} |")
        for k, lab in (("discount_range", "할인율"), ("price_band", "공모희망가액")):
            r = ipo.get(k)
            out.append(f"| {lab} | {_fmt_range(r)} | {_cite_s(r or {})} |")
        if ipo.get("applied_earnings_basis"):
            out.append(f"| 적용 이익 기준 | {ipo['applied_earnings_basis']} | |")
        if ipo.get("peers"):
            out += ["", "비교기업: " + ", ".join(f"{p['name']} {_fmt(p.get('value'))}" for p in ipo["peers"])]
        if ipo.get("external_comparison"):
            out += ["", f"외부평가와 비교: {ipo['external_comparison']}"]
    if case.get("notes"):
        out += ["", "## 비고", "", *[f"- {n}" for n in case["notes"]]]
    out += ["", "## 부록. 출처", "", "| rcept_no | file_id | section_id | 제목 | 읽은 글자 수 | 방법 |", "|---|---|---|---|---|---|"]
    out += [f"| {c['rcept_no']} | {c['file_id']} | {c['section_id']} | {c.get('title') or ''} | {c['chars_read']:,} | {c.get('how') or ''} |"
            for c in case["citations"]]
    # 원문 범위 표기 "39,907~47,403"가 한 줄에 둘 이상이면 Markdown 취소선이 된다(CLAUDE.md 범위 규칙) → en dash
    return "\n".join(out).replace("~", "–") + "\n"


def _stats_cli(directory: Path, argv: list[str]) -> int:
    """stats <dir> [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--deal-type merger,ipo] [--method DCF] [--purpose 합병가액,…|all] [--firm X]
    [--regime 기준시가|"공정가액(2026.12.9 개정)"|IPO|none] [--industry 26,21 (KSIC 코드 접두)]

    거래 단위 통계(JSON): 걸러진 행, deal_stats(WACC·g·멀티플 대표값 분위수, 평가기관별 건수), IPO가 있으면 ipo_stats.
    industries: 중분류 라벨별 거래 수("26 전자부품·…", 매핑에 없으면 코드만). regimes: 체계별 거래 수. 기준시가와 공정가액 체계가 섞이면 warning — 합병가액 산정 체계가 달라 한 분포로 보면 안 된다.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="dart_mcp.valuation stats")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--deal-type")
    ap.add_argument("--method")
    ap.add_argument("--purpose")
    ap.add_argument("--firm")
    ap.add_argument("--regime")
    ap.add_argument("--industry")
    a = ap.parse_args(argv)
    split = (lambda s: {x.strip() for x in s.split(",") if x.strip()} if s else None)
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))
             if not p.name.startswith("_")]
    rows = [r for c in cases for r in flatten_case(c)]
    rows = filter_rows(rows, date_from=a.date_from, date_to=a.date_to, deal_types=split(a.deal_type),
                       methods=split(a.method), purposes=split(a.purpose), firm=a.firm, regimes=split(a.regime),
                       industries=split(a.industry))
    kept = {r["rcept_no"] for r in rows}
    regimes: dict[str, int] = {}
    industries: dict[str, int] = {}
    for rno in kept:
        first = next(r for r in rows if r["rcept_no"] == rno)
        reg, ind = first.get("regime") or "none", first.get("industry") or "(없음)"
        regimes[reg] = regimes.get(reg, 0) + 1
        industries[ind] = industries.get(ind, 0) + 1
    out = {"filters": vars(a), "regimes": regimes, "industries": dict(sorted(industries.items(), key=lambda x: -x[1])),
           "rows": rows, **deal_stats(rows)}
    if {"기준시가", REGIME_FAIR} <= set(regimes):
        out["warning"] = f"기준시가·{REGIME_FAIR} 체계가 섞였다 — --regime으로 나눠 따로 본다"
    ipo_cases = [c for c in cases if c["rcept_no"] in kept and c["deal"]["type"] == "ipo"]
    if ipo_cases:
        out["ipo"] = ipo_stats(ipo_cases)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def _cli(argv: list[str]) -> int:
    """uv run python -m dart_mcp.valuation validate <case.json|dir> | verify-cites <case.json> [--sample 8] [--seed N]
    | md <case.json> (같은 이름 .md 생성) | table <dir> | stats <dir> [필터…] (거래 단위 통계)
    validate: errors[]가 있으면 FAIL(종료코드 1), warnings[](분포 밖 값)는 원문 대조용 — 종료코드에 영향 없음."""
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("validate", "verify-cites", "table", "md", "stats"):
        print(_cli.__doc__)
        return 2
    cmd, target = argv[0], Path(argv[1])
    if cmd == "validate" and target.is_dir():
        results = []
        for p in sorted(target.glob("*.json")):
            if p.name.startswith("_"):
                continue
            c = json.loads(p.read_text(encoding="utf-8"))
            results.append({"file": p.name, "errors": validate_case(c), "warnings": distribution_warnings(c)})
        print(json.dumps({"cases": len(results), "failed": sum(bool(r["errors"]) for r in results),
                          "warned": sum(bool(r["warnings"]) for r in results),
                          "results": [r for r in results if r["errors"] or r["warnings"]]}, ensure_ascii=False, indent=1))
        return 1 if any(r["errors"] for r in results) else 0
    if cmd == "stats":
        return _stats_cli(target, argv[2:])
    if cmd == "md":
        md_path = target.with_suffix(".md")
        md_path.write_text(render_markdown(json.loads(target.read_text(encoding="utf-8"))), encoding="utf-8")
        print(md_path)
        return 0
    if cmd == "table":
        rows = [r for p in sorted(target.glob("*.json")) for r in flatten_case(json.loads(p.read_text(encoding="utf-8")))]
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    case = json.loads(target.read_text(encoding="utf-8"))
    if cmd == "validate":
        errors = validate_case(case)
        print(json.dumps({"file": str(target), "valid": not errors, "errors": errors,
                          "warnings": distribution_warnings(case)}, ensure_ascii=False, indent=1))
        return 0 if not errors else 1
    sample = int(argv[argv.index("--sample") + 1]) if "--sample" in argv else 8
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else target.stat().st_size
    from .cache import DisclosureCache
    from .client import DartClient

    cache = DisclosureCache()

    def get_text(rcept_no: str, file_id: str, section_id: str) -> str | None:
        disc = cache.get(rcept_no, None if cache.has(rcept_no) else DartClient())
        f = disc.get_file(file_id)
        sec = f.get_section(section_id) if f else None
        return sec.text if sec else None

    out = verify_citations(case, get_text, sample=sample, seed=seed)
    out["seed"] = seed
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if not out["missing_cite"] and all(r["ok"] for r in out["sampled"]) else 1


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    sys.exit(_cli(sys.argv[1:]))
