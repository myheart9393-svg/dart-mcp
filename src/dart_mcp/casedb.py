"""가치평가 사례 DB 조회·파생 필드(추출 없이 기존 사례 JSON만으로).

    uv run python -m dart_mcp.casedb derive <dir>                 # deal.spac·spac_basis(파생) 갱신
    uv run python -m dart_mcp.casedb compare <dir> [필터…] --wacc 11 --g 1 --srp 3.5 --beta-l 1.0 [--n 3]
    uv run python -m dart_mcp.casedb export <dir> --csv <경로> [필터…]
    uv run python -m dart_mcp.casedb audit-null <dir>             # null 필드를 캐시 원문 키워드로 감사 → absent_reasons 갱신
    uv run python -m dart_mcp.casedb finalize <json|dir> [--dry-run] [--offline]   # 후처리: induty·spac·status 초기값·relative kind·regime
    uv run python -m dart_mcp.casedb backfill-queue <dir> [--all] [--md <경로>]   # 보강 대기 목록(추출 안 함; --all이면 원문에 없음도)
    uv run python -m dart_mcp.casedb diff <case.json> [--against <git rev | 다른 json>]   # 보강 전후 필드별 diff(기본 HEAD)

필터는 valuation stats와 같다(--from/--to 이사회 결의일, --deal-type, --method, --industry, --regime, --firm/--as,
--status/--exclude-status, --spac). 통계는 거래 단위(valuation.representative: 외부평가 값 우선, 없으면 중앙값).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any

from .valuation import (_quantiles, _spac_key, add_filter_args, apply_filter_args, dedup_cases, median_stability, precedent_table,
                        stability_warnings,
                        d_over_e, flatten_case, load_cases, representative, sample_warnings)

# --------------------------------------------------------------------------- SPAC 판정
SPAC_NAME_RE = re.compile(r"기업인수목적|스팩|SPAC", re.I)
# 문구: SPAC 단어, 또는 시행령 176조의5 ③(기업인수목적회사 합병 특례). 단독 "특례"는 다른 특례(계열사 등)와 섞여 쓰지 않는다
SPAC_TEXT_RE = re.compile(r"기업인수목적|스팩|SPAC|176조의5\s*(?:제\s*)?(?:③|3\s*항)", re.I)


def _texts(case: dict) -> list[tuple[str, str]]:
    """SPAC 문구를 찾을 기존 필드(경로, 문자열)."""
    out = [("external_valuation.basis_text", (case.get("external_valuation") or {}).get("basis_text") or ""),
           ("deal.relation_text", (case.get("deal") or {}).get("relation_text") or "")]
    for i, v in enumerate(case.get("valuations") or []):
        out.append((f"valuations/{i}.weights.basis", str((v.get("weights") or {}).get("basis") or "")))
        out.append((f"valuations/{i}.note", v.get("note") or ""))
    out += [(f"notes/{i}", n) for i, n in enumerate(case.get("notes") or [])]
    return out


def derive_spac(case: dict) -> tuple[bool | str, str]:
    """→ (True|False|"unknown", 근거). 합병·분할합병만 판정(그 밖은 False — SPAC 상장 IPO는 사례 대상이 아니다).

    이름(회사명·합병 상대방에 기업인수목적·스팩·SPAC)과 문구(외부평가 근거·가중치 근거·note의 SPAC 단어 또는 176조의5 ③)를 함께 본다.
    둘 다 없으면, 문구를 볼 필드(외부평가 근거·원소 note)가 비어 있을 때만 unknown.
    """
    if case["deal"]["type"] not in ("merger", "split_merger"):
        return False, "합병·분할합병 아님"
    names = [("company.name", case["company"]["name"]), ("deal.counterparty", case["deal"].get("counterparty") or "")]
    by_name = [p for p, s in names if SPAC_NAME_RE.search(s)]
    by_text = []
    for p, s in _texts(case):
        m = SPAC_TEXT_RE.search(s)
        if m:
            by_text.append(f"{p} '{s[max(0, m.start() - 15): m.end() + 15].strip()}'")
    if by_name or by_text:
        parts = ([f"이름: {', '.join(by_name)}"] if by_name else []) + ([f"문구: {by_text[0]}" + (f" 외 {len(by_text) - 1}곳" if len(by_text) > 1 else "")] if by_text else [])
        return True, "; ".join(parts)
    has_text = any(s.strip() for p, s in _texts(case) if p.startswith(("external_valuation", "valuations")))
    return (False, "이름·문구에 SPAC 표시 없음") if has_text else ("unknown", "판정할 문구 필드가 비어 있음")


def spac_sources(case: dict) -> str:
    """판정 근거 종류: name | text | both | none(보고용)."""
    v, basis = derive_spac(case)
    n, t = basis.startswith("이름:"), "문구:" in basis
    return "both" if n and t else "name" if n else "text" if t else "none"


# --------------------------------------------------------------------------- compare
COMPARE_ARGS = {"wacc": "wacc", "g": "g", "srp": "size_premium", "specific": "specific_risk", "rf": "rf", "mrp": "mrp", "beta_u": "beta_u",
                "beta_l": "beta_l", "ke": "ke", "kd": "kd", "tax": "tax_rate", "de": "d_over_e"}
SMALL_N = 5


def per_deal(rows: list[dict], var: str) -> dict[str, float]:
    vals: dict[str, list] = {}
    for r in rows:
        if r.get(var) is not None:
            vals.setdefault(r["rcept_no"], []).append((r.get("role"), float(r[var])))
    return {k: representative(v) for k, v in vals.items()}


def percentile(xs: list[float], x: float) -> float:
    """중간순위 백분위: (x보다 작은 수 + 같은 수/2) / n × 100."""
    return (sum(1 for v in xs if v < x) + 0.5 * sum(1 for v in xs if v == x)) / len(xs) * 100


def compare(rows: list[dict], mine: dict[str, float], n: int = 3, spac_filter: str | None = None) -> dict:
    """내 값(변수 → 값) vs 선례 분포. 최근접은 내가 준 변수의 표준화 거리 sqrt(mean(z²)), 변수가 len(mine)−1개 이상 있는 거래만."""
    reps = {var: per_deal(rows, var) for var in mine}
    out: dict[str, Any] = {"deals": len({r["rcept_no"] for r in rows}), "variables": {}, "nearest": [],
                           "size_premium_not_applied": len({r["rcept_no"] for r in rows if r.get("size_premium_not_applied")})}
    sd = {}
    for var, x in mine.items():
        xs = list(reps[var].values())
        if not xs:
            out["variables"][var] = {"n": 0, "mine": x, "note": "표본 없음"}
            continue
        q = _quantiles(xs)
        sd[var] = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        out["variables"][var] = {**{k: q[k] for k in ("n", "median", "q1", "q3", "min", "max")}, "mine": x,
                                 "percentile": round(percentile(xs, x), 1),
                                 **({"note": f"표본 부족(n<{SMALL_N})"} if len(xs) < SMALL_N else {})}
        stab = median_stability(reps[var])
        if stab:
            out["variables"][var]["median_stability"] = stab
    need = max(1, len(mine) - 1)
    info = {}
    for r in rows:
        info.setdefault(r["rcept_no"], r)
    cand = []
    for rno in info:
        ks = [v for v in mine if rno in reps[v] and sd.get(v)]
        if len(ks) < need:
            continue
        d = math.sqrt(sum(((reps[v][rno] - mine[v]) / sd[v]) ** 2 for v in ks) / len(ks))
        cand.append((d, rno, ks))
    for d, rno, ks in sorted(cand)[:n]:
        r = info[rno]
        ext = sorted({x["subject"] for x in rows if x["rcept_no"] == rno and x.get("role") == "외부평가" and x.get("subject")})
        out["nearest"].append({"distance": round(d, 3), "rcept_no": rno, "company": r["company"], "board_date": r.get("board_date"),
                               "firm": ", ".join(ext) or None, "spac": _spac_key(r.get("spac")), "status": r.get("status"),
                               "industry": r.get("industry"), **{v: reps[v].get(rno) for v in mine}})
    out["warnings"] = sample_warnings(rows, tuple(mine), spac_filter=spac_filter) + stability_warnings(out["variables"])
    near_spac = sum(1 for x in out["nearest"] if x["spac"] == "true")
    if out["nearest"] and near_spac * 2 > len(out["nearest"]):
        out["warnings"].append(f"최근접 선례 {len(out['nearest'])}건 중 SPAC {near_spac}건 — 비SPAC 선례는 --spac false로 다시 본다")
    if out["deals"] < SMALL_N:
        out["warning"] = f"표본 부족: 거래 {out['deals']}건"
    # 최근접 선례 표(SPAC·상태 열 포함) — 보고서에 그대로 붙인다
    cols = list(mine)
    lines = ["| 거리 | 회사 | 이사회결의일 | 외부평가 | SPAC | 상태 | " + " | ".join(cols) + " |",
             "|---|---|---|---|---|---|" + "---|" * len(cols)]
    for x in out["nearest"]:
        lines.append(f"| {x['distance']} | {x['company']} | {x['board_date'] or ''} | {x['firm'] or ''} | {x['spac']} | "
                     f"{x['status'] or ''} | " + " | ".join("" if x[v] is None else f"{x[v]:g}" for v in cols) + " |")
    out["nearest_table"] = "\n".join(lines)
    return {"warnings": out.pop("warnings"), **out}


# --------------------------------------------------------------------------- export
EXPORT_COLUMNS = ["사례ID", "회사", "거래유형", "이사회결의일", "상태", "SPAC", "업종(KSIC 대분류)", "업종(중분류)", "기관", "역할", "목적",
                  "방법", "가중치", "WACC", "g", "rf", "mrp", "size_premium", "규모위험 미적용", "specific_risk", "beta_u", "beta_l", "ke", "kd", "세율",
                  "D/E", "상대가치(거래)", "상대가치 사유", "결과값", "결과 하한", "결과 상한", "결과 단위", "출처 접수번호", "출처 섹션", "출처 offset"]


def export_rows(cases: list[dict], keep: set[tuple[str, int]] | None = None) -> list[dict]:
    from .industry import section

    v = lambda x: x.get("value") if isinstance(x, dict) else None  # noqa: E731
    out = []
    for c in cases:
        for i, e in enumerate(c.get("valuations") or []):
            if keep is not None and (c["rcept_no"], i) not in keep:
                continue
            dcf = e.get("dcf") or {}
            res = e.get("result") or {}
            rng = res.get("range") or {}
            w = e.get("weights") or {}
            src = next((x for x in (res.get("value"), (rng or {}).get("min"), dcf.get("wacc")) if isinstance(x, dict) and x.get("cite")), None)
            cite = (src or {}).get("cite") or {}
            out.append({
                "사례ID": c["rcept_no"], "회사": c["company"]["name"], "거래유형": c["deal"]["type"],
                "이사회결의일": c["deal"].get("board_date"), "상태": c["deal"].get("status"), "SPAC": _spac_key(c["deal"].get("spac")),
                "업종(KSIC 대분류)": section(c["company"].get("induty_code")), "업종(중분류)": flatten_case(c)[0].get("industry"),
                "기관": e.get("subject"), "역할": e.get("role"), "목적": e.get("purpose"), "방법": e.get("method"),
                "가중치": f"{w['asset']:g}:{w['income']:g}" if w.get("asset") is not None and w.get("income") is not None else None,
                "WACC": v(dcf.get("wacc")), "g": v(dcf.get("g")), "rf": v(dcf.get("rf")), "mrp": v(dcf.get("mrp")),
                "size_premium": None if dcf.get("size_premium_applied") is False else v(dcf.get("size_premium")),
                "규모위험 미적용": True if dcf.get("size_premium_applied") is False else None,
                "specific_risk": v(dcf.get("specific_risk")),
                "beta_u": v(dcf.get("beta_unlevered")), "beta_l": v(dcf.get("beta_levered")), "ke": v(dcf.get("ke")),
                "kd": v(dcf.get("kd")), "세율": v(dcf.get("tax_rate")), "D/E": d_over_e(dcf) if dcf else None,
                "상대가치(거래)": (c.get("relative_value") or {}).get("kind"), "상대가치 사유": (c.get("relative_value") or {}).get("reason"),
                "결과값": v(res.get("value")), "결과 하한": v((rng or {}).get("min")), "결과 상한": v((rng or {}).get("max")),
                "결과 단위": res.get("unit"), "출처 접수번호": cite.get("rcept_no") or c["rcept_no"] if cite else None,
                "출처 섹션": cite.get("section_id"), "출처 offset": cite.get("offset"),
            })
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    """UTF-8 BOM(엑셀에서 바로 열린다)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------- CLI
# --------------------------------------------------------------------------- 후처리(finalize)
REGIME_AMENDED_FROM = "2026-12-09"  # 개정 자본시장법(공정가액) 적용 이사회 결의 시작일 — 그 전 결의는 현행 기준시가 체계
_REGIME_TYPES = ("merger", "share_exchange", "split_merger")
_RELATIVE_TYPES = ("merger", "share_exchange", "split_merger")
# 거래 단위 상대가치 규칙 문구(v1.6.2 이관과 같은 두 문구 + 일반 미산정 문구). (정규식, kind, 사유)
_RELATIVE_RULES = (
    (re.compile(r"상대가치\s*등은\s*별도로\s*기재하지\s*않"), "기재 생략",
     "자산가치 및 수익가치, 상대가치 등은 별도로 기재하지 않음(상장사 간 기준주가 합병)"),
    # "3사 미만이므로 … 산정하지 아니" — 사실 진술만. "3사 미만인 경우에는 … 산정하지 아니하며"(규정 설명, 위메이드맥스·나노엔텍)는 제외
    (re.compile(r"유사회사[^\n]{0,120}?3\s*사\s*미만(?:이므로|으로|이어서)[^\n]{0,80}?산정하지\s*(?:않|아니)"), "산정하지 않음",
     "유사회사 기준(3사 이상)을 충족하는 상장법인이 없어 상대가치를 산정하지 않음"),
)


