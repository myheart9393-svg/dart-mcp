"""정기공시(pblntf_ty=A) 목록을 사업·반기·분기보고서로 분류하고 최신본을 고른다. 순수 함수만 둔다(단위테스트 대상).

report_nm 예: "사업보고서 (2025.12)", "[기재정정]반기보고서 (2026.06)", "분기보고서 (2026.03)".
같은 종류·같은 기간의 보고서가 여러 번 제출되면(정정·첨부추가 등) 가장 늦게 접수된 것을 쓰고 나머지는 superseded.
"""

from __future__ import annotations

import re

_NAME_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)")
_PREFIX_RE = re.compile(r"^\s*((?:\[[^\]]*\]\s*)*)")


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
    반환: {"latest_annual", "interim_after_annual", "superseded", "fy_end_month"}.
    각 보고서: {kind, period, bsns_year, reprt_code, rcept_no, rcept_dt, report_nm, is_correction, supersedes[]}.
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
        chosen.append({
            "kind": kind,
            "period": period,
            "rcept_no": head.get("rcept_no"),
            "rcept_dt": head.get("rcept_dt"),
            "report_nm": head.get("report_nm"),
            "is_correction": bool(head["prefix"]),
            "supersedes": [r.get("rcept_no") for r in rest],
        })
        superseded += [
            {"rcept_no": r.get("rcept_no"), "report_nm": r.get("report_nm"), "rcept_dt": r.get("rcept_dt"),
             "superseded_by": head.get("rcept_no")}
            for r in rest
        ]

    annuals = sorted((c for c in chosen if c["kind"] == "사업보고서"), key=lambda c: c["period"])
    if not annuals:
        return {"latest_annual": None, "interim_after_annual": [], "superseded": superseded, "fy_end_month": None}
    latest = annuals[-1]
    fy_end = int(latest["period"][5:7])
    for c in chosen:
        c["reprt_code"] = interim_reprt_code(c["kind"], c["period"], fy_end)
        c["bsns_year"] = _fiscal_year(c["period"], fy_end)
    interim = sorted(
        (c for c in chosen if c["kind"] != "사업보고서" and c["period"] > latest["period"]),
        key=lambda c: c["period"],
    )
    return {"latest_annual": latest, "interim_after_annual": interim, "superseded": superseded, "fy_end_month": fy_end}
