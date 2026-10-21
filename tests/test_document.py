from dart_mcp.document import decode_dart_xml, detect_declared_encoding, parse_dart_xml

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT ACLASS="A">
<DOCUMENT-NAME>사업보고서</DOCUMENT-NAME>
<BODY>
<SECTION-1>
<TITLE ATOC="Y">I. 회사의 개요</TITLE>
<P>당사는   반도체를&nbsp;만듭니다.
여러 줄로   나뉜 문단.</P>
<SECTION-2>
<TITLE>1. 주요 재무정보</TITLE>
<TABLE WIDTH="600">
<COLGROUP><COL WIDTH="200"/><COL WIDTH="200"/></COLGROUP>
<TBODY>
<TR><TH>구분</TH><TH>2024년</TH><TH>2023년</TH></TR>
<TR><TD>매출액</TD><TD ALIGN="RIGHT">300,000</TD><TD>258,000</TD></TR>
<TR><TD>영업이익
(연결)</TD><TE COLSPAN="2">32,000</TE></TR>
</TBODY>
</TABLE>
<WEIRD-TAG>알 수 없는 태그 안의 텍스트</WEIRD-TAG>
</SECTION-2>
</SECTION-1>
</BODY>
</DOCUMENT>
"""


def test_title_becomes_markdown_heading():
    md = parse_dart_xml(SAMPLE.encode("utf-8"))
    lines = md.splitlines()
    assert "## I. 회사의 개요" in lines
    assert "## 1. 주요 재무정보" in lines
    # 헤딩 앞뒤는 빈 줄로 분리되어야 한다
    i = lines.index("## I. 회사의 개요")
    assert lines[i - 1] == "" and lines[i + 1] == ""


def test_table_becomes_markdown_table_with_colspan_padding():
    md = parse_dart_xml(SAMPLE.encode("utf-8"))
    assert "| 구분 | 2024년 | 2023년 |" in md
    assert "|---|---|---|" in md
    assert "| 매출액 | 300,000 | 258,000 |" in md
    # 셀 안 개행 -> 공백, COLSPAN=2 -> 빈 셀 하나 추가, TE도 셀로 인식
    assert "| 영업이익 (연결) | 32,000 | |" in md


def test_whitespace_and_unknown_tags_and_tag_collection():
    tags: set[str] = set()
    md = parse_dart_xml(SAMPLE.encode("utf-8"), seen_tags=tags)
    assert "당사는 반도체를 만듭니다." in md  # 연속 공백/&nbsp; 정리
    assert "알 수 없는 태그 안의 텍스트" in md  # recover 모드, 모르는 태그도 텍스트 보존
    assert "\n\n\n" not in md
    expected = {"DOCUMENT", "SECTION-1", "SECTION-2", "TITLE", "TABLE", "TR", "TD", "TE", "TH", "WEIRD-TAG"}
    assert expected <= tags


def test_encoding_declaration_is_respected_with_cp949_fallback():
    xml_euckr = '<?xml version="1.0" encoding="euc-kr"?><DOCUMENT><P>한글</P></DOCUMENT>'.encode("cp949")
    assert detect_declared_encoding(xml_euckr) == "euc-kr"
    text, used = decode_dart_xml(xml_euckr)
    assert used == "cp949" and "한글" in text
    assert "한글" in parse_dart_xml(xml_euckr)

    # 선언이 거짓(utf-8이라 적혀 있지만 실제 cp949)인 경우 -> 폴백
    lying = '<?xml version="1.0" encoding="utf-8"?><DOCUMENT><P>한글</P></DOCUMENT>'.encode("cp949")
    assert "한글" in parse_dart_xml(lying)


ROWSPAN_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>
<FORMULA-VERSION ADATE="20241231">6.0</FORMULA-VERSION>
<SUMMARY><EXTRACTION ACODE="LINK_FLAG">C</EXTRACTION></SUMMARY>
<BODY>
<TABLE>
<TR><TD ROWSPAN="2">사업연도</TD><TU AUNIT="PERIODFROM" AUNITVALUE="20240101">2024년 01월 01일</TU><TD>부터</TD></TR>
<TR><TU AUNIT="PERIODTO" AUNITVALUE="20241231">2024년 12월 31일</TU><TD>까지</TD></TR>
<TR><TD>비고</TD><TD COLSPAN="2">-</TD></TR>
</TABLE>
</BODY>
</DOCUMENT>
"""


def test_rowspan_and_tu_cells_and_metadata_skipped():
    md = parse_dart_xml(ROWSPAN_SAMPLE.encode("utf-8"))
    assert "# 사업보고서" in md.splitlines()
    assert "6.0" not in md and "LINK_FLAG" not in md and "\nC\n" not in md  # 메타데이터 제외
    assert "| 사업연도 | 2024년 01월 01일 | 부터 |" in md  # TU가 셀로 인식됨
    assert "| | 2024년 12월 31일 | 까지 |" in md  # ROWSPAN 칸은 빈 셀로 유지되어 열이 밀리지 않음
    assert "| 비고 | - | |" in md