def _relative_from_text(texts: dict[str, str]) -> dict | None:
    for rx, kind, reason in _RELATIVE_RULES:
        for sid, t in texts.items():
            m = rx.search(t)
            if m:
                return {"applied": False, "kind": kind, "reason": reason,
                        "cite": {"section_id": sid, "offset": m.start(), "file_id": "main"}, "derived": True}
    return None


def _relative_kind_from_reason(rv: dict) -> str | None:
    if rv.get("applied") is True:
        return "산정"
    r = rv.get("reason")
    t = (r.get("text") if isinstance(r, dict) else r) or ""
    if "별도로 기재하지 않" in t and not re.search(r"산정하지\s*(?:않|아니)", t):
        return "기재 생략"
    if rv.get("applied") is False and re.search(r"산정하지\s*(?:않|아니)|미산정|적용하지\s*않", t):
        return "산정하지 않음"
    return None


def finalize(case: dict, *, today: str | None = None, network: bool = True,
             section_texts: Any = None) -> list[dict]:
    """사례 JSON 후처리를 한 번에: induty_code·deal.spac/spac_basis·deal.status 초기값·relative_value.kind 규칙 분류·regime.
    이미 값이 있는 칸은 건드리지 않는다. 바뀐 칸 목록 [{field, old, new, basis}]을 돌려준다(case는 제자리 수정).
    network=False면 기업개황 조회(induty_code)를 건너뛴다. section_texts(rcept_no, ids) → {id: text}는 상대가치 규칙 분류용(기본: 캐시 원문)."""
    from .valuation import STATUS_PENDING_DAYS, _KIND_WORDS, _date

    today = today or __import__("datetime").date.today().strftime("%Y%m%d")
    d, changes = case["deal"], []

    def put(field: str, old: Any, new: Any, basis: str) -> None:
        changes.append({"field": field, "old": old, "new": new, "basis": basis})

    if network and not case["company"].get("induty_code"):
        from .industry import fill_case

        res = fill_case(case)
        if res["changed"]:
            put("company.induty_code", None, res["induty_code"], res["reason"] or "기업개황 induty_code")
    if d.get("spac") is None:
        val, basis = derive_spac(case)
        d["spac"], d["spac_basis"] = val, basis
        put("deal.spac", None, val, basis)
    if d.get("status") is None and d["type"] in _KIND_WORDS:
        days = (_date(today) - _date(case["rcept_no"][:8])).days
        st = "진행" if days <= STATUS_PENDING_DAYS else "미확인"
        d["status"], d["status_source"] = st, None
        put("deal.status", None, st, f"초기값(본문 접수 후 {days}일, 공시 목록 미조회) — valuation status로 갱신")
    if d.get("regime") is None:
        if d["type"] == "ipo":
            d["regime"] = "IPO"
            put("deal.regime", None, "IPO", "거래 유형 IPO")
        elif d["type"] in _REGIME_TYPES and d.get("board_date") and d["board_date"] < REGIME_AMENDED_FROM:
            d["regime"] = "기준시가"
            put("deal.regime", None, "기준시가", f"이사회 결의 {d['board_date']} < 개정법 적용 {REGIME_AMENDED_FROM}")
    if d["type"] in _RELATIVE_TYPES:
        rv = case.get("relative_value")
        if rv is not None and rv.get("kind") is None:
            k = _relative_kind_from_reason(rv)
            if k:
                rv["kind"] = k
                put("relative_value.kind", None, k, "applied·사유 문구 규칙 분류")
        elif rv is None:
            if section_texts is None:
                from .nullaudit import _section_texts as section_texts
            texts = section_texts(case["rcept_no"], set()) or {}
            new = _relative_from_text(texts)
            if new:
                case["relative_value"] = new
                put("relative_value", None, new["kind"], f"캐시 원문 규칙 문구 section {new['cite']['section_id']} @{new['cite']['offset']}")
    if changes:
        stamp = f"finalize {today[:4]}-{today[4:6]}-{today[6:]}: " + ", ".join(f"{c['field']}={c['new']}" for c in changes)
        case["notes"] = [*(case.get("notes") or []), stamp]
    return changes


