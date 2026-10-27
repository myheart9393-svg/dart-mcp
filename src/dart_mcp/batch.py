"""/dart-valuation-batch의 결정적인 부분: 대상 목록(큐) 만들기, 진행 상태 저장, _batch_<날짜>.md 렌더.

    uv run python -m dart_mcp.batch plan   <bgn> <end> [--grade full] [--limit N] [--state reports/valuations/_batch_<날짜>.json]
    uv run python -m dart_mcp.batch record --state <state.json> <rcept_no> <ok|fail|skip> [--reason ...] [--calls N] [--chars N] [--seconds N]
    uv run python -m dart_mcp.batch report --state <state.json>      # → 같은 이름 .md

plan 규칙:
- search_valuation_disclosures(bgn, end, listed_only=False, kinds=전부+유상증자)에서 grade가 맞는 거래.
- 증권신고서(지분증권)은 corp_cls만으로는 IPO/유상증자를 못 가린다(valuation.equity_kind 설명; 상장폐지 후 E가 된 회사의 유상증자도 있다)
  → 전부 본문을 받아 equity_kind로 확인.
  유상증자면 skip:rights_offering, 판단 불가면 skip:equity_unknown.
- SPAC(기업인수목적회사) IPO는 공모가가 고정(평가 없음)이라 skip:spac.
- reports/valuations/에 이미 있는 거래(rcept_no·original·supersedes 중 하나)는 skip:existing.
- 추출 대상은 status="todo", 순서는 접수일 오래된 것부터. --limit은 todo 건수 상한(나머지는 status="queued").
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from .valuation import DEAL_LABELS, SPAC_RE, equity_kind

CASE_DIR = Path("reports/valuations")
EQUITY_SCAN_CHARS = 300_000


def _existing_keys(case_dir: Path) -> set[str]:
    keys: set[str] = set()
    for p in case_dir.glob("*.json"):
        if p.name.startswith("_"):
            continue
        c = json.loads(p.read_text(encoding="utf-8"))
        # related_rcept_nos는 넣지 않는다: summary(B)만 뽑은 거래의 짝 증권신고서(C)는 아직 추출 대상이다
        keys |= {c["rcept_no"], c.get("original_rcept_no") or ""} - {""}
        keys.add(p.stem)
    return keys


def _main_text(rcept_no: str, limit: int = EQUITY_SCAN_CHARS) -> str:
    from . import server

    disc = server._load(rcept_no)
    f = disc.get_file("main")
    if f is None:
        return ""
    parts, n = [], 0
    for s in f.sections:
        if s.level > 1:
            continue
        parts.append(s.text)
        n += len(s.text)
        if n >= limit:
            break
    return "".join(parts)[:limit]


def plan(bgn: str, end: str, grade: str = "full", limit: int | None = None, case_dir: Path = CASE_DIR,
         kinds: list[str] | None = None) -> dict:
    """kinds: 거래 유형(영문 코드·한글 별칭). 생략하면 전부(유상증자 포함 — 본문으로 IPO를 가리려고)."""
    from . import server

    res = server.search_valuation_disclosures(bgn, end, kinds=kinds or sorted(DEAL_LABELS), listed_only=False,
                                              max_results=100_000)
    if "error" in res:
        raise RuntimeError(res["error"])
    existing = _existing_keys(case_dir)
    items = []
    for d in sorted(res["deals"], key=lambda x: (x["original_rcept_dt"] or x["rcept_dt"], x["rcept_no"])):
        if grade and d["source_grade"] != grade:
            continue
        it = {k: d[k] for k in ("rcept_no", "body_rcept_no", "original_rcept_no", "report_nm", "rcept_dt", "corp_code",
                                "corp_name", "corp_cls", "market", "filing_type", "deal_type", "deal_label",
                                "source_grade", "supersedes", "related_rcept_nos")}
        keys = {d["rcept_no"], d["body_rcept_no"], d.get("original_rcept_no") or "", *d["supersedes"]} - {""}
        it["status"], it["reason"] = "todo", None
        if keys & existing:
            it["status"], it["reason"] = "skip", "existing"
        elif d["deal_type"] == "ipo" and SPAC_RE.search(d["corp_name"] or ""):
            it["status"], it["reason"] = "skip", "spac"
        elif d["deal_type"] in ("rights_offering", "ipo"):
            # corp_cls는 조회 시점 상태라 양쪽으로 틀린다: 올해 상장한 IPO는 K·Y, 상장폐지 후 E가 된 회사의 유상증자는 IPO로 보인다
            # (코이즈 20260122000389: corp_cls E, 주주배정 유상증자 — 배치 1차 실측)
            kind = equity_kind(_main_text(d["body_rcept_no"]))
            it["equity_kind"] = kind
            if kind == "ipo" and SPAC_RE.search(d["corp_name"] or ""):
                it["status"], it["reason"] = "skip", "spac"
            elif kind == "ipo":
                it["deal_type"], it["deal_label"] = "ipo", DEAL_LABELS["ipo"]
            else:
                it["status"], it["reason"] = "skip", "rights_offering" if kind else "equity_unknown"
        items.append(it)
    todo = [i for i in items if i["status"] == "todo"]
    if limit is not None:
        for i in todo[limit:]:
            i["status"] = "queued"
    return {"bgn_de": bgn, "end_de": end, "grade": grade, "limit": limit, "kinds": kinds, "created_at": _now(),
            "scan": {"total_deals": res["total"], "api_pages": res["api_pages"]}, "items": items}


def ensure_company(it: dict, case_dir: Path = CASE_DIR) -> dict | None:
    """ok로 기록한 사례 JSON의 company.corp_code(비면 큐의 값)·induty_code(비면 기업개황)를 채운다."""
    from .industry import fill_case

    path = case_dir / f"{it['body_rcept_no']}.json"
    if not path.exists():
        return None
    case = json.loads(path.read_text(encoding="utf-8"))
    comp = case["company"]
    fixed = not comp.get("corp_code")
    comp["corp_code"] = comp.get("corp_code") or it["corp_code"]
    res = fill_case(case)
    if fixed or res["changed"]:
        path.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"induty_code": res["induty_code"], "reason": res["reason"]}


def _now() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")


def record(state: dict, rcept_no: str, status: str, reason: str | None = None, **metrics) -> dict:
    for it in state["items"]:
        if rcept_no in (it["rcept_no"], it["body_rcept_no"]):
            it["status"], it["reason"] = status, reason
            it.update({k: v for k, v in metrics.items() if v is not None})
            it["done_at"] = _now()
            return it
    raise KeyError(rcept_no)


def render(state: dict) -> str:
    items = state["items"]
    by: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for it in items:
        by[it["status"]] = by.get(it["status"], 0) + 1
        if it["status"] in ("fail", "skip"):
            key = f"{it['status']}: {it['reason']}"
            reasons[key] = reasons.get(key, 0) + 1
    done = [i for i in items if i["status"] in ("ok", "fail")]
    tot = {k: sum(i.get(k) or 0 for i in done) for k in ("calls", "chars", "seconds")}
    out = [f"# 가치평가 일괄 추출 {state['bgn_de']}–{state['end_de']} (등급 {state['grade']})",
           f"> 계획 {state['created_at']} / 스캔 거래 {state['scan']['total_deals']}건, list.json {state['scan']['api_pages']}페이지 / "
           f"상태 {json.dumps(by, ensure_ascii=False)}", "",
           "## 요약", "", "| 구분 | 건수 |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in sorted(by.items())]
    out += ["", "| 실패·제외 사유 | 건수 |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in sorted(reasons.items(), key=lambda x: -x[1])] or ["| – | 0 |"]
    if done:
        out += ["", f"추출 {len(done)}건 합계: 툴 호출 {tot['calls']:,}회, 읽은 글자 {tot['chars']:,}자, 소요 {tot['seconds']:,}초 "
                f"(건당 평균 {tot['calls'] / len(done):.1f}회 · {tot['chars'] / len(done):,.0f}자 · {tot['seconds'] / len(done):,.0f}초)"]
    out += ["", "## 건별", "", "| # | 접수일 | 회사 | 거래 | rcept_no(본문) | 상태 | 사유 | 호출 | 글자 | 초 | 리뷰 |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, it in enumerate(items, 1):
        out.append(f"| {n} | {it['rcept_dt']} | {it['corp_name']} | {it['deal_label']} | {it['body_rcept_no']} | {it['status']} | "
                   f"{it.get('reason') or ''} | {it.get('calls') or ''} | {it.get('chars') or ''} | {it.get('seconds') or ''} | "
                   f"{it.get('review') or ''} |")
    return "\n".join(out) + "\n"


def _cli(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.disable(logging.INFO)
    ap = argparse.ArgumentParser(prog="dart_mcp.batch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("bgn")
    p.add_argument("end")
    p.add_argument("--grade", default="full")
    p.add_argument("--limit", type=int)
    p.add_argument("--state")
    p.add_argument("--kinds", help="쉼표 구분: merger,split,split_merger,share_exchange (지분증권 제외 등)")
    r = sub.add_parser("record")
    r.add_argument("--state", required=True)
    r.add_argument("rcept_no")
    r.add_argument("status", choices=["ok", "fail", "skip", "todo"])
    r.add_argument("--reason")
    r.add_argument("--review")
    for k in ("calls", "chars", "seconds"):
        r.add_argument(f"--{k}", type=int)
    q = sub.add_parser("report")
    q.add_argument("--state", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        st = plan(a.bgn, a.end, a.grade or None, a.limit, kinds=a.kinds.split(",") if a.kinds else None)
        path = Path(a.state or CASE_DIR / f"_batch_{dt.date.today():%Y-%m-%d}.json")
        path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        path.with_suffix(".md").write_text(render(st), encoding="utf-8")
        todo = [i for i in st["items"] if i["status"] == "todo"]
        print(json.dumps({"state": str(path), "items": len(st["items"]), "todo": [i["body_rcept_no"] for i in todo],
                          "status": {s: sum(1 for i in st["items"] if i["status"] == s) for s in
                                     {i["status"] for i in st["items"]}}}, ensure_ascii=False, indent=1))
        return 0
    path = Path(a.state)
    st = json.loads(path.read_text(encoding="utf-8"))
    if a.cmd == "record":
        it = record(st, a.rcept_no, a.status, a.reason, calls=a.calls, chars=a.chars, seconds=a.seconds,
                    **({"review": a.review} if a.review else {}))
        if a.status == "ok":
            it["industry"] = ensure_company(it)
        path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(it, ensure_ascii=False))
    path.with_suffix(".md").write_text(render(st), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
