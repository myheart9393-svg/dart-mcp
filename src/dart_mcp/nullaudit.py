"""null 필드 감사(추출 없이): 사례 JSON의 비어 있는 필드를 캐시된 원문 섹션에서 키워드로 찾아 "추출 누락 의심" / "원문에 없음 추정"으로 나눈다.

    uv run python -m dart_mcp.casedb audit-null <dir> [--write]

--write면 사례 JSON `absent_reasons[]`({path, field, reason, basis})를 갱신한다. 값은 채우지 않는다.
reason: "추출 안 함"(원문 섹션에 키워드가 있다 — 추출 누락 의심) · "원문에 없음"(키워드가 없다 — 추정) · "해당 없음"(그 거래 유형에 없는 항목).
원문이 data/ 캐시에 없는 사례는 감사하지 않고 개수만 센다(API를 부르지 않는다).
한계: 섹션 단위 검색이라 같은 섹션의 다른 평가 주체 서술에 걸릴 수 있다(평가 주체가 여럿인 문서는 누락 의심이 과대).
미적용 판정은 키워드 ±80자 창이라 문장 경계를 넘을 수 있다(인접한 다른 항목의 '반영하지 않았다'를 빌려 올 수 있음).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

AUDIT_FIELDS = {
    "size_premium": re.compile(r"규모\s*위험|기업규모|Size\s*(?:Risk\s*)?Premium|SRP|사이즈\s*프리미엄|규모\s*프리미엄", re.I),
    "peers": re.compile(r"Un-?levered|무부채\s*베타|영업\s*베타", re.I),
    "relative": re.compile(r"상대\s*가치"),
    "income_value": re.compile(r"수익\s*가치"),
}
DATE = "2026-10-27"
# 키워드 주변(±80자)의 미적용·미산정 문구 — "Size risk premium을 반영하지 않았습니다"(씨피시스템 2024), "상대가치 | 해당사항 없음" 등
NEGATION = re.compile(r"반영하지\s*않|적용하지\s*않|고려하지\s*않|산정하지\s*(?:않|아니)|해당\s*사항\s*없|해당\s*없음|N/A|미적용|미산정")


def _section_texts(rcept_no: str, section_ids: set[str]) -> dict[str, str] | None:
    from .cache import DisclosureCache

    cache = DisclosureCache()
    if not cache.has(rcept_no):
        return None
    disc = cache.get(rcept_no, None)
    f = disc.get_file("main")
    if f is None:
        return None
    out = {}
    for s in f.sections:
        if not section_ids or s.id in section_ids or any(s.id.startswith(x + ".") for x in section_ids):
            out[s.id] = s.text
    return out


def _cited_sections(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        c = node.get("cite")
        if isinstance(c, dict) and c.get("section_id"):
            out.add(str(c["section_id"]).split(".h")[0])
        for v in node.values():
            out |= _cited_sections(v)
    elif isinstance(node, list):
        for v in node:
            out |= _cited_sections(v)
    return out


def targets(case: dict) -> list[dict]:
    """감사 대상 null 필드: DCF 원소의 size_premium·peers, 본질가치 원소의 income_value, 합병·교환 거래의 상대가치(거래 단위)."""
    out = []
    for i, v in enumerate(case.get("valuations") or []):
        dcf = v.get("dcf") or {}
        if dcf and v.get("purpose") not in ("공정가치평가", "손상검사"):
            if not (dcf.get("size_premium") or {}).get("value") and (dcf.get("size_premium") or {}).get("value") != 0:
                out.append({"path": f"valuations/{i}/dcf/size_premium", "field": "size_premium", "node": v})
            if not dcf.get("peers"):
                out.append({"path": f"valuations/{i}/dcf/peers", "field": "peers", "node": v})
        if v.get("method") == "본질가치" and not (v.get("income_value") or {}).get("value"):
            out.append({"path": f"valuations/{i}/income_value", "field": "income_value", "node": v})
    t = case["deal"]["type"]
    has_rel = any(v.get("method") == "상대가치" or v.get("relative") for v in case.get("valuations") or [])
    if t in ("merger", "split_merger", "share_exchange") and not has_rel:
        out.append({"path": "relative", "field": "relative", "node": case})
    elif t == "split" and not has_rel:
        out.append({"path": "relative", "field": "relative", "node": None, "na": "분할은 상대가치 비교 대상이 아니다(시행세칙 제7조는 합병가액)"})
    return out


def audit_case(case: dict) -> dict:
    tg = targets(case)
    if not tg:
        return {"rcept_no": case["rcept_no"], "items": [], "cached": True}
    secs = _cited_sections(case.get("valuations")) | _cited_sections(case.get("conclusion"))
    texts = _section_texts(case["rcept_no"], secs)
    items = []
    for t in tg:
        if t.get("na"):
            items.append({"path": t["path"], "field": t["field"], "reason": "해당 없음", "basis": t["na"]})
            continue
        if texts is None:
            items.append({"path": t["path"], "field": t["field"], "reason": None, "basis": "원문 캐시 없음"})
            continue
        own = _cited_sections(t["node"]) if t["node"] is not case else secs
        scope = {k: s for k, s in texts.items() if not own or k in own or any(k.startswith(x + ".") for x in own)} or texts
        hit = next(((k, m) for k, s in scope.items() for m in [AUDIT_FIELDS[t["field"]].search(s)] if m), None)
        if hit:
            k, m = hit
            s = scope[k]
            near = s[max(0, m.start() - 80): m.end() + 80]
            quote = f"section {k} offset {m.start()} '{s[max(0, m.start() - 20): m.end() + 20].strip()}'"
            if NEGATION.search(near) and t["field"] != "relative":
                items.append({"path": t["path"], "field": t["field"], "reason": "원문에 없음",
                              "basis": f"키워드 감사 {DATE}: 원문이 미적용 명시 — {quote}"})
            elif NEGATION.search(near):
                items.append({"path": t["path"], "field": t["field"], "reason": "추출 안 함",
                              "basis": f"키워드 감사 {DATE}: 원문이 미산정 명시(relative_value.applied=false로 보강 가능) — {quote}"})
            else:
                items.append({"path": t["path"], "field": t["field"], "reason": "추출 안 함",
                              "basis": f"키워드 감사 {DATE}: {quote} — 추출 누락 의심"})
        else:
            items.append({"path": t["path"], "field": t["field"], "reason": "원문에 없음",
                          "basis": f"키워드 감사 {DATE}: section {', '.join(sorted(scope))}에 키워드 없음 — 원문에 없음 추정"})
    return {"rcept_no": case["rcept_no"], "items": items, "cached": texts is not None}


def audit_cli(directory: Path, argv: list[str]) -> int:
    import logging

    logging.disable(logging.INFO)
    write = "--write" in argv
    summary: dict[str, dict[str, int]] = {}
    uncached, rows = 0, []
    for p in sorted(directory.glob("*.json")):
        if p.name.startswith("_"):
            continue
        case = json.loads(p.read_text(encoding="utf-8"))
        res = audit_case(case)
        if not res["cached"] and res["items"]:
            uncached += 1
        for it in res["items"]:
            key = it["reason"] or "(캐시 없음)"
            summary.setdefault(it["field"], {}).setdefault(key, 0)
            summary[it["field"]][key] += 1
            rows.append({"rcept_no": case["rcept_no"], **it})
        if write:
            kept = [x for x in case.get("absent_reasons") or [] if not str(x.get("basis", "")).startswith("키워드 감사")
                    and x.get("reason") != "해당 없음"]
            case["absent_reasons"] = kept + [{k: it[k] for k in ("path", "field", "reason", "basis")} for it in res["items"] if it["reason"]]
            if not case["absent_reasons"]:
                del case["absent_reasons"]
            p.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"summary": summary, "uncached_cases": uncached, "rows": rows}, ensure_ascii=False, indent=1))
    return 0