def backfill_queue(cases: list[dict], include_absent: bool = False) -> dict:
    """사례 absent_reasons(audit-null --write 결과) → 보강 대기 목록. 기본은 "추출 안 함"(원문에 키워드가 있어 누락 의심)만,
    include_absent면 "원문에 없음"도. 행: {rcept_no, company, field, path, reason, basis}."""
    want = {"추출 안 함"} | ({"원문에 없음"} if include_absent else set())
    rows = []
    for c in cases:
        for x in c.get("absent_reasons") or []:
            if x.get("reason") in want:
                rows.append({"rcept_no": c["rcept_no"], "company": (c.get("company") or {}).get("name"), "field": x.get("field"),
                             "path": x.get("path"), "reason": x.get("reason"), "basis": x.get("basis")})
    rows.sort(key=lambda r: (r["rcept_no"], r["path"] or ""))
    by_field: dict[str, int] = {}
    for r in rows:
        by_field[r["field"]] = by_field.get(r["field"], 0) + 1
    md = ["| rcept_no | 회사 | 필드 | 경로 | 사유 | 근거 |", "|---|---|---|---|---|---|"]
    md += [f"| {r['rcept_no']} | {r['company']} | {r['field']} | {r['path']} | {r['reason']} | {(r['basis'] or '')[:90]} |" for r in rows]
    return {"cases": len({r["rcept_no"] for r in rows}), "fields": len(rows), "by_field": by_field, "rows": rows,
            "markdown": "\n".join(md)}


