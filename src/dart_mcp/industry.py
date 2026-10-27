"""업종(KSIC) 코드: 사례 JSON의 company.induty_code 채우기와 중분류 라벨.

    uv run python -m dart_mcp.industry fill <case.json|dir> [--force]   # 비어 있는 induty_code를 기업개황(30일 캐시)으로 채운다
    uv run python -m dart_mcp.industry dist <dir>                       # 중분류별 사례 수

induty_code는 기업개황(company.json) 조회값이라 원문 cite가 없다(스키마도 cite를 요구하지 않는 조회용 필드).
조회 실패·상장폐지 등으로 못 채우면 null로 두고 notes에 사유를 남긴다.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from functools import lru_cache
from pathlib import Path

KSIC_PATH = Path(__file__).with_name("ksic.json")
NOTE_PREFIX = "induty_code:"


@lru_cache(maxsize=1)
def _ksic() -> dict:
    return json.loads(KSIC_PATH.read_text(encoding="utf-8"))


def division(code: str | None) -> str | None:
    """KSIC 코드 → 중분류(앞 2자리). 2자리 미만·숫자 아님이면 None."""
    c = (code or "").strip()
    return c[:2] if len(c) >= 2 and c[:2].isdigit() else None


def label(code: str | None) -> str | None:
    """"26 전자부품·컴퓨터·영상·음향·통신장비". 매핑에 없는 중분류는 코드만("99"), 코드가 없으면 None."""
    d = division(code)
    if d is None:
        return None
    name = _ksic()["divisions"].get(d)
    return f"{d} {name}" if name else d


def section(code: str | None) -> str | None:
    """대분류 "C 제조업"."""
    d = division(code)
    if d is None:
        return None
    for letter, s in _ksic()["sections"].items():
        lo, hi = s["divisions"]
        if lo <= d <= hi:
            return f"{letter} {s['name']}"
    return None


# 대분류 묶음 별칭(--industry에 코드 접두 대신 쓸 수 있다). 값은 ksic.json sections의 문자
SECTION_ALIASES = {
    "농림어업": "A", "광업": "B", "제조업": "C", "제조": "C", "전기가스": "D", "수도폐기물": "E", "건설": "F", "건설업": "F",
    "도소매": "G", "도매소매": "G", "운수": "H", "운수창고": "H", "숙박음식": "I", "정보통신": "J", "정보통신업": "J",
    "금융보험": "K", "금융·보험": "K", "금융": "K", "부동산": "L", "전문과학기술": "M", "사업지원": "N",
    "교육": "P", "보건복지": "Q", "예술스포츠": "R", "기타서비스": "S",
}


def section_letter(code: str | None) -> str | None:
    s = section(code)
    return s.split(" ", 1)[0] if s else None


def matches(code: str | None, token: str) -> bool:
    """--industry 토큰 하나와 induty_code 비교: 숫자면 코드 접두("26", "582"), 대분류 문자("C") 또는 별칭("제조업", "정보통신")이면 대분류."""
    t = token.strip()
    if not t:
        return False
    if t.isdigit():
        return (code or "").startswith(t)
    letter = t.upper() if len(t) == 1 and t.isalpha() else SECTION_ALIASES.get(t) or SECTION_ALIASES.get(t.replace(" ", ""))
    if letter is None:
        raise ValueError(f"--industry {t!r}를 모름. KSIC 코드 접두(26), 대분류 문자(C) 또는 {sorted(SECTION_ALIASES)}")
    return section_letter(code) == letter


def lookup(corp_code: str, data_dir: Path | None = None) -> tuple[str | None, str | None]:
    """corp_code → (induty_code, 실패 사유). financials.load_company(30일 캐시)를 쓴다."""
    from .client import DartClient
    from .financials import load_company

    err: list[str] = []

    class _Recorder:  # load_company는 예외를 삼키므로 사유를 여기서 잡는다
        def get_company(self, code: str) -> dict:
            try:
                return DartClient().get_company(code)
            except Exception as exc:  # noqa: BLE001
                err.append(f"{type(exc).__name__}: {exc}")
                raise

    if not corp_code:
        return None, "corp_code 없음"
    company = load_company(_Recorder, corp_code, data_dir)
    if company is None:
        return None, f"기업개황 조회 실패({err[0] if err else '원인 미상'})"
    code = (company.get("induty_code") or "").strip()
    return (code, None) if code else (None, "기업개황에 induty_code 없음")


def fill_case(case: dict, *, force: bool = False, data_dir: Path | None = None) -> dict:
    """case.company.induty_code가 비었으면(force면 항상) 채운다 → {"rcept_no", "induty_code", "reason", "changed"}."""
    comp = case["company"]
    if comp.get("induty_code") and not force:
        return {"rcept_no": case["rcept_no"], "induty_code": comp["induty_code"], "reason": None, "changed": False}
    code, reason = lookup(comp.get("corp_code") or "", data_dir)
    changed = code != comp.get("induty_code")
    comp["induty_code"] = code
    notes = [n for n in case.get("notes") or [] if not str(n).startswith(NOTE_PREFIX)]
    if reason:
        notes.append(f"{NOTE_PREFIX} null — {reason} ({dt.date.today():%Y-%m-%d})")
        changed = True
    case["notes"] = notes
    return {"rcept_no": case["rcept_no"], "induty_code": code, "reason": reason, "changed": changed}


def fill_file(path: Path, *, force: bool = False) -> dict:
    case = json.loads(path.read_text(encoding="utf-8"))
    res = fill_case(case, force=force)
    if res["changed"]:
        path.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _case_files(target: Path) -> list[Path]:
    if target.is_dir():
        return [p for p in sorted(target.glob("*.json")) if not p.name.startswith("_")]
    return [target]


def _cli(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.disable(logging.WARNING)
    if len(argv) < 2 or argv[0] not in ("fill", "dist"):
        print(__doc__)
        return 2
    files = _case_files(Path(argv[1]))
    if argv[0] == "fill":
        results = [fill_file(p, force="--force" in argv) for p in files]
        print(json.dumps({"cases": len(results), "filled": sum(bool(r["induty_code"]) for r in results),
                          "changed": sum(r["changed"] for r in results),
                          "failed": [r for r in results if r["reason"]]}, ensure_ascii=False, indent=1))
        return 0
    counts: dict[str, int] = {}
    for p in files:
        code = json.loads(p.read_text(encoding="utf-8"))["company"].get("induty_code")
        k = label(code) or "(없음)"
        counts[k] = counts.get(k, 0) + 1
    print(json.dumps(dict(sorted(counts.items(), key=lambda x: (-x[1], x[0]))), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
