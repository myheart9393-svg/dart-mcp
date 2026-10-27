"""/dart-valuation 사례 JSON을 만드는 도우미. 숫자의 cite를 원문에서 직접 찾아 채운다(손으로 offset을 적지 않는다).

    from dart_mcp import casebuild as B
    from dart_mcp.casebuild import N, R, C, val
    B.RCEPT = "20261019000334"
    wacc = N("8.43%", "5", 220698, "%")      # 섹션 "5"의 offset 220698 이후 4,000자 안에서 "8.43%"를 찾아 그 위치를 cite로

N(text, sid, anchor)는 anchor부터 앞으로 먼저 찾는다(바로 앞 표의 같은 숫자를 잡지 않게: 우성 2026-10 리뷰 d-1).
못 찾으면 예외 — 원문에 없는 숫자에는 cite를 만들 수 없다.

툴 호출 기록(호출 수·읽은 글자 수 집계, citations 생성용)은 CLI로:

    uv run python -m dart_mcp.casebuild call  --log <log.jsonl> --tag <rcept> <tool> '<json kwargs>'
    uv run python -m dart_mcp.casebuild grep  --log <log.jsonl> --tag <rcept> <rcept_no> <section_id> <정규식> [ctx] [max]
    uv run python -m dart_mcp.casebuild usage --log <log.jsonl> [--tag <rcept>]

call은 dart_mcp.server의 툴 함수를 그대로 부른다(MCP 서버가 재연결 전이라 새 툴이 안 보일 때 — 보고서에 "MCP 대신 직접 호출").
grep은 섹션 텍스트를 정규식으로 찾아 **그 섹션 기준 offset**을 준다(search_in_disclosure는 .hN 하위 구간 offset을 줄 수 있다).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .cache import DisclosureCache

_cache = DisclosureCache()
_texts: dict[tuple[str, str, str], str] = {}
RCEPT: str | None = None
LOG_ENV = "DART_CASE_LOG"


def sec_text(rcept: str, sid: str, file_id: str = "main") -> str:
    key = (rcept, file_id, sid)
    if key not in _texts:
        disc = _cache.get(rcept, None if _cache.has(rcept) else _client())
        f = disc.get_file(file_id)
        sec = f.get_section(sid) if f else None
        if sec is None:
            raise KeyError(f"{rcept} {file_id} section {sid!r} 없음")
        _texts[key] = sec.text
    return _texts[key]


def _client():
    from .client import DartClient

    return DartClient()


def locate(text: str, sid: str, anchor: int, rcept: str | None = None, window: int = 4000) -> int:
    rcept = rcept or RCEPT
    if rcept is None:
        raise ValueError("casebuild.RCEPT를 먼저 정하세요")
    t = sec_text(rcept, sid)
    pos = t.find(text, anchor, anchor + window)
    if pos < 0:
        pos = t.find(text, max(0, anchor - 200), anchor + window)
    if pos < 0:
        raise ValueError(f"{text!r} not found in {rcept} §{sid} near {anchor}")
    return pos


def _cite(sid: str, pos: int, rcept: str | None) -> dict:
    cite = {"section_id": sid, "offset": pos, "file_id": "main"}
    if rcept and rcept != RCEPT:
        cite["rcept_no"] = rcept
    return cite


def N(text: str, sid: str, anchor: int, unit: str | None = None, value: float | int | None = None,
      rcept: str | None = None) -> dict:
    """원문 표기 text → {"value","unit","text","cite"}. value를 생략하면 text의 첫 숫자(쉼표 제거)."""
    pos = locate(text, sid, anchor, rcept)
    if value is None:
        m = re.search(r"-?\d[\d,]*\.?\d*", text)
        if not m:
            raise ValueError(f"{text!r}에 숫자가 없습니다. value를 주세요")
        raw = m.group(0).replace(",", "")
        value = float(raw) if "." in raw else int(raw)
    return {"value": value, "unit": unit, "text": text, "cite": _cite(sid, pos, rcept)}


def R(lo: dict | None, hi: dict | None) -> dict:
    return {"min": lo, "max": hi}


def C(sid: str, anchor_text: str, anchor: int, rcept: str | None = None) -> dict:
    """숫자 아닌 필드(external_valuation 등)의 cite."""
    return _cite(sid, locate(anchor_text, sid, anchor, rcept), rcept)


def company(corp_code: str, name: str, market: str | None) -> dict:
    """case["company"]. induty_code는 기업개황(30일 캐시)에서 채운다 — 못 찾으면 null(사유는 batch record·industry fill이 notes에)."""
    from .industry import lookup

    return {"corp_code": corp_code, "name": name, "market": market, "induty_code": lookup(corp_code)[0]}


def val(subject: str, target: str, role: str, method: str, *, purpose: str, weights: dict | None = None,
        asset_value: dict | None = None, income_value: dict | None = None, dcf: dict | None = None,
        relative: dict | None = None, result_value: dict | None = None, result_unit: str | None = "원",
        result_range: dict | None = None, note: str | None = None) -> dict:
    """valuations[] 원소. purpose는 필수(합병가액·분할·교환비율·양수도가액·공모가·공정가치평가·손상검사·기타)."""
    out: dict[str, Any] = {"subject": subject, "target": target, "role": role, "purpose": purpose, "method": method,
                           "weights": weights, "asset_value": asset_value, "dcf": dcf, "relative": relative,
                           "result": {"value": result_value, "unit": result_unit, "range": result_range}}
    if income_value is not None:
        out["income_value"] = income_value
    if note:
        out["note"] = note
    return out


# --------------------------------------------------------------------------- 호출 기록
def _log_path(log: str | None) -> Path:
    p = log or os.environ.get(LOG_ENV)
    if not p:
        raise ValueError(f"--log 또는 환경변수 {LOG_ENV}가 필요합니다")
    return Path(p)


def _append(log: str | None, rec: dict) -> None:
    path = _log_path(log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_chars(fn: str, res: Any) -> int:
    if not isinstance(res, dict):
        return 0
    if fn == "get_disclosure_section":
        return int(res.get("returned_chars") or 0)
    if fn == "search_in_disclosure":
        return sum(len(m["context"]) for m in res.get("matches", []))
    if fn == "find_tables":
        return sum(len(t["text"]) for t in res.get("tables", []))
    return 0


def citations_from_log(tag: str, titles: dict[str, str], rcept: str, log: str | None = None) -> list[dict]:
    """기록에서 tag의 원문 읽기(섹션·표·검색)를 섹션별로 합친다 → citations[]."""
    agg: dict[str, dict] = {}
    for line in open(_log_path(log), encoding="utf-8"):
        r = json.loads(line)
        if r["tag"] != tag or not r["read"]:
            continue
        k = r["kwargs"]
        if (k.get("rcept_no") or rcept) != rcept:
            continue
        sid = k.get("section_id")
        if sid is None:
            continue
        how = {"find_tables": "find_tables", "get_disclosure_section": "section"}.get(r["fn"], "search")
        a = agg.setdefault(sid, {"chars": 0, "how": set()})
        a["chars"] += r["read"]
        a["how"].add(how)
    return [{"rcept_no": rcept, "file_id": "main", "section_id": sid, "title": titles.get(sid),
             "chars_read": a["chars"], "how": "/".join(sorted(a["how"]))} for sid, a in sorted(agg.items())]


def usage(log: str | None = None, tag: str | None = None) -> dict:
    """기록 집계: {tag: {calls: {fn: n}, chars}}."""
    out: dict[str, dict] = {}
    for line in open(_log_path(log), encoding="utf-8"):
        r = json.loads(line)
        if tag and r["tag"] != tag:
            continue
        u = out.setdefault(r["tag"], {"calls": {}, "chars": 0})
        u["calls"][r["fn"]] = u["calls"].get(r["fn"], 0) + 1
        u["chars"] += r["read"]
    return out


def _cli(argv: list[str]) -> int:
    import argparse

    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="dart_mcp.casebuild")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("call", "grep", "usage"):
        p = sub.add_parser(name)
        p.add_argument("--log")
        p.add_argument("--tag")
    sub.choices["call"].add_argument("tool")
    sub.choices["call"].add_argument("kwargs", nargs="?", default="{}")
    g = sub.choices["grep"]
    for a in ("rcept_no", "section_id", "pattern"):
        g.add_argument(a)
    g.add_argument("ctx", nargs="?", type=int, default=150)
    g.add_argument("max", nargs="?", type=int, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "usage":
        print(json.dumps(usage(a.log, a.tag), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "call":
        import logging

        logging.disable(logging.INFO)
        from . import server

        kwargs = json.loads(a.kwargs)
        res = getattr(server, a.tool)(**kwargs)
        _append(a.log, {"tag": a.tag or kwargs.get("rcept_no") or "", "fn": a.tool, "kwargs": kwargs,
                        "read": _read_chars(a.tool, res)})
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if not (isinstance(res, dict) and "error" in res) else 1
    text = sec_text(a.rcept_no, a.section_id)
    hits = list(re.finditer(a.pattern, text))
    read = 0
    print(f"{len(hits)} hits")
    for m in hits[: a.max]:
        s = text[max(0, m.start() - a.ctx): m.end() + a.ctx].replace("\n", " ")
        read += len(s)
        print(f"--- off {m.start()}: {s}")
    _append(a.log, {"tag": a.tag or a.rcept_no, "fn": "search_in_disclosure(grep)",
                    "kwargs": {"rcept_no": a.rcept_no, "section_id": a.section_id, "q": a.pattern}, "read": read})
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