def case_diff(old: Any, new: Any, path: str = "") -> list[dict]:
    """사례 JSON 두 개의 필드별 차이: [{op: added|removed|changed, path, old, new}]. 새로 생기거나 없어진 노드는 통째로 한 줄."""
    out: list[dict] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in list(old) + [k for k in new if k not in old]:
            p = f"{path}/{k}"
            if k not in new:
                out.append({"op": "removed", "path": p, "old": old[k], "new": None})
            elif k not in old or (old[k] is None and new[k] is not None):
                out.append({"op": "added", "path": p, "old": old.get(k), "new": new[k]})
            elif new[k] is None and old[k] is not None:
                out.append({"op": "removed", "path": p, "old": old[k], "new": None})
            else:
                out += case_diff(old[k], new[k], p)
        return out
    if isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            p = f"{path}/{i}"
            if i >= len(new):
                out.append({"op": "removed", "path": p, "old": old[i], "new": None})
            elif i >= len(old):
                out.append({"op": "added", "path": p, "old": None, "new": new[i]})
            else:
                out += case_diff(old[i], new[i], p)
        return out
    if old != new:
        out.append({"op": "changed", "path": path, "old": old, "new": new})
    return out


def _filtered(directory: Path, a: Any) -> tuple[list[dict], list[dict]]:
    cases, _dropped = dedup_cases(load_cases(directory))
    rows = []
    for c in cases:
        for i, r in enumerate(flatten_case(c)):
            rows.append({**r, "_idx": i})
    return cases, apply_filter_args(rows, a)


