"""가치평가 사례 DB 조회·파생 필드(추출 없이 기존 사례 JSON만으로).

    uv run python -m dart_mcp.casedb derive <dir>                 # deal.spac·spac_basis(파생) 갱신
    uv run python -m dart_mcp.casedb compare <dir> [필터…] --wacc 11 --g 1 --srp 3.5 --beta-l 1.0 [--n 3]
    uv run python -m dart_mcp.casedb export <dir> --csv <경로> [필터…]
    uv run python -m dart_mcp.casedb audit-null <dir>             # null 필드를 캐시 원문 키워드로 감사 → absent_reasons 갱신

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

from .valuation import (_quantiles, _spac_key, add_filter_args, apply_filter_args,
                        d_over_e, flatten_case, load_cases, representative)

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


def compare(rows: list[dict], mine: dict[str, float], n: int = 3) -> dict:
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
    if out["deals"] < SMALL_N:
        out["warning"] = f"표본 부족: 거래 {out['deals']}건"
    return out


# --------------------------------------------------------------------------- export
EXPORT_COLUMNS = ["사례ID", "회사", "거래유형", "이사회결의일", "상태", "SPAC", "업종(KSIC 대분류)", "업종(중분류)", "기관", "역할", "목적",
                  "방법", "가중치", "WACC", "g", "rf", "mrp", "size_premium", "규모위험 미적용", "specific_risk", "beta_u", "beta_l", "ke", "kd", "세율",
                  "D/E", "결과값", "결과 하한", "결과 상한", "결과 단위", "출처 접수번호", "출처 섹션", "출처 offset"]


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
def _filtered(directory: Path, a: Any) -> tuple[list[dict], list[dict]]:
    cases = load_cases(directory)
    rows = []
    for c in cases:
        for i, r in enumerate(flatten_case(c)):
            rows.append({**r, "_idx": i})
    return cases, apply_filter_args(rows, a)


def _cli(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("derive", "compare", "export", "audit-null"):
        print(__doc__)
        return 2
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
    if cmd == "audit-null":
        from .nullaudit import audit_cli

        return audit_cli(directory, argv[2:])
    ap = argparse.ArgumentParser(prog=f"dart_mcp.casedb {cmd}")
    add_filter_args(ap)
    if cmd == "compare":
        for k in COMPARE_ARGS:
            ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float)
        ap.add_argument("--n", type=int, default=3)
    else:
        ap.add_argument("--csv", required=True)
    a = ap.parse_args(argv[2:])
    cases, rows = _filtered(directory, a)
    if cmd == "compare":
        mine = {COMPARE_ARGS[k]: getattr(a, k) for k in COMPARE_ARGS if getattr(a, k) is not None}
        if not mine:
            print("비교할 값을 하나 이상 주세요: " + " ".join(f"--{k.replace('_', '-')}" for k in COMPARE_ARGS))
            return 2
        print(json.dumps({"filters": {k: v for k, v in vars(a).items() if v is not None and k not in COMPARE_ARGS},
                          **compare(rows, mine, a.n)}, ensure_ascii=False, indent=1))
        return 0
    keep = {(r["rcept_no"], r["_idx"]) for r in rows}
    out = export_rows(cases, keep)
    write_csv(out, Path(a.csv))
    print(json.dumps({"csv": a.csv, "rows": len(out), "cases": len({r['사례ID'] for r in out})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
