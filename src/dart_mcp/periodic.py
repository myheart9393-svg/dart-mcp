"""정기공시(pblntf_ty=A) 목록을 사업·반기·분기보고서로 분류하고 최신본을 고른다. 순수 함수만 둔다(단위테스트 대상).

report_nm 예: "사업보고서 (2025.12)", "[기재정정]반기보고서 (2026.06)", "분기보고서 (2026.03)".
같은 종류·같은 기간의 보고서가 여러 번 제출되면(정정·첨부추가 등) 가장 늦게 접수된 것을 쓰고 나머지는 superseded.

정정 종류(correction_kind)를 구분하는 이유: [기재정정]은 본문(재무제표 포함)이 바뀌었을 수 있지만
[첨부정정]·[첨부추가]는 감사보고서 등 첨부만 바뀐 것이다. is_correction은 기재정정일 때만 True.
"""

from __future__ import annotations

import re

_NAME_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)")
_PREFIX_RE = re.compile(r"^\s*((?:\[[^\]]*\]\s*)*)")
# prefix에 여러 꼬리표가 붙으면 앞쪽(본문 영향이 큰 것)을 고른다
CORRECTION_KINDS = ("기재정정", "첨부정정", "첨부추가")


def correction_kind(prefix: str) -> str | None:
    """'[기재정정]' → "기재정정", '[첨부추가]' → "첨부추가", '' 또는 모르는 꼬리표 → None."""
    for kind in CORRECTION_KINDS:
        if f"[{kind}]" in (prefix or "").replace(" ", ""):
            return kind
    return None


def parse_report_nm(report_nm: str) -> dict | None:
    """'[기재정정]반기보고서 (2026.06)' → {"kind": "반기보고서", "period": "2026.06", "prefix": "[기재정정]"}.

    정기보고서가 아니면 None.
    """
    m = _NAME_RE.match(report_nm or "")
    if not m:
        return None
    prefix = _PREFIX_RE.match(report_nm).group(1).strip()
    return {"kind": m.group(1), "period": f"{m.group(2)}.{m.group(3)}", "prefix": prefix}


def interim_reprt_code(kind: str, period: str, fy_end_month: int) -> str | None:
    """결산월 기준 경과 개월수로 reprt_code를 정한다. 12월 결산: 03→11013, 06→11012, 09→11014."""
    if kind == "사업보고서":
        return "11011"
    months = (int(period[5:7]) - fy_end_month) % 12
    return {3: "11013", 6: "11012", 9: "11014"}.get(months)


def _fiscal_year(period: str, fy_end_month: int) -> str:
    """보고 기간이 속한 사업연도(그 회계연도 결산월이 있는 해). 12월 결산이면 기간의 연도 그대로."""
    y, m = int(period[:4]), int(period[5:7])
    return str(y if m <= fy_end_month else y + 1)


def classify_periodic_reports(items: list[dict]) -> dict:
    """search_disclosures 결과 → 최신 사업보고서 + 그 이후 반기·분기보고서.

    items: [{rcept_no, report_nm, rcept_dt}, ...] (순서 무관)
    반환: {"latest_annual", "interim_after_annual", "superseded", "late_corrections", "fy_end_month"}.
    각 보고서: {kind, period, bsns_year, reprt_code, rcept_no, rcept_dt, report_nm, prefix, correction_kind,
    is_correction(기재정정일 때만 True), supersedes[], original_rcept_no, original_rcept_dt(최초 제출본, 정정 없으면 자기 자신)}.
    late_corrections: 최신 사업보고서 최초 제출일 이후(같은 날 포함)에 접수된, 그보다 앞선 기간(사업·반기·분기)의 정정본
    [{kind, period, rcept_no, rcept_dt, correction_kind}] (접수일순). 전기 재무제표 재작성 신호일 수 있다.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for it in items:
        p = parse_report_nm(it.get("report_nm", ""))
        if p is None:
            continue
        groups.setdefault((p["kind"], p["period"]), []).append({**it, **p})

    chosen: list[dict] = []
    superseded: list[dict] = []
    for (kind, period), filings in groups.items():
        # 늦게 접수된 것이 최신본. 같은 날이면 rcept_no가 큰 쪽
        filings.sort(key=lambda x: (x.get("rcept_dt", ""), x.get("rcept_no", "")), reverse=True)
        head, rest = filings[0], filings[1:]
        original = filings[-1]  # 그룹에서 가장 먼저 접수된 것(최초 제출본). 정정이 없으면 head 자신
        chosen.append({
            "kind": kind,
            "period": period,
            "rcept_no": head.get("rcept_no"),
            "rcept_dt": head.get("rcept_dt"),
            "report_nm": head.get("report_nm"),
            "prefix": head["prefix"],
            "correction_kind": correction_kind(head["prefix"]),
            "is_correction": correction_kind(head["prefix"]) == "기재정정",
            "supersedes": [r.get("rcept_no") for r in rest],
            "original_rcept_no": original.get("rcept_no"),
            "original_rcept_dt": original.get("rcept_dt"),
        })
        superseded += [
            {"rcept_no": r.get("rcept_no"), "report_nm": r.get("report_nm"), "rcept_dt": r.get("rcept_dt"),
             "superseded_by": head.get("rcept_no")}
            for r in rest
        ]

    annuals = sorted((c for c in chosen if c["kind"] == "사업보고서"), key=lambda c: c["period"])
    if not annuals:
        return {"latest_annual": None, "interim_after_annual": [], "superseded": superseded,
                "late_corrections": [], "fy_end_month": None}
    latest = annuals[-1]
    fy_end = int(latest["period"][5:7])
    for c in chosen:
        c["reprt_code"] = interim_reprt_code(c["kind"], c["period"], fy_end)
        c["bsns_year"] = _fiscal_year(c["period"], fy_end)
    interim = sorted(
        (c for c in chosen if c["kind"] != "사업보고서" and c["period"] > latest["period"]),
        key=lambda c: c["period"],
    )
    # 기준은 최신 사업보고서의 최초 제출일. 정정본과 같은 날 함께 낸 과거 기간 정정(일괄 정정)도 잡는다
    baseline = latest.get("original_rcept_dt") or ""
    late = sorted(
        (
            {"kind": f["kind"], "period": f["period"], "rcept_no": f.get("rcept_no"), "rcept_dt": f.get("rcept_dt"),
             "correction_kind": correction_kind(f["prefix"])}
            for filings in groups.values()
            for f in filings
            if f["period"] < latest["period"] and correction_kind(f["prefix"])
            and (f.get("rcept_dt") or "") >= baseline
        ),
        key=lambda x: (x["rcept_dt"] or "", x["rcept_no"] or ""),
    )
    return {"latest_annual": latest, "interim_after_annual": interim, "superseded": superseded,
            "late_corrections": late, "fy_end_month": fy_end}