def _cli(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("derive", "compare", "export", "audit-null", "backfill-queue", "diff", "finalize"):
        print(__doc__)
        return 2
    if argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, directory = argv[0], Path(argv[1])
    if cmd == "derive":
        counts: dict[str, int] = {}
        for p in sorted(directory.glob("*.json")):
            if p.name.startswith("_"):
                continue
            c = json.loads(p.read_text(encoding="utf-8"))
            val, basis = derive_spac(c)
            c["deal"]["spac"], c["deal"]["spac_basis"] = val, basis
            p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
            counts[_spac_key(val)] = counts.get(_spac_key(val), 0) + 1
        print(json.dumps({"spac": counts}, ensure_ascii=False))
        return 0
    if cmd == "finalize":
        paths = [directory] if directory.is_file() else [p for p in sorted(directory.glob("*.json")) if not p.name.startswith("_")]
        dry, out = "--dry-run" in argv, []
        for p in paths:
            case = json.loads(p.read_text(encoding="utf-8"))
            ch = finalize(case, network="--offline" not in argv)
            if ch:
                out.append({"rcept_no": case["rcept_no"], "company": case["company"]["name"], "changes": ch})
                if not dry:
                    p.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
        by: dict[str, int] = {}
        for r in out:
            for c in r["changes"]:
                by[c["field"]] = by.get(c["field"], 0) + 1
        print(json.dumps({"files": len(paths), "changed": len(out), "dry_run": dry, "by_field": by, "rows": out},
                         ensure_ascii=False, indent=1))
        return 0
    if cmd == "backfill-queue":
        q = backfill_queue(load_cases(directory), include_absent="--all" in argv)
        if "--md" in argv:
            mp = Path(argv[argv.index("--md") + 1])
            mp.write_text(f"# 보강 대기 목록 ({q['cases']}건 사례, {q['fields']}칸)\n\n" + q["markdown"] + "\n", encoding="utf-8")
        print(json.dumps({k: q[k] for k in ("cases", "fields", "by_field", "rows")}, ensure_ascii=False, indent=1))
        return 0
    if cmd == "diff":
        import subprocess

        new = json.loads(directory.read_text(encoding="utf-8"))
        against = argv[argv.index("--against") + 1] if "--against" in argv else "HEAD"
        if Path(against).is_file():
            old, src = json.loads(Path(against).read_text(encoding="utf-8")), against
        else:
            rel = directory.resolve().relative_to(Path.cwd().resolve()).as_posix()
            r = subprocess.run(["git", "show", f"{against}:{rel}"], capture_output=True, text=True, encoding="utf-8")
            if r.returncode != 0:
                print(json.dumps({"error": f"git show {against}:{rel} 실패: {r.stderr.strip()[:200]}"}, ensure_ascii=False))
                return 1
            old, src = json.loads(r.stdout), f"{against}:{rel}"
        d = case_diff(old, new)
        print(json.dumps({"against": src, "changes": len(d),
                          "by_op": {op: sum(1 for x in d if x["op"] == op) for op in ("added", "changed", "removed")},
                          "diff": d}, ensure_ascii=False, indent=1))
        return 0
    if cmd == "audit-null":
        from .nullaudit import audit_cli

        return audit_cli(directory, argv[2:])
    ap = argparse.ArgumentParser(prog=f"dart_mcp.casedb {cmd}")
    add_filter_args(ap)
    if cmd == "compare":
        for k in COMPARE_ARGS:
            ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float)
        ap.add_argument("--n", type=int, default=3)
        ap.add_argument("--list", nargs="?", const=30, type=int, default=None, metavar="N",
                        help="개별 선례 표(최근 결의일 순 N건, 기본 30)를 함께 낸다")
    else:
        ap.add_argument("--csv", required=True)
    a = ap.parse_args(argv[2:])
    cases, rows = _filtered(directory, a)
    if cmd == "compare":
        mine = {COMPARE_ARGS[k]: getattr(a, k) for k in COMPARE_ARGS if getattr(a, k) is not None}
        if not mine:
            print("비교할 값을 하나 이상 주세요: " + " ".join(f"--{k.replace('_', '-')}" for k in COMPARE_ARGS))
            return 2
        res = compare(rows, mine, a.n, spac_filter=a.spac)
        if a.list:
            res["precedents"] = precedent_table(rows, tuple(mine), limit=a.list)
        # n(최근접 수)은 필터가 아니다 — filters에 섞으면 표본 수로 읽힌다(retro B6)
        print(json.dumps({"warnings": res.pop("warnings"), "nearest_n": a.n,
                          "filters": {k: v for k, v in vars(a).items() if v is not None and k not in COMPARE_ARGS and k not in ("n", "list")},
                          **res}, ensure_ascii=False, indent=1))
        return 0
    keep = {(r["rcept_no"], r["_idx"]) for r in rows}
    out = export_rows(cases, keep)
    write_csv(out, Path(a.csv))
    print(json.dumps({"warnings": sample_warnings(rows, spac_filter=a.spac), "csv": a.csv, "rows": len(out),
                      "cases": len({r['사례ID'] for r in out})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
