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
