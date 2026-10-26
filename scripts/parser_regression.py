"""파서 회귀 검사: data/ 아래 모든 공시 XML을 현재 document.py로 다시 변환해 섹션 목록을 baseline과 비교한다.

    uv run python scripts/parser_regression.py            # 비교(baseline 없는 공시는 새로 저장)
    uv run python scripts/parser_regression.py --update   # 현재 결과로 baseline 갱신
    uv run python scripts/parser_regression.py --jobs 4

baseline: data/_baseline/<rcept_no>.json = {file_id: [[id, title, char_count], ...]}.
document.py를 고치면 커밋 전에 돌려 변경 목록을 커밋 메시지에 적는다(CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from dart_mcp.cache import default_data_dir, file_id_of
from dart_mcp.document import build_outline

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)


def snapshot(rcept_dir: Path) -> dict[str, list[list]]:
    rcept_no = rcept_dir.name
    out: dict[str, list[list]] = {}
    for xml in sorted(rcept_dir.glob("*.xml")):
        file_id = file_id_of(xml.name, rcept_no)
        # cache.store와 같은 인자로 만든다(main=False인 첨부는 휴리스틱 소제목 .hN을 만들지 않는다)
        sections = build_outline(xml.read_bytes(), main=file_id == "main")
        out[file_id] = [[s.id, s.title, s.char_count] for s in sections]
    return out


def diff(old: dict[str, list[list]], new: dict[str, list[list]]) -> list[str]:
    lines: list[str] = []
    for fid in sorted(set(old) | set(new)):
        if fid not in new:
            lines.append(f"  [{fid}] 파일 사라짐")
            continue
        if fid not in old:
            lines.append(f"  [{fid}] 새 파일 ({len(new[fid])}개 섹션)")
            continue
        o = {sid: (t, c) for sid, t, c in old[fid]}
        n = {sid: (t, c) for sid, t, c in new[fid]}
        for sid in [s for s, *_ in new[fid] if s not in o]:
            lines.append(f"  [{fid}] + {sid} {n[sid][0]!r} {n[sid][1]:,}자")
        for sid in [s for s, *_ in old[fid] if s not in n]:
            lines.append(f"  [{fid}] - {sid} {o[sid][0]!r} {o[sid][1]:,}자")
        for sid, _, _ in new[fid]:
            if sid in o and o[sid] != n[sid]:
                (ot, oc), (nt, nc) = o[sid], n[sid]
                what = []
                if ot != nt:
                    what.append(f"제목 {ot!r} → {nt!r}")
                if oc != nc:
                    what.append(f"{oc:,} → {nc:,}자 ({nc - oc:+,})")
                lines.append(f"  [{fid}] ~ {sid} {nt!r}: " + ", ".join(what))
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update", action="store_true", help="현재 변환 결과로 baseline을 덮어쓴다")
    ap.add_argument("--jobs", type=int, default=1, help="병렬 프로세스 수")
    ap.add_argument("--data-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    data = args.data_dir or default_data_dir()
    base_dir = data / "_baseline"
    base_dir.mkdir(parents=True, exist_ok=True)
    dirs = sorted(d for d in data.iterdir() if d.is_dir() and re.fullmatch(r"\d{14}", d.name) and any(d.glob("*.xml")))

    with ProcessPoolExecutor(max_workers=args.jobs) if args.jobs > 1 else _Serial() as ex:
        snaps = dict(zip((d.name for d in dirs), ex.map(snapshot, dirs)))

    changed = created = 0
    for rcept_no, snap in snaps.items():
        path = base_dir / f"{rcept_no}.json"
        if not path.exists() or args.update:
            if not path.exists():
                created += 1
            path.write_text(json.dumps(snap, ensure_ascii=False, indent=0), encoding="utf-8")
            continue
        lines = diff(json.loads(path.read_text(encoding="utf-8")), snap)
        if lines:
            changed += 1
            print(f"{rcept_no}: {len(lines)}건 변경")
            print("\n".join(lines))
    mode = "baseline 갱신" if args.update else "비교"
    print(f"\n{mode}: 공시 {len(snaps)}건, 변경 {changed}건, 새 baseline {created}건 ({base_dir})")
    return 1 if changed and not args.update else 0


class _Serial:
    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    @staticmethod
    def map(fn, items):
        return map(fn, items)


if __name__ == "__main__":
    sys.exit(main())
