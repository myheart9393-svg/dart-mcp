"""/dart-export 본체: md 파싱 → 빌더 호출 → 숫자 검증 → 결과 요약.

사용법: python -m dart_mcp.export.cli <보고서.md> [--docx] [--pptx] [--html] [--out reports/export/] [--style default]
플래그가 없으면 셋 다. 검증 실패·빌드 실패는 종료코드 1. Node·패키지가 없으면 그 형식만 건너뛴다(사유 출력).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import html as html_builder
from .parse_md import parse_file
from .verify import Result, verify

HERE = Path(__file__).parent
FORMATS = ("docx", "pptx", "html")
NODE_PACKAGE = {"docx": "docx", "pptx": "pptxgenjs"}
INSTALL_HINT = "npm install --prefix src/dart_mcp/export"
MAX_PAGE_PASSES = 3


def load_style(name: str) -> dict:
    """--style: styles/ 아래 이름 또는 JSON 경로. 없는 키는 default.json 값을 쓴다."""
    default = json.loads((HERE / "styles" / "default.json").read_text(encoding="utf-8"))
    if name == "default":
        return default
    path = Path(name)
    if not path.exists():
        path = HERE / "styles" / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"스타일 파일을 찾을 수 없다: {name}")
    custom = json.loads(path.read_text(encoding="utf-8"))
    colors = {**default["colors"], **custom.get("colors", {})}
    return {**default, **custom, "colors": colors}


def node_problem(fmt: str) -> str | None:
    """빌더를 돌릴 수 없는 사유. 돌릴 수 있으면 None."""
    node = shutil.which("node")
    if not node:
        return f"node를 찾을 수 없다 (Node.js 설치 후 `{INSTALL_HINT}`)"
    package = NODE_PACKAGE[fmt]
    probe = subprocess.run([node, "-e", f"require.resolve('{package}')"], cwd=HERE, capture_output=True)
    if probe.returncode != 0:
        return f"Node 패키지 {package}가 없다 (`{INSTALL_HINT}`)"
    return None


def run_node(script: str, *args: Path) -> str | None:
    """빌더 실행. 실패하면 stderr를 돌려준다. 성공해도 경고는 출력한다."""
    proc = subprocess.run([shutil.which("node"), script, *map(str, args)], cwd=HERE,
                          capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return proc.stderr.strip() or f"{script} 종료코드 {proc.returncode}"
    if proc.stderr.strip():
        print(proc.stderr.strip())
    return None


def find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    default = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    return str(default) if default.exists() else None


def heading_pages(page_texts: list[str], heads: list[str]) -> dict[str, int]:
    """쪽별 글자에서 제목이 한 줄을 차지하는 첫 쪽을 찾는다(1쪽 = 표지는 제외)."""
    norm = lambda s: re.sub(r"\s+", "", s)
    pages: dict[str, int] = {}
    for number, text in enumerate(page_texts, start=1):
        if number == 1:
            continue
        lines = {norm(line) for line in text.split("\n")}
        for head in heads:
            if head not in pages and norm(head) in lines:
                pages[head] = number
    return pages


def measure_pages(docx_path: Path, heads: list[str], work: Path) -> dict[str, int] | None:
    """soffice로 PDF를 만들어 제목별 쪽수를 잰다. 도구가 없거나 실패하면 None(목차에서 쪽수 생략)."""
    soffice, pdftotext, pdfinfo = find_soffice(), shutil.which("pdftotext"), shutil.which("pdfinfo")
    if not (soffice and pdftotext and pdfinfo):
        return None
    run = lambda *cmd: subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    try:
        run(soffice, "--headless", "--convert-to", "pdf", "--outdir", str(work), str(docx_path))
        pdf = work / f"{docx_path.stem}.pdf"
        info = re.search(r"Pages:\s+(\d+)", run(pdfinfo, str(pdf)).stdout)
        if not info:
            return None
        texts = [run(pdftotext, "-f", str(n), "-l", str(n), "-layout", str(pdf), "-").stdout
                 for n in range(1, int(info.group(1)) + 1)]
    except (OSError, subprocess.SubprocessError):
        return None
    return heading_pages(texts, heads)


def build_docx(blocks_path: Path, data: dict, out: Path, style_path: Path, work: Path) -> str | None:
    """docx 생성. soffice가 있으면 목차 쪽수가 안정될 때까지 다시 만든다."""
    heads = [b["text"] for b in data["blocks"] if b["type"] == "h" and b["lvl"] <= 3]
    error = run_node("docx.js", blocks_path, out, style_path)
    if error or not (find_soffice() and heads):
        return error
    pages_path = work / "pages.json"
    # 첫 회는 자리표시자 0을 넣는다. 목차 줄이 제목과 같아져 본문으로 잘못 잡히는 일을 막는다.
    pages = {h: 0 for h in heads}
    for _ in range(MAX_PAGE_PASSES):
        pages_path.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        error = run_node("docx.js", blocks_path, out, style_path, pages_path)
        if error:
            return error
        measured = measure_pages(out, heads, work)
        if measured is None or len(measured) < len(heads):
            # 쪽수를 다 찾지 못하면 틀린 쪽수를 싣지 않고 생략한다.
            print("참고: 목차 쪽수를 측정하지 못해 생략했다.")
            return run_node("docx.js", blocks_path, out, style_path)
        if measured == pages:
            return None
        pages = measured
    pages_path.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return run_node("docx.js", blocks_path, out, style_path, pages_path)


def report(result: Result) -> None:
    for title, items in (("md에 있는데 빠진 숫자", result.missing), ("md에 없는 숫자", result.extra),
                         ("줄어든 문구", result.phrases)):
        if items:
            print(f"  {title} {len(items)}건:")
            for item in items:
                print(f"    {item}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dart-export", description="보고서 md → docx·pptx·html")
    ap.add_argument("report", type=Path)
    for fmt in FORMATS:
        ap.add_argument(f"--{fmt}", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("reports/export"))
    ap.add_argument("--style", default="default")
    args = ap.parse_args(argv)

    if not args.report.is_file():
        print(f"보고서를 찾을 수 없다: {args.report}")
        return 1
    wanted = [f for f in FORMATS if getattr(args, f)] or list(FORMATS)
    md = args.report.read_text(encoding="utf-8")
    data = parse_file(args.report)
    style = load_style(args.style)
    args.out.mkdir(parents=True, exist_ok=True)

    failed = False
    with tempfile.TemporaryDirectory(prefix="dart-export-") as tmp:
        work = Path(tmp)
        blocks_path = work / "blocks.json"
        style_path = work / "style.json"
        blocks_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")
        for fmt in wanted:
            out = (args.out / f"{args.report.stem}.{fmt}").resolve()
            if fmt in NODE_PACKAGE and (problem := node_problem(fmt)):
                print(f"{fmt}: 건너뜀 — {problem}")
                continue
            if fmt == "html":
                html_builder.build(data, style, out)
                error = None
            elif fmt == "docx":
                error = build_docx(blocks_path, data, out, style_path, work)
            else:
                error = run_node("pptx.js", blocks_path, out, style_path)
            if error:
                print(f"{fmt}: 빌드 실패 — {error}")
                failed = True
                continue
            result = verify(md, fmt, out)
            print(f"{fmt}: {out} ({out.stat().st_size:,} bytes) — 숫자 검증 {'통과' if result.ok else '실패'}")
            report(result)
            failed = failed or not result.ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
