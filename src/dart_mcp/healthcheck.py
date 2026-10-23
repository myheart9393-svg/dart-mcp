"""파서·재무 매칭 건전성 일괄 검사 (LLM 호출 없음).

    uv run python -m dart_mcp.healthcheck --corp-codes 00126380,00164779
    uv run python -m dart_mcp.healthcheck --corp-codes codes.txt        # 한 줄에 하나(# 뒤는 주석)
    uv run python -m dart_mcp.healthcheck --sample 30 --seed 1          # 상장사 무작위 N개

회사마다 get_latest_reports → 최신 사업보고서 본문(body_rcept_no) outline(depth=2) → get_key_financials(연결, 013이면 별도)를
server 함수로 직접 호출한다(캐시 사용). 감사보고서 첨부는 attachment_rcept_no의 ZIP에서 본다.
검사 a–g는 각각 PASS/WARN/FAIL/N/A. 결과는 reports/healthcheck_<날짜>.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import server
from .cache import _PROJECT_ROOT, default_data_dir
from .financials import load_company

log = logging.getLogger("dart_mcp.healthcheck")

PASS, WARN, FAIL, NA = "PASS", "WARN", "FAIL", "N/A"
CHECKS = {
    "a": "뒷부분 누락(원문 SECTION-1·TITLE 수 vs 파싱 수)",
    "b": "U+FFFD(깨진 글자)",
    "c": "level 1 섹션 수(5–30)",
    "d": "재무 API missing",
    "e": "reprt_code null 분기보고서",
    "f": "API 숫자 ↔ 원문 요약재무정보",
    "g": "감사보고서 첨부",
}
_SEVERITY = {PASS: 0, NA: 0, WARN: 1, FAIL: 2}
F_MIN_WON = 1_000_000_000  # 1,000백만원 미만 값은 표기 단위에 따라 자릿수가 너무 짧아 비교하지 않는다
_UNITS = ((1, "원"), (1_000, "천원"), (1_000_000, "백만원"))
_SUMMARY_NA_RE = re.compile(r"해당\s*사항\s*(이\s*)?없|생략")
CORP_CLS = {"Y": "유가", "K": "코스닥", "N": "코넥스", "E": "기타"}


@dataclass
class Check:
    status: str
    detail: str = ""


@dataclass
class CompanyResult:
    corp_code: str
    corp_name: str = ""
    market: str = ""
    induty_code: str = ""
    rcept_no: str | None = None  # 본문(body_rcept_no)
    attachment_rcept_no: str | None = None
    bsns_year: str | None = None
    fs_div: str | None = None
    checks: dict[str, Check] = field(default_factory=dict)
    error: str | None = None

    @property
    def overall(self) -> str:
        if self.error:
            return "ERROR"
        worst = max((_SEVERITY[c.status] for c in self.checks.values()), default=0)
        return {0: PASS, 1: WARN, 2: FAIL}[worst]


# --------------------------------------------------------------------------- 순수 함수(단위테스트 대상)
def amount_candidates(won: int) -> list[str]:
    """원 단위 금액 → 원문 표기 후보: 원 그대로, 천원·백만원 반올림."""
    out: list[str] = []
    for div, _ in _UNITS:
        v = f"{round(won / div):,}"
        if v not in out:
            out.append(v)
    return out


def _granularity(won: int) -> int:
    """API 값 자체가 반올림돼 있으면(예: 57,617,000,000) 그 단위. 비교 허용오차에 쓴다."""
    for div in (1_000_000, 1_000):
        if won % div == 0:
            return div
    return 1


def rounded_match(text: str, won: int) -> str | None:
    """text 안 숫자 x와 단위 m 중 |x·m − won| < max(m, API 반올림 단위) 인 것의 표기 (한 단위 안: 반올림·절사·올림 모두).

    API 값이 이미 백만원 단위로 반올림돼 있고 원문은 원 단위인 경우(뉴엔에이아이 2025 실측)와, 원문이 백만원 미만을
    절사·올림한 경우(한화손해보험 20,492,834.69 → 20,492,834, 오리온홀딩스 6,183,410.43 → 6,183,411 실측)를 잡는다.
    """
    tol = _granularity(won)
    for m in re.finditer(r"(?<![\d,.])\d{1,3}(?:,\d{3})+(?![\d]|,\d|\.\d)", text):
        x = int(m.group(0).replace(",", ""))
        for div, unit in _UNITS:
            if abs(x * div - abs(won)) < max(div, tol):
                return f"{m.group(0)}({unit})"
    return None


def merged_digits(text: str, won: int) -> str | None:
    """후보 표기가 더 긴 숫자열 속에만 있으면(원문 셀이 "402,39675,912…"처럼 붙은 경우) 그 숫자열 앞부분."""
    for cand in amount_candidates(won):
        for m in re.finditer(r"[\d,()\-△]{12,}", text):
            if cand in m.group(0) and not bounded_in(m.group(0), cand):
                return m.group(0)[:30]
    return None


def bounded_in(text: str, number: str) -> bool:
    """number가 더 긴 숫자의 일부가 아닌 채로 text에 있는가 ("1,234"가 "51,234"에 걸리지 않게)."""
    return re.search(r"(?<![\d,.])" + re.escape(number) + r"(?![\d]|,\d|\.\d)", text) is not None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


# --------------------------------------------------------------------------- 검사
def _check_numbers(rcept_no: str, main_sections: list, accounts: dict, year: str) -> Check:
    summary = next((s for s in main_sections if s.level == 2 and "요약재무정보" in _norm(s.title)), None)
    if summary is None:
        return Check(NA, "요약재무정보 섹션 없음")
    body = summary.text.split("\n", 1)[-1]
    if len(body.strip()) < 300 and _SUMMARY_NA_RE.search(body):
        return Check(NA, f"{summary.id} 요약재무정보 기재 생략/해당사항 없음")
    notes, bad, merged = [], [], []
    for key, label in (("revenue", "매출액"), ("total_assets", "자산총계")):
        won = (accounts.get(key) or {}).get("values", {}).get(year)
        if won is None or abs(won) < F_MIN_WON:
            notes.append(f"{label}: {'API 값 없음' if won is None else f'{won:,}원 < 1,000백만원'}(N/A)")
            continue
        hit = None
        for cand in amount_candidates(won):
            res = server.search_in_disclosure(rcept_no, cand, max_results=100)
            ids = {m["section_id"] for m in res.get("matches", [])}
            if any(i == summary.id or i.startswith(summary.id + ".") for i in ids) and bounded_in(summary.text, cand):
                hit = f"'{cand}'"
                break
        if hit is None and (rm := rounded_match(summary.text, won)):
            hit = f"'{rm}' 반올림 일치"
        if hit is None and (mg := merged_digits(summary.text, won)):
            merged.append(f"{label} {won:,}원: 원문 셀에 숫자가 구분자 없이 붙어 있음 '{mg}'(원문 XML 자체 결함)")
        elif hit is None:
            bad.append(f"{label} {won:,}원: {summary.id} 요약재무정보에 원·천원·백만원 표기 모두 없음")
        else:
            notes.append(f"{label} {hit} 확인")
    if bad:
        return Check(FAIL, "; ".join(bad + merged + notes))
    if merged:
        return Check(WARN, "; ".join(merged + notes))
    if not any("확인" in n for n in notes):
        return Check(NA, "; ".join(notes))
    return Check(PASS, "; ".join(notes))


def _has_audit_report(disc) -> tuple[bool, list[str]]:
    names = []
    for f in disc.files:
        if f.file_id == "main":
            continue
        head = "".join(s.text for s in f.sections if s.level <= 1)[:3000]
        names.append(f.file_id)
        if "감사보고서" in head:
            return True, names
    return False, names


def check_company(corp_code: str) -> CompanyResult:
    r = CompanyResult(corp_code)
    company = load_company(server._get_client, corp_code) or {}
    r.corp_name = company.get("corp_name", "")
    r.market = CORP_CLS.get(company.get("corp_cls", ""), company.get("corp_cls", ""))
    r.induty_code = company.get("induty_code", "")

    latest = server.get_latest_reports(corp_code)
    if "error" in latest:
        r.error = latest["error"]
        return r
    annual = latest["latest_annual"]
    r.rcept_no, r.bsns_year = annual["body_rcept_no"], annual["bsns_year"]
    r.attachment_rcept_no = annual["attachment_rcept_no"]

    outline = server.get_disclosure_outline(r.rcept_no, depth=2)
    if "error" in outline:
        r.error = f"{outline['error']} {outline.get('hint', '')}".strip()
        return r
    disc = server._load(r.rcept_no)
    main = disc.get_file("main")

    # a. 뒷부분 누락: 원문 태그 수 vs 파싱 수 (document.truncation_warnings)
    r.checks["a"] = Check(FAIL, "; ".join(main.parse_warnings)) if main.parse_warnings else Check(PASS)

    # b. U+FFFD (파일별, 섹션 중복을 피해 level≤1만 센다)
    fffd = {f.file_id: sum(s.text.count("�") for s in f.sections if s.level <= 1) for f in disc.files}
    fffd = {k: v for k, v in fffd.items() if v}
    if fffd:
        sample = next((s for s in main.sections if s.level == 1 and "�" in s.text), None)
        ctx = ""
        if sample is not None:
            i = sample.text.index("�")
            ctx = f" 예: {sample.id} …{sample.text[max(0, i - 20):i + 20]!r}…"
        r.checks["b"] = Check(FAIL, f"{fffd}{ctx}")
    else:
        r.checks["b"] = Check(PASS)

    # c. level 1 섹션 수
    n1 = sum(1 for s in outline["files"][0]["sections"] if s["level"] == 1)
    r.checks["c"] = Check(PASS if 5 <= n1 <= 30 else WARN, f"{n1}개")

    # d. 재무 API missing (연결 → 013이면 별도)
    fin = server.get_key_financials(corp_code, r.bsns_year, fs_div="CFS")
    r.fs_div = "CFS"
    if "error" not in fin and fin.get("rcept_no") is None:
        fin = server.get_key_financials(corp_code, r.bsns_year, fs_div="OFS")
        r.fs_div = "OFS"
    if "error" in fin:
        r.checks["d"] = Check(FAIL, fin["error"])
    elif fin.get("rcept_no") is None:
        r.checks["d"] = Check(WARN, "연결·별도 모두 013(데이터 없음)")
    else:
        zero = f" assumed_zero={fin['assumed_zero']}" if fin.get("assumed_zero") else ""
        sector = (fin.get("sector") or {}).get("sector")
        extra = f" (금융업, financial_missing={fin.get('financial_missing')})" if fin.get("warning") else ""
        diff = f" API rcept_no={fin['rcept_no']}≠원문" if fin["rcept_no"] != r.rcept_no else ""
        if fin.get("missing"):
            r.checks["d"] = Check(WARN, f"{r.fs_div} missing={fin['missing']}{zero}{extra}{diff}")
        else:
            r.checks["d"] = Check(PASS, f"{r.fs_div} sector={sector}{zero}{extra}{diff}".strip())

    # e. reprt_code null 분기·반기
    nulls = [x["report_nm"] for x in latest.get("interim_after_annual", []) if x.get("reprt_code") is None]
    r.checks["e"] = Check(WARN, ", ".join(nulls)) if nulls else Check(PASS)

    # f. 매출액·자산총계 원문 존재
    if fin.get("accounts"):
        r.checks["f"] = _check_numbers(r.rcept_no, main.sections, fin["accounts"], r.bsns_year)
    else:
        r.checks["f"] = Check(NA, "재무 API 값 없음")

    # g. 감사보고서 첨부 (attachment_rcept_no의 ZIP)
    # DART가 첨부정정 ZIP을 014(파일 없음)로 거부하는 경우가 있어(디엘이앤씨·메가스터디교육 2025 실측) 같은 그룹의 다른 접수본으로 대체한다
    candidates = list(dict.fromkeys([r.attachment_rcept_no, r.rcept_no, annual["original_rcept_no"], *annual["supersedes"]]))
    failed: list[str] = []
    found, tried = None, []
    for rc in candidates:
        try:
            adisc = disc if rc == r.rcept_no else server._load(rc)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{rc}: {exc}")
            continue
        ok, attach = _has_audit_report(adisc)
        tried.append(f"{rc} 첨부 {attach or '없음'}")
        if ok:
            found = rc
            break
    if found == r.attachment_rcept_no and not failed:
        r.checks["g"] = Check(PASS, "" if found == r.rcept_no else found)
    elif found:
        r.checks["g"] = Check(WARN, f"attachment_rcept_no 다운로드 실패({'; '.join(failed)}) → {found}의 감사보고서 사용")
    else:
        r.checks["g"] = Check(WARN, f"감사보고서 없음: {'; '.join(tried + failed)}")
    return r


# --------------------------------------------------------------------------- 입력·출력
def parse_corp_codes(arg: str) -> list[str]:
    p = Path(arg)
    raw = p.read_text(encoding="utf-8") if p.exists() else arg.replace(",", "\n")
    codes = [ln.split("#")[0].strip() for ln in raw.splitlines()]
    return [c for c in codes if c]


def sample_listed(n: int, seed: int | None) -> list[str]:
    payload = json.loads((default_data_dir() / "corp_codes.json").read_text(encoding="utf-8"))
    listed = sorted(e["corp_code"] for e in payload["list"] if (e.get("stock_code") or "").strip())
    return random.Random(seed).sample(listed, min(n, len(listed)))


def render_report(results: list[CompanyResult], args_desc: str) -> str:
    today = dt.date.today().isoformat()
    lines = [f"# 파서·재무 매칭 healthcheck ({today})", "", f"- 대상: {args_desc} — {len(results)}개사",
             "- 방식: server 함수 직접 호출(LLM 없음), 캐시 사용", ""]
    lines += ["| 검사 | 내용 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in CHECKS.items()] + [""]
    counts = {s: sum(1 for r in results if r.overall == s) for s in (PASS, WARN, FAIL, "ERROR")}
    lines += [f"종합: PASS {counts[PASS]} · WARN {counts[WARN]} · FAIL {counts[FAIL]} · ERROR {counts['ERROR']}", ""]
    head = "| 회사 | 시장 | 업종 | 본문 rcept_no | FY | fs | " + " | ".join(CHECKS) + " | 종합 |"
    lines += [head, "|" + "---|" * (7 + len(CHECKS))]
    for r in results:
        cells = [r.checks[k].status if k in r.checks else "" for k in CHECKS]
        lines.append(f"| {r.corp_name or r.corp_code} | {r.market} | {r.induty_code} | {r.rcept_no or ''} | "
                     f"{r.bsns_year or ''} | {r.fs_div or ''} | " + " | ".join(cells) + f" | {r.overall} |")
    lines += ["", "## 이상 항목 상세", ""]
    any_issue = False
    for r in results:
        issues = [(k, c) for k, c in r.checks.items() if c.status in (WARN, FAIL)]
        if not issues and not r.error:
            continue
        any_issue = True
        att = f", 첨부 {r.attachment_rcept_no}" if r.attachment_rcept_no and r.attachment_rcept_no != r.rcept_no else ""
        lines.append(f"### {r.corp_name or r.corp_code} ({r.corp_code}, 본문 {r.rcept_no or '-'}{att})")
        if r.error:
            lines.append(f"- ERROR: {r.error}")
        for k, c in issues:
            lines.append(f"- **{k} {c.status}** {CHECKS[k]}: {c.detail}")
        lines.append("")
    if not any_issue:
        lines.append("없음")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dart_mcp.healthcheck", description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--corp-codes", help="corp_code 쉼표 목록 또는 파일 경로")
    src.add_argument("--sample", type=int, help="corp_codes.json 상장사에서 무작위 N개")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", help="보고서 경로 (기본 reports/healthcheck_<날짜>.md)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.getLogger().setLevel(logging.WARNING)  # server가 INFO로 잡아 둔 캐시 로그는 숨기고 트리 붕괴 경고 등만 남긴다

    if args.sample:
        codes, desc = sample_listed(args.sample, args.seed), f"상장사 무작위 {args.sample}개(seed={args.seed})"
    else:
        codes, desc = parse_corp_codes(args.corp_codes), f"--corp-codes {args.corp_codes}"

    results: list[CompanyResult] = []
    for i, code in enumerate(codes, 1):
        print(f"[{i}/{len(codes)}] {code} ...", file=sys.stderr, flush=True)
        try:
            r = check_company(code)
        except Exception as exc:  # noqa: BLE001 — 한 회사 실패가 전체를 멈추지 않게
            log.exception("healthcheck %s failed", code)
            r = CompanyResult(code, error=f"{type(exc).__name__}: {exc}")
        print(f"    {r.corp_name} → {r.overall} " + " ".join(f"{k}={c.status}" for k, c in r.checks.items()),
              file=sys.stderr, flush=True)
        results.append(r)

    report = render_report(results, desc)
    out = Path(args.out) if args.out else _PROJECT_ROOT / "reports" / f"healthcheck_{dt.date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"저장: {out}", file=sys.stderr)
    return 1 if any(r.overall in (FAIL, "ERROR") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
