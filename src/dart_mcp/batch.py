"""/dart-valuation-batch의 결정적인 부분: 대상 목록(큐) 만들기, 진행 상태 저장, _batch_<날짜>.md 렌더.

    uv run python -m dart_mcp.batch plan   <bgn> <end> [--grade full] [--limit N] [--state reports/valuations/_batch_<날짜>.json]
    uv run python -m dart_mcp.batch record --state <state.json> <rcept_no> <ok|fail|skip> [--reason ...] [--calls N] [--chars N] [--seconds N]
    uv run python -m dart_mcp.batch report --state <state.json>      # → 같은 이름 .md
    uv run python -m dart_mcp.batch sample --state <state.json> [--only r1,r2]   # 리뷰 표본 20% (seed = rcept_no 목록 해시)

plan 규칙:
- search_valuation_disclosures(bgn, end, listed_only=False, kinds=전부+유상증자)에서 grade가 맞는 거래.
- 증권신고서(지분증권)은 corp_cls만으로는 IPO/유상증자를 못 가린다(valuation.equity_kind 설명; 상장폐지 후 E가 된 회사의 유상증자도 있다)
  → 전부 본문을 받아 equity_kind로 확인.
  유상증자면 skip:rights_offering, 판단 불가면 skip:equity_unknown.
- SPAC(기업인수목적회사) IPO는 공모가가 고정(평가 없음)이라 skip:spac.
- reports/valuations/에 이미 있는 거래(rcept_no·original·supersedes 중 하나)는 skip:existing.
- 목록에 [첨부정정]만 있고 회사별 150일 재조회로도 원본·기재정정을 못 찾으면(body_available=false) skip:no_body.
- 추출 대상은 status="todo", 순서는 접수일 오래된 것부터. --limit은 todo 건수 상한(나머지는 status="queued").
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import logging
import sys
from pathlib import Path

from .valuation import DEAL_LABELS, SPAC_RE, equity_kind

CASE_DIR = Path("reports/valuations")
EQUITY_SCAN_CHARS = 300_000


CORRECTION_LOOKBACK_DAYS = 180


def _existing_deals(case_dir: Path) -> dict[tuple[str, str], list[str]]:
    """(corp_code, deal_type) → 기존 사례 rcept_no 목록. 원본이 plan 창 밖인 [기재정정]을 새 거래로 보지 않으려고(v1.6.4 SK이노베이션)."""
    out: dict[tuple[str, str], list[str]] = {}
    for p in case_dir.glob("*.json"):
        if p.name.startswith("_"):
            continue
        c = json.loads(p.read_text(encoding="utf-8"))
        cc = (c.get("company") or {}).get("corp_code")
        if cc:
            out.setdefault((cc, c["deal"]["type"]), []).append(c["rcept_no"])
    return out


def correction_of_existing(item: dict, deals: dict[tuple[str, str], list[str]]) -> str | None:
    """정정 꼬리표가 붙은 큐 항목이 같은 회사·같은 유형 기존 사례(접수 180일 안)의 정정으로 보이면 그 rcept_no."""
    if not re.match(r"\[(기재정정|첨부정정|첨부추가)\]", str(item.get("report_nm") or "")):  # 셀트릭스 v1.6.3은 [첨부정정]
        return None
    import datetime as _dt

    day = _dt.datetime.strptime(item["rcept_dt"], "%Y%m%d")
    lo = (day - _dt.timedelta(days=CORRECTION_LOOKBACK_DAYS)).strftime("%Y%m%d")
    hits = sorted(r for r in deals.get((item.get("corp_code") or "", item["deal_type"]), []) if lo <= r[:8] < item["rcept_dt"])
    return hits[-1] if hits else None


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
    deals = _existing_deals(case_dir)
    items = []
    for d in sorted(res["deals"], key=lambda x: (x["original_rcept_dt"] or x["rcept_dt"], x["rcept_no"])):
        if grade and d["source_grade"] != grade:
            continue
        it = {k: d[k] for k in ("rcept_no", "body_rcept_no", "original_rcept_no", "report_nm", "rcept_dt", "corp_code",
                                "corp_name", "corp_cls", "market", "filing_type", "deal_type", "deal_label",
                                "source_grade", "supersedes", "related_rcept_nos")}
        keys = {d["rcept_no"], d["body_rcept_no"], d.get("original_rcept_no") or "", *d["supersedes"]} - {""}
        it["status"], it["reason"] = "todo", None
        it["body_available"], it["hint"] = d.get("body_available"), d.get("hint")
        if keys & existing:
            it["status"], it["reason"] = "skip", "existing"
        elif (prev := correction_of_existing(it, deals)):
            # 원본이 창 밖이라 supersedes가 비었다 — 새 사례가 아니라 기존 사례를 정정본으로 갱신할 일
            it["status"], it["reason"] = "skip", "existing_correction"
            it["hint"] = f"기존 사례 {prev}의 [기재정정]으로 보인다 — 새로 추출하지 말고 기존 사례를 정정본으로 갱신(사례 JSON의 정정 관계는 notes)"
        elif d.get("body_available") is False:
            # 첨부정정 ZIP뿐이고 원본을 못 찾음: 실패가 아니라 읽을 본문이 없는 것(retro 2026-11-04 #8)
            it["status"], it["reason"] = "skip", "no_body"
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


def finalize_case_file(it: dict, case_dir: Path = CASE_DIR) -> list[dict] | None:
    """record ok 후처리: casedb.finalize(spac·status 초기값·relative kind·regime; induty는 ensure_company가 이미 함)."""
    from .casedb import finalize

    path = case_dir / f"{it['body_rcept_no']}.json"
    if not path.exists():
        return None
    case = json.loads(path.read_text(encoding="utf-8"))
    ch = finalize(case, network=False)
    if ch:
        path.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    return [{"field": c["field"], "new": c["new"]} for c in ch]


def write_report(md_path: Path, generated: str) -> None:
    """_batch_<날짜>.md 쓰기: 생성 내용 + 마커, 기존 파일의 마커 아래(손으로 붙인 추출 기록 등)는 보존(v1.6.4 — record·report가 지웠다).
    마커 없는 기존 파일은 새 생성에 없는 줄을 마커 아래로 옮긴다(잃지 않는다)."""
    from .valuation import MD_MARKER

    tail = ""
    if md_path.exists():
        old = md_path.read_text(encoding="utf-8")
        if MD_MARKER in old:
            tail = old.split(MD_MARKER, 1)[1].lstrip("\n")
        else:
            gen_lines = set(generated.splitlines())
            extra = [ln for ln in old.splitlines() if ln.strip() and ln not in gen_lines]
            if extra:
                first = next(i for i, ln in enumerate(old.splitlines()) if ln in extra)
                tail = "\n".join(old.splitlines()[first:]).rstrip("\n") + "\n"
    md_path.write_text(generated.rstrip("\n") + "\n" + MD_MARKER + "\n" + ("\n" + tail if tail else ""), encoding="utf-8")


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


def review_sample(state: dict, rate: float = 0.2, only: list[str] | None = None) -> dict:
    """리뷰 표본: ok 건(또는 only로 준 rcept_no) 중 ceil(rate × n)건. seed = 대상 body_rcept_no 정렬 목록의 sha256 앞 16자리.

    state 파일 크기로 seed를 정하면 기록(record)이 하나만 늘어도 표본이 바뀐다(v1.6.3). 같은 대상 목록이면 언제 다시 뽑아도 같다.
    """
    import hashlib
    import math
    import random

    ids = sorted({i["body_rcept_no"] for i in state["items"] if i["status"] == "ok"} if only is None else set(only))
    seed = hashlib.sha256(",".join(ids).encode()).hexdigest()[:16]
    k = math.ceil(rate * len(ids)) if ids else 0
    return {"n_ok": len(ids), "rate": rate, "seed": seed, "sample": sorted(random.Random(seed).sample(ids, k))}


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
    sm = sub.add_parser("sample", help="리뷰 표본(ok 건의 20%%, seed = rcept_no 목록 해시)")
    sm.add_argument("--state", required=True)
    sm.add_argument("--rate", type=float, default=0.2)
    sm.add_argument("--only", help="쉼표 구분 rcept_no — 이번에 추출한 건만 대상으로")
    a = ap.parse_args(argv)
    if a.cmd == "sample":
        st = json.loads(Path(a.state).read_text(encoding="utf-8"))
        print(json.dumps(review_sample(st, a.rate, a.only.split(",") if a.only else None), ensure_ascii=False))
        return 0
    if a.cmd == "plan":
        st = plan(a.bgn, a.end, a.grade or None, a.limit, kinds=a.kinds.split(",") if a.kinds else None)
        path = Path(a.state or CASE_DIR / f"_batch_{dt.date.today():%Y-%m-%d}.json")
        path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        write_report(path.with_suffix(".md"), render(st))
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
            it["finalize"] = finalize_case_file(it)
        path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(it, ensure_ascii=False))
    write_report(path.with_suffix(".md"), render(st))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
