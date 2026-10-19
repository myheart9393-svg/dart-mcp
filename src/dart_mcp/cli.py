"""검증용 CLI.

    python -m dart_mcp.cli fetch <rcept_no> --out ./data/<rcept_no>/
    python -m dart_mcp.cli search --corp-code 00126380 --bgn-de 20250101 --end-de 20251231 --pblntf-ty A
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import DartApiError, DartClient
from .document import decode_dart_xml, detect_declared_encoding, extract_from_zip, parse_dart_xml


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def cmd_fetch(args: argparse.Namespace) -> int:
    out_dir = Path(args.out) if args.out else Path("data") / args.rcept_no
    out_dir.mkdir(parents=True, exist_ok=True)

    with DartClient() as client:
        try:
            zip_bytes = client.get_document(args.rcept_no)
        except DartApiError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    zip_path = out_dir / f"{args.rcept_no}.zip"
    zip_path.write_bytes(zip_bytes)
    written: list[Path] = [zip_path]

    files = extract_from_zip(zip_bytes)
    print(f"ZIP 내 파일 {len(files)}개:")
    for name, data in files:
        print(f"  - {name}  ({_human(len(data))})")

    md_paths: list[Path] = []
    for name, data in files:
        raw_path = out_dir / Path(name).name
        raw_path.write_bytes(data)
        written.append(raw_path)

        if not name.lower().endswith((".xml", ".htm", ".html")):
            continue

        declared = detect_declared_encoding(data)
        _, used = decode_dart_xml(data)
        tags: set[str] = set()
        md = parse_dart_xml(data, seen_tags=tags)
        md_path = raw_path.with_suffix(".md")
        md_path.write_text(md, encoding="utf-8")
        written.append(md_path)
        md_paths.append(md_path)

        print(f"\n[{name}]")
        print(f"  XML 선언 encoding : {declared!r}  -> 실제 디코딩: {used}")
        print(f"  발견 태그 ({len(tags)}): {', '.join(sorted(tags))}")

    print("\n저장된 파일:")
    for p in written:
        print(f"  {p}  ({_human(p.stat().st_size)})")

    for md_path in md_paths:
        print(f"\n===== {md_path.name} (앞 {args.head}줄) =====")
        with md_path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= args.head:
                    break
                print(line.rstrip("\n"))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    with DartClient() as client:
        data = client.search_disclosures(
            corp_code=args.corp_code,
            bgn_de=args.bgn_de,
            end_de=args.end_de,
            pblntf_ty=args.pblntf_ty,
            page_count=args.page_count,
        )
    print(f"total={data.get('total_count')} page={data.get('page_no')}/{data.get('total_page')}")
    for item in data.get("list", []):
        print(f"{item['rcept_no']}  {item['rcept_dt']}  {item['corp_name']:<12}  {item['report_nm']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dart_mcp.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="공시 원문 ZIP을 받아 XML/MD로 저장")
    f.add_argument("rcept_no")
    f.add_argument("--out", help="출력 폴더 (기본 ./data/<rcept_no>/)")
    f.add_argument("--head", type=int, default=40, help="stdout에 출력할 .md 앞부분 줄 수")
    f.set_defaults(func=cmd_fetch)

    s = sub.add_parser("search", help="공시 목록 검색 (list.json)")
    s.add_argument("--corp-code", dest="corp_code")
    s.add_argument("--bgn-de", dest="bgn_de", help="YYYYMMDD")
    s.add_argument("--end-de", dest="end_de", help="YYYYMMDD")
    s.add_argument("--pblntf-ty", dest="pblntf_ty", help="A=정기, B=주요사항, C=발행, D=지분, ...")
    s.add_argument("--page-count", dest="page_count", type=int, default=20)
    s.set_defaults(func=cmd_search)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
