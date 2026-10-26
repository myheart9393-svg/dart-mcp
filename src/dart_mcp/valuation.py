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
EXTRACTOR_VERSION = "1.0"

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

    증권신고서(지분증권)은 회사가 비상장(corp_cls E·N·없음)이면 IPO, 상장(Y·K)이면 유상증자로 본다.
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
                "notes": notes,
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
        deals = [d for d in deals if d["corp_cls"] in ("Y", "K") or d["deal_type"] == "ipo"]
    deals = [d for d in deals if d["deal_type"] in wanted]
    return {"deals": deals, "api_calls": calls, "windows": windows, "scanned": scanned}


# --------------------------------------------------------------------------- 사례 JSON 검증
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_case(case: dict) -> list[str]:
    """스키마 위반 메시지 목록(비면 통과). jsonschema가 없으면 ImportError."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(load_schema())
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(case), key=lambda e: list(e.absolute_path))]


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
        "board_date": case["deal"].get("board_date"), "regime": case["deal"].get("regime"),
        "firm": (case.get("external_valuation") or {}).get("firm"), "source_grade": case["source_grade"],
    }
    for val in case.get("valuations") or [{}]:
        dcf = val.get("dcf") or {}
        rel = val.get("relative") or {}
        res = val.get("result") or {}
        rows.append({
            **base, "subject": val.get("subject"), "target": val.get("target"), "role": val.get("role"),
            "method": val.get("method"), "wacc": v(dcf.get("wacc")), "g": v(dcf.get("g")),
            "multiple_type": rel.get("multiple_type"), "multiple": v(rel.get("multiple")),
            "result": v(res.get("value")), "result_unit": res.get("unit"),
        })
    return rows


def _fmt(x: Any) -> str:
    """숫자 필드 → 원문 표기(text) 또는 value+unit. null이면 '원문 없음'."""
    if not isinstance(x, dict) or x.get("value") is None:
        return "원문 없음"
    if x.get("text"):
        t = str(x["text"])
        unit = x.get("unit") or ""
        return t if (not unit or t.endswith(unit) or unit == "주") else f"{t}{unit}"
    return f"{x['value']}{x.get('unit') or ''}"


def _fmt_range(r: dict | None) -> str:
    if not r:
        return "–"
    return f"{_fmt(r.get('min'))}–{_fmt(r.get('max'))}"


def _cite_s(x: Any) -> str:
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
           f"> 원본 {case.get('original_rcept_no')} / 짝 공시 {', '.join(case.get('related_rcept_nos') or []) or '없음'} / "
           f"이사회 {d.get('board_date') or '원문 없음'} / 체계 {d.get('regime') or '원문 없음'} / 추출 {case['extracted_at']} (v{case['extractor_version']})",
           "", "## 1. 거래 개요", "", "| 항목 | 내용 |", "|---|---|",
           f"| 회사 | {case['company']['name']} ({case['company'].get('market') or '–'}, {case['company'].get('corp_code')}) |",
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
           "| 주체 | 대상 | 역할 | 방법 | 가중(자산:수익) | WACC | g | β(U/L) | 멀티플 | 결과 | 범위 | 출처 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in case["valuations"]:
        dcf, rel, res, w = v.get("dcf") or {}, v.get("relative") or {}, v["result"], v.get("weights")
        beta = f"{_fmt(dcf.get('beta_unlevered'))}/{_fmt(dcf.get('beta_levered'))}" if dcf else "–"
        mult = f"{rel.get('multiple_type') or ''} {_fmt(rel.get('multiple'))}".strip() if rel else "–"
        cites = [x for x in (dcf.get("wacc"), res.get("value"), (res.get("range") or {}).get("min"))
                 if isinstance(x, dict) and x.get("cite")][:2]
        out.append(f"| {v['subject']} | {v['target']} | {v['role']} | {v['method']} | "
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
                       ("kd", "세전타인자본비용"), ("tax_rate", "세율"), ("target_de", "목표 D/E"), ("wacc", "WACC"), ("g", "영구성장률")):
            out.append(f"| {lab} | {_fmt(dcf.get(k))} | {_cite_s(dcf.get(k))} |")
        if dcf.get("peers"):
            out.append("")
            out.append("유사기업: " + ", ".join(f"{p['name']} {_fmt(p.get('value'))}" for p in dcf["peers"]))
    out += ["", "## 3. 결론", "", "| 회사 | 기준 | 주당 가액 | 출처 |", "|---|---|---|---|"]
    out += [f"| {p['company']} | {p.get('basis') or '–'} | {_fmt(p['value'])} | {_cite_s(p['value'])} |" for p in co["price_per_share"]]
    for r in co["range"]:
        out.append(f"| {r.get('subject') or '–'} | {r['label']} | {_fmt_range(r['range'])} | {_cite_s(r['range'].get('min'))} |")
    if co.get("ratio"):
        out.append(f"| – | 비율 | {_fmt(co['ratio'])} | {_cite_s(co['ratio'])} |")
    if co.get("transaction_value"):
        out.append(f"| – | 거래금액 | {_fmt(co['transaction_value'])} | {_cite_s(co['transaction_value'])} |")
    out += ["", f"의견: {co.get('opinion_text') or '원문 없음'}", "", "## 4. 민감도", ""]
    if case["sensitivity"]:
        out += ["| 주체 | 대상 | 변수 | 범위 | 출처 |", "|---|---|---|---|---|"]
        out += [f"| {s['subject']} | {s['target']} | {s['variables']} | {_fmt_range(s['range'])} | {_cite_s(s['range'].get('min'))} |"
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
            out.append(f"| {lab} | {_fmt_range(r)} | {_cite_s((r or {}).get('min'))} |")
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


def _cli(argv: list[str]) -> int:
    """uv run python -m dart_mcp.valuation validate <case.json> | verify-cites <case.json> [--sample 8] [--seed N]
    | md <case.json> (같은 이름 .md 생성) | table <dir>"""
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("validate", "verify-cites", "table", "md"):
        print(_cli.__doc__)
        return 2
    cmd, target = argv[0], Path(argv[1])
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
        print(json.dumps({"file": str(target), "valid": not errors, "errors": errors}, ensure_ascii=False, indent=1))
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
