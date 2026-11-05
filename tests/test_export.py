"""/dart-export: 파서, 빌더, 숫자 검증."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from dart_mcp.export import cli, html as html_builder, verify as verify_mod
from dart_mcp.export.parse_md import fallback_title, parse, plain

SAMPLE = """# 가나전자 vs 다라전자 비교분석 (2025 사업보고서 기준)

> 출처: 가나전자 rcept_no 20260301000001 / 작성일 2026-11-04
> 두 회사 모두 **연결**.

> **범위 안내**: 사업 구성이 다르다 (20260301000001, 3.1).

## 1. 요약

- **규모**: 가나전자가 4–5배 크다.
- 표본 2건이라 경고: 통계적 의미 제한.
  - 하위 항목 7.5%[^a]
1. 번호 항목 88.9%

[^a]: 각주 내용 12.5%.

## 2. 핵심 지표

ROE는 지배주주 기준이다.

| 지표 (백만원 / %) | 가나 FY2023·연결 | 가나 FY2024·연결 | 가나 FY2025·연결 | 다라 FY2023·연결 | 다라 FY2024·연결 | 다라 FY2025·연결 |
|---|---:|---:|---:|---:|---:|---:|
| 매출액 | 1,000 | 2,000 | 3,000 | 900 | 800 | 700 |
| 당기순이익 | 10 | 20 | 30 | −11 | −22 | 33 |
| 영업이익률(%) (계산) | 15.4 | 18.4 | 18.3 | 6.4¹ | 6.3 | 9.0 |

¹ FY2023은 기말 기준.
출처: 가나 (20260301000001, 재무API) / 다라 (20260301000002, 재무API)

**판단**: 가나전자가 크다. 추정: 격차는 유지될 수 있다.

### 2.1 세부

| 구분 | 값 |
|---|---:|
| 파이프 a\\|b | 41 |

**라벨 표**

| 구분 | 2024 | 2025 |
|---|---|---|
| 비율 | 1.5 | 2.5 |

이 보고서는 투자 권유가 아니다.