# 2012년 사업보고서(20120330000791) 실측 구조: 선언은 utf-8인데 실제 바이트는 cp949,
# 그리고 편집기 템플릿 태그(INSERTION/COMMENT/LIBRARYLIST, FILENAME, WARNING, APPENDIX)가 본문 사이에 있다.
LEGACY_2012 = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
<DOCUMENT-HEADER AEXT-CLASS="Y"><DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>
<FORMULA-VERSION SUBVER="1" ADATE="20120102">1.7</FORMULA-VERSION></DOCUMENT-HEADER>
<BODY>
<INSERTION ABASISNUMBER="SE1"><COMMENT>◆click◆ 정정문서 작성시 『정오표』 삽입</COMMENT>
<LIBRARYLIST>정정신고(보고)-대표이사등의확인.LCommon</LIBRARYLIST></INSERTION>
<SECTION-1><TITLE ATOC="Y">I. 회사의 개요</TITLE>
<FILENAME ATYPE="dsl">4_주식의총수현황</FILENAME>
<P>당사는 검사용 프로브를 만듭니다.</P>
<WARNING>※ 주권상장법인은 XBRL 재무제표를 삽입하여야 합니다.</WARNING>
<APPENDIX ATYPE="IMAGE"><COMMENT>◆click◆ 『확인서』 그림파일 삽입</COMMENT></APPENDIX>
<P>꼬리 문단</P>
</SECTION-1>
</BODY>
</DOCUMENT>
""".encode("cp949")


def test_legacy_2012_lying_declaration_and_editor_tags_skipped():
    assert detect_declared_encoding(LEGACY_2012) == "utf-8"
    text, used = decode_dart_xml(LEGACY_2012)
    assert used == "cp949" and "�" not in text
    md = parse_dart_xml(LEGACY_2012)
    assert "당사는 검사용 프로브를 만듭니다." in md and "꼬리 문단" in md
    for junk in ("◆click◆", ".LCommon", "4_주식의총수현황", "XBRL 재무제표를 삽입"):
        assert junk not in md


def test_declared_cp949_but_actually_utf8():
    # cp949로 먼저 읽으면 utf-8 한글 바이트도 오류 없이 엉뚱한 글자로 "성공"한다 → utf-8(엄격)을 먼저 본다
    raw = '<?xml version="1.0" encoding="euc-kr"?><DOCUMENT><P>한글 사업보고서</P></DOCUMENT>'.encode("utf-8")
    assert detect_declared_encoding(raw) == "euc-kr"
    text, used = decode_dart_xml(raw)
    assert used == "utf-8" and "한글 사업보고서" in text
    assert "한글 사업보고서" in parse_dart_xml(raw)


def _table_md(table_xml: str) -> list[str]:
    md = parse_dart_xml(f'<?xml version="1.0" encoding="utf-8"?><DOCUMENT><BODY>{table_xml}</BODY></DOCUMENT>'.encode())
    return [ln for ln in md.splitlines() if ln.startswith("|")]


def test_short_row_still_consumes_non_adjacent_rowspan():
    # 2행은 셀이 모자라 2열에서 끝나지만, 떨어진 3열의 ROWSPAN도 한 행 소진돼야 4행이 밀리지 않는다
    lines = _table_md(
        "<TABLE>"
        "<TR><TH>구분</TH><TH>a</TH><TH>b</TH><TH>c</TH></TR>"
        '<TR><TD ROWSPAN="2">A</TD><TD>B</TD><TD>C</TD><TD ROWSPAN="3">D</TD></TR>'
        "<TR><TD>E</TD></TR>"
        "<TR><TD>F</TD><TD>G</TD><TD>H</TD></TR>"
        "<TR><TD>I</TD><TD>J</TD><TD>K</TD><TD>L</TD></TR>"
        "</TABLE>"
    )
    assert lines == [
        "| 구분 | a | b | c |",
        "|---|---|---|---|",
        "| A | B | C | D |",
        "| | E | | |",
        "| F | G | H | |",
        "| I | J | K | L |",
    ]


def test_header_row_only_when_th_or_thead():
    # 첫 행이 TD면 빈 머리글을 넣어 데이터 행이 열 제목처럼 보이지 않게 한다
    assert _table_md("<TABLE><TR><TD>매출액</TD><TD>300</TD></TR><TR><TD>영업이익</TD><TD>30</TD></TR></TABLE>") == [
        "| | |", "|---|---|", "| 매출액 | 300 |", "| 영업이익 | 30 |",
    ]
    # THEAD 안의 행은 TD여도 머리글
    assert _table_md("<TABLE><THEAD><TR><TD>구분</TD><TD>2024</TD></TR></THEAD>"
                     "<TBODY><TR><TD>매출액</TD><TD>300</TD></TR></TBODY></TABLE>")[:2] == ["| 구분 | 2024 |", "|---|---|"]
    # TH와 TD가 섞인 첫 행은 머리글이 아니다
    assert _table_md("<TABLE><TR><TH>매출액</TH><TD>300</TD></TR></TABLE>")[0] == "| | |"


def test_section_title_from_direct_child_title_only():
    from dart_mcp.document import build_outline

    xml = """<?xml version="1.0" encoding="utf-8"?><DOCUMENT><BODY>
<SECTION-1><P>제목 TITLE 없는 섹션</P>
<SECTION-2><TITLE>1. 하위 섹션 제목</TITLE><P>본문</P></SECTION-2>
</SECTION-1>
<SECTION-1><TITLE>II. 사업의 내용</TITLE><SECTION-2><TITLE>1. 개요</TITLE></SECTION-2></SECTION-1>
</BODY></DOCUMENT>""".encode()
    titles = {s.id: s.title for s in build_outline(xml)}
    assert titles["1"] == ""  # 하위 SECTION의 제목을 빌려 오지 않는다
    assert titles["1.1"] == "1. 하위 섹션 제목"
    assert titles["2"] == "II. 사업의 내용" and titles["2.1"] == "1. 개요"