<!-- generated:end -->
"""

needs_docx = pytest.mark.skipif(cli.node_problem("docx") is not None, reason="node 또는 docx 패키지 없음")
needs_pptx = pytest.mark.skipif(cli.node_problem("pptx") is not None, reason="node 또는 pptxgenjs 패키지 없음")


def blocks_of(md: str = SAMPLE) -> list[dict]:
    return parse(md)["blocks"]


def tables_of(md: str = SAMPLE) -> list[dict]:
    return [b for b in blocks_of(md) if b["type"] == "table"]


def write_report(tmp_path: Path, md: str = SAMPLE, name: str = "샘플_비교분석_2026-11-04.md") -> Path:
    path = tmp_path / name
    path.write_text(md, encoding="utf-8")
    return path


# ---- 파서: 표지

def test_cover_comes_from_h1_and_first_quote():
    meta = parse(SAMPLE)["meta"]
    assert meta["title"] == "가나전자 vs 다라전자 비교분석"
    assert meta["subtitle"] == "2025 사업보고서 기준"
    assert meta["date"] == "2026-11-04"
    assert len(meta["cover"]) == 2
    assert meta["closing"] == "이 보고서는 투자 권유가 아니다."


def test_only_first_quote_moves_to_cover():
    assert [b for b in blocks_of() if b["type"] == "quote"][0]["paras"][0][0]["t"] == "범위 안내"


def test_missing_h1_uses_filename_without_date():
    assert fallback_title(Path("쿠팡_3분기실적_2026-11-05.md")) == "쿠팡 3분기실적"
    assert parse("본문만 있다.", "대체 제목")["meta"]["title"] == "대체 제목"
    assert parse("본문만 있다.")["meta"]["date"] is None


# ---- 파서: 인라인

def test_cite_is_recognized_for_any_company_name():
    runs = next(b for b in blocks_of("(가상회사 20260301000001, 5.3) 앞 글 (20260301000002, 재무API; 20260301000002, 5)")
                if b["type"] in ("p", "source"))["runs"]
    assert [r["t"] for r in runs if r.get("k") == "cite"] == [
        "(가상회사 20260301000001, 5.3)", "(20260301000002, 재무API; 20260301000002, 5)"]


def test_estimate_and_bold_runs():
    verdict = next(b for b in blocks_of() if b["type"] == "verdict")
    assert verdict["runs"][0] == {"t": "판단", "b": True}
    assert any(r.get("k") == "est" and r["t"] == "추정:" for r in verdict["runs"])


def test_en_dash_range_is_kept():
    item = next(b for b in blocks_of() if b["type"] == "ul")["items"][0]
    assert "4–5배" in plain(item["runs"])


def test_list_levels_markers_and_footnote():
    items = next(b for b in blocks_of() if b["type"] == "ul")["items"]
    assert items[2]["lvl"] == 1
    assert {"t": "[a]", "k": "fn"} in items[2]["runs"]
    assert items[3]["marker"] == "1."
    note = next(b for b in blocks_of() if b["type"] == "note" and "각주" in plain(b["runs"]))
    assert plain(note["runs"]).startswith("[a]")


def test_block_kinds():
    kinds = {b["type"] for b in blocks_of()}
    assert kinds == {"h", "quote", "ul", "p", "note", "table", "source", "verdict", "label"}
    assert any(b.get("closing") for b in blocks_of())


# ---- 파서: 표

def test_two_level_header_only_when_all_columns_match():
    first, second, third = tables_of()
    assert first["groups"] == [{"label": "가나 (연결)", "span": 3}, {"label": "다라 (연결)", "span": 3}]
    assert first["subheader"][:2] == ["FY2023", "FY2024"]
    assert "groups" not in second and "groups" not in third


def test_group_header_without_basis_and_company_with_space():
    md = "| | SK 하이 FY2024 | SK 하이 FY2025 |\n|---|---|---|\n| 값 | 1 | 2 |\n"
    assert tables_of(md)[0]["groups"] == [{"label": "SK 하이", "span": 2}]


def test_caption_from_heading_label_or_none():
    first, second, third = tables_of()
    assert first["caption"] == "핵심 지표"  # H2와 표 사이에 문단이 있어도 찾는다. 절 번호는 뺀다.
    assert second["caption"] == "세부"
    assert third["caption"] == "라벨 표"
    assert tables_of("앞 글\n\n- 목록\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")[0]["caption"] is None


def test_escaped_pipe_and_short_or_long_rows():
    assert plain(tables_of()[1]["rows"][0][0]) == "파이프 a|b"
    md = "| a | b |\n|---|---|\n| 1 |\n| 2 | 3 | 4 |\n"
    rows = [[plain(c) for c in r] for r in tables_of(md)[0]["rows"]]
    assert rows == [["1", ""], ["2", "3 4"]]  # 남는 칸의 내용을 버리지 않는다.


def test_numeric_column_is_right_aligned_without_colon():
    assert tables_of()[2]["align"] == ["l", "r", "r"]


# ---- 파서: 차트 스펙

def test_chart_values_are_table_values_sorted_by_year():
    charts = tables_of()[0]["charts"]
    assert [c["title"] for c in charts] == ["매출액", "영업이익률(%) (계산)"]
    revenue, margin = charts
    assert revenue["unit"] == "백만원" and margin["unit"] == "%"
    assert revenue["categories"] == ["FY2023", "FY2024", "FY2025"]
    assert revenue["series"][1] == {"name": "다라 (연결)", "values": [900.0, 800.0, 700.0], "labels": ["900", "800", "700"]}
    assert margin["decimals"] == 1
    assert margin["series"][1]["labels"][0] == "6.4¹" and margin["series"][1]["values"][0] == 6.4


def test_descending_years_become_chronological():
    md = "| 지표 (백만원) | 2025 (제57기) | 2024 (제56기) | 2023 (제55기) |\n|---|---|---|---|\n| 매출액 | −3 | 2 | 1 |\n"
    chart = tables_of(md)[0]["charts"][0]
    assert chart["categories"] == ["2023", "2024", "2025"]
    assert chart["series"][0]["values"] == [1.0, 2.0, -3.0]


@pytest.mark.parametrize("md", [
    "| 지표 | 2024 | 2025 |\n|---|---|---|\n| 매출액 | 1 | 2 |\n",  # 2개년
    "| 지표 | 2023 | 2024 | 2025 | 기준 |\n|---|---|---|---|---|\n| 매출액 | 1 | 2 | 3 | x |\n",  # 연도 아닌 열
    "| 지표 | 2023 | 2024 | 2025 |\n|---|---|---|---|\n| 매출액 | 1 | – | 3 |\n",  # 숫자 아닌 칸
    "| 지표 | 2023 | 2024 | 2025 |\n|---|---|---|---|\n| 매출액 증감률 | 1 | 2 | 3 |\n",  # 증감률
])
def test_no_chart_when_not_a_clean_multi_year_table(md):
    assert "charts" not in tables_of(md)[0]


# ---- 숫자 토큰

def test_tokens_handle_commas_signs_and_hyphens():
    assert verify_mod.tokens("−1,816,669 와 +11.0% 그리고 -5, 2026-03-13") == {
        "-1816669": 1, "+11.0": 1, "-5": 1, "2026": 1, "03": 1, "13": 1}


def test_md_text_drops_only_non_rendered_syntax():
    text = verify_mod.md_text("|---|---:|\n**1,000** [링크](http://x/99) `7`<br>끝\n<!-- 5 -->")
    assert verify_mod.tokens(text) == {"1000": 1, "7": 1}


# ---- HTML

def test_html_contains_everything_and_passes(tmp_path):
    out = tmp_path / "r.html"
    html_builder.build(parse(SAMPLE), cli.load_style("default"), out)
    text = out.read_text(encoding="utf-8")
    assert '<th colspan="3">가나 (연결)</th>' in text
    assert "<svg" in text and "[표] 1 핵심 지표" in text
    assert "Strictly Private" not in text and "NAVER" not in text and "November" not in text
    assert verify_mod.verify(SAMPLE, "html", out).ok


def test_html_escapes_and_handles_duplicate_headings(tmp_path):
    out = tmp_path / "r.html"
    md = "## 같은 <제목>\n\n글\n\n## 같은 <제목>\n\n글\n"
    html_builder.build(parse(md), cli.load_style("default"), out)
    text = out.read_text(encoding="utf-8")
    assert "같은 &lt;제목&gt;" in text and 'id="sec-같은-제목-2"' in text


def test_html_verify_detects_dropped_number(tmp_path):
    out = tmp_path / "r.html"
    html_builder.build(parse(SAMPLE), cli.load_style("default"), out)
    text = out.read_text(encoding="utf-8")
    out.write_text(text.replace("<td class=\"r\">−22</td>", "<td class=\"r\">22</td>"), encoding="utf-8")
    result = verify_mod.verify(SAMPLE, "html", out)
    assert not result.ok and any(m.startswith("-22 ") for m in result.missing)


def test_html_verify_detects_count_loss_and_lost_phrase(tmp_path):
    md = "- 값 77\n- 값 77\n\n추정: 이렇다.\n"
    out = tmp_path / "r.html"
    html_builder.build(parse("- 값 77\n\n이렇다.\n"), cli.load_style("default"), out)
    result = verify_mod.verify(md, "html", out)
    assert any(m.startswith("77 ") for m in result.missing)
    assert any("추정:" in p for p in result.phrases)


def test_style_file_sets_header_footer_and_colors(tmp_path):
    style_path = tmp_path / "s.json"
    style_path.write_text(json.dumps({"header": "대외비", "footer": "바닥글", "colors": {"navy": "000080"}}), encoding="utf-8")
    style = cli.load_style(str(style_path))
    assert style["colors"]["navy"] == "000080" and style["colors"]["green"] == "329767"
    out = tmp_path / "r.html"
    html_builder.build(parse(SAMPLE), style, out)
    text = out.read_text(encoding="utf-8")
    assert "대외비" in text and "바닥글" in text and "--navy:#000080" in text


# ---- 세 형식 전체

@needs_docx
@needs_pptx
def test_all_formats_pass_and_source_is_untouched(tmp_path, capsys):
    report = write_report(tmp_path)
    before = hashlib.sha256(report.read_bytes()).hexdigest()
    out = tmp_path / "export"
    assert cli.main([str(report), "--out", str(out)]) == 0
    assert hashlib.sha256(report.read_bytes()).hexdigest() == before
    assert {p.suffix for p in out.iterdir()} == {".docx", ".pptx", ".html"}
    assert capsys.readouterr().out.count("숫자 검증 통과") == 3


@needs_docx
def test_docx_has_no_fixed_phrases_or_page_numbers_without_soffice(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "find_soffice", lambda: None)
    report = write_report(tmp_path)
    assert cli.main([str(report), "--docx", "--out", str(tmp_path)]) == 0
    path = tmp_path / f"{report.stem}.docx"
    text = verify_mod.docx_text(path)
    assert "가나전자 vs 다라전자 비교분석" in text and "[표] 2 세부" in text
    assert "Strictly Private" not in text and "November" not in text
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        headers = "".join(z.read(n).decode("utf-8") for n in names if re.search(r"word/(header|footer)\d*\.xml", n))
        body = z.read("word/document.xml").decode("utf-8")
    assert "Strictly Private" not in headers and "OpenDART" not in headers
    # 목차 줄에 쪽수 탭이 없다.
    assert "<w:tab/>" not in body.split("1. 요약")[1].split("2. 핵심 지표")[0]


@needs_docx
def test_docx_shows_page_numbers_from_pages_json(tmp_path):
    data = parse(SAMPLE)
    blocks = tmp_path / "b.json"
    blocks.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    style = tmp_path / "s.json"
    style.write_text(json.dumps(cli.load_style("default"), ensure_ascii=False), encoding="utf-8")
    pages = tmp_path / "p.json"
    pages.write_text(json.dumps({"1. 요약": 3}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "r.docx"
    assert cli.run_node("docx.js", blocks, out, style, pages) is None
    assert "1. 요약 3" in verify_mod.docx_text(out)


WIDE_MD = (
    "# 넓은 표\n\n## 앞\n\n글\n\n## 평가\n\n설명 문단\n\n"
    "| 주체 | 대상 | 역할 | 목적 | 방법 | 가중(자산:수익) | WACC | g | β(U/L) | 멀티플 | 결과 | 범위 | 출처 |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    "| 이촌회계법인 | 주식회사 휴맥스 | 재무자문 | 합병가액 | DCF | – | 12.39% | 1.00% | 0.4324/0.7427 | – "
    "| 26,365원 | 25,929원–27,073원 | (§5 @23960) |\n\n"
    "출처: 표 아래 출처 줄\n\n## 뒤\n\n글\n"
)
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


@needs_docx
def test_docx_wide_table_goes_landscape_fixed_and_within_page(tmp_path):
    report = write_report(tmp_path, WIDE_MD, "wide.md")
    assert cli.main([str(report), "--docx", "--out", str(tmp_path)]) == 0
    with zipfile.ZipFile(tmp_path / "wide.docx") as z:
        root = etree.fromstring(z.read("word/document.xml"))
    table = next(root.iter(f"{W_NS}tbl"))
    assert table.find(f"{W_NS}tblPr/{W_NS}tblLayout").get(f"{W_NS}type") == "fixed"
    grid = sum(int(c.get(f"{W_NS}w")) for c in table.find(f"{W_NS}tblGrid"))
    sizes = [s.get(f"{W_NS}orient") for s in root.iter(f"{W_NS}pgSz")]
    assert sizes.count("landscape") == 1 and len(sizes) == 3  # 세로 → 가로 → 세로
    landscape = next(s for s in root.iter(f"{W_NS}sectPr") if s.find(f"{W_NS}pgSz").get(f"{W_NS}orient") == "landscape")
    size, margin = landscape.find(f"{W_NS}pgSz"), landscape.find(f"{W_NS}pgMar")
    text_width = int(size.get(f"{W_NS}w")) - int(margin.get(f"{W_NS}left")) - int(margin.get(f"{W_NS}right"))
    assert grid <= text_width
    # 제목·문단·출처가 표와 같은 가로 구역에 있다.
    body = list(root.find(f"{W_NS}body"))
    table_pos = body.index(table)
    heading = table_pos - next(i for i, e in enumerate(reversed(body[:table_pos])) if "".join(e.itertext()) == "평가") - 1
    source = next(i for i, e in enumerate(body) if "출처: 표 아래" in "".join(e.itertext()))
    assert not any(e.find(f"{W_NS}pPr/{W_NS}sectPr") is not None for e in body[heading:source])
    assert body[heading - 1].find(f"{W_NS}pPr/{W_NS}sectPr") is not None  # 가로 구역은 제목부터 시작한다.


@needs_docx
def test_docx_narrow_table_stays_portrait_and_fixed(tmp_path):
    report = write_report(tmp_path)
    assert cli.main([str(report), "--docx", "--out", str(tmp_path)]) == 0
    with zipfile.ZipFile(tmp_path / f"{report.stem}.docx") as z:
        root = etree.fromstring(z.read("word/document.xml"))
    assert [s.get(f"{W_NS}orient") for s in root.iter(f"{W_NS}pgSz")] == ["portrait"]
    assert all(t.find(f"{W_NS}tblPr/{W_NS}tblLayout") is not None for t in root.iter(f"{W_NS}tbl"))


@needs_pptx
def test_pptx_wide_table_columns_fit_unbreakable_tokens(tmp_path):
    report = write_report(tmp_path, WIDE_MD, "wide.md")
    assert cli.main([str(report), "--pptx", "--out", str(tmp_path)]) == 0
    with zipfile.ZipFile(tmp_path / "wide.pptx") as z:
        slide = next(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n) and b"<a:tbl>" in z.read(n))
        root = etree.fromstring(z.read(slide))
    inches = [int(c.get("w")) / 914400 for c in root.iter(f"{A_NS}gridCol")]
    assert len(inches) == 13 and sum(inches) <= 12.14
    em = 10 / 72  # 13열 표는 10pt
    assert inches[8] >= len("0.4324/0.7427") * 0.58 * em  # β(U/L)
    assert inches[6] >= len("12.39%") * 0.58 * em  # WACC


@needs_pptx
def test_pptx_chart_is_native_and_values_match_table(tmp_path):
    report = write_report(tmp_path)
    assert cli.main([str(report), "--pptx", "--out", str(tmp_path)]) == 0
    path = tmp_path / f"{report.stem}.pptx"
    text, values = verify_mod.pptx_content(path)
    assert {float(v) for v in values} >= {1000.0, 3000.0, 700.0, 15.4, 9.0}
    assert "이 보고서는 투자 권유가 아니다." in text and "4–5배" in text and "추정:" in text
    with zipfile.ZipFile(path) as z:
        assert sum(bool(re.fullmatch(r"ppt/charts/chart\d+\.xml", n)) for n in z.namelist()) == 2


def _section_slide_count(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        return sum(bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", n)) for n in z.namelist())


@needs_pptx
def test_pptx_makes_slide_per_h2_and_splits_overflow(tmp_path):
    short = write_report(tmp_path, "# 제목\n\n## 가\n\n글\n\n## 나\n\n글\n", "short.md")
    long_rows = "\n".join(f"| 행{i} | {i}00 |" for i in range(80))
    long_md = f"# 제목\n\n## 가\n\n| 구분 | 값 |\n|---|---:|\n{long_rows}\n\n" + "\n".join(f"- 항목 {i} 내용." for i in range(60))
    long = write_report(tmp_path, long_md, "long.md")
    assert cli.main([str(short), "--pptx", "--out", str(tmp_path)]) == 0
    assert cli.main([str(long), "--pptx", "--out", str(tmp_path)]) == 0
    assert _section_slide_count(tmp_path / "short.pptx") == 4  # 표지·목차·H2 둘
    assert _section_slide_count(tmp_path / "long.pptx") > 5
    assert "(계속)" in verify_mod.pptx_content(tmp_path / "long.pptx")[0]


@needs_pptx
def test_pptx_verify_detects_new_number_on_slide_and_chart(tmp_path):
    report = write_report(tmp_path)
    assert cli.main([str(report), "--pptx", "--out", str(tmp_path)]) == 0
    path = tmp_path / f"{report.stem}.pptx"
    tampered = tmp_path / "tampered.pptx"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = data.replace("가나전자".encode(), "가나전자 987654".encode(), 1)
            if re.fullmatch(r"ppt/charts/chart\d+\.xml", item.filename):
                data = data.replace(b"<c:v>3000</c:v>", b"<c:v>3100</c:v>")
            dst.writestr(item, data)
    result = verify_mod.verify(SAMPLE, "pptx", tampered)
    assert "987654" in result.extra and "차트 3100" in result.extra


@needs_docx
def test_cli_returns_1_and_lists_missing_when_verification_fails(tmp_path, monkeypatch, capsys):
    report = write_report(tmp_path)
    real = verify_mod.docx_text
    monkeypatch.setattr(verify_mod, "docx_text", lambda p: real(p).replace("1,000", ""))
    assert cli.main([str(report), "--docx", "--out", str(tmp_path)]) == 1
    captured = capsys.readouterr().out
    assert "숫자 검증 실패" in captured and "1000 (md" in captured


# ---- Node 없음·기타

def test_missing_node_skips_only_that_format(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    report = write_report(tmp_path)
    assert cli.main([str(report), "--out", str(tmp_path)]) == 0
    captured = capsys.readouterr().out
    assert "docx: 건너뜀" in captured and "pptx: 건너뜀" in captured and "html:" in captured
    assert captured.count("npm install --prefix src/dart_mcp/export") == 2
    assert {p.suffix for p in tmp_path.iterdir() if p.stem == report.stem} == {".md", ".html"}


def test_format_flags_select_outputs(tmp_path):
    report = write_report(tmp_path)
    out = tmp_path / "x"
    assert cli.main([str(report), "--html", "--out", str(out)]) == 0
    assert [p.suffix for p in out.iterdir()] == [".html"]


def test_missing_report_returns_1(tmp_path):
    assert cli.main([str(tmp_path / "없음.md")]) == 1


def test_heading_pages_skips_cover_and_uses_first_match():
    texts = ["1. 요약\n", "목 차\n1. 요약 ........ 0\n", "머리\n1.  요약\n본문", "1. 요약\n2. 표\n"]
    assert cli.heading_pages(texts, ["1. 요약", "2. 표", "없음"]) == {"1. 요약": 3, "2. 표": 4}
