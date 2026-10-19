import io
import zipfile

from dart_mcp.cache import DisclosureCache, file_id_of
from dart_mcp.document import build_outline

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
<DOCUMENT-NAME>사업보고서</DOCUMENT-NAME>
<BODY>
<COVER><COVER-TITLE>사 업 보 고 서</COVER-TITLE><P>표지 문단</P></COVER>
<SECTION-1>
<TITLE>I. 회사의 개요</TITLE>
<SECTION-2><TITLE>1. 회사의 개요</TITLE><P>개요 본문</P></SECTION-2>
<SECTION-2><TITLE>2. 회사의 연혁</TITLE><P>연혁 본문</P>
  <SECTION-3><TITLE>가. 본점 이전</TITLE><P>이전 본문</P></SECTION-3>
</SECTION-2>
</SECTION-1>
<SECTION-1>
<TITLE>II. 사업의 내용</TITLE>
<P>사업 본문</P>
<TABLE><TR><TD>구분</TD><TD>값</TD></TR><TR><TD>매출</TD><TD>100</TD></TR></TABLE>
</SECTION-1>
</BODY>
</DOCUMENT>
"""


def test_outline_ids_levels_titles():
    secs = build_outline(SAMPLE.encode("utf-8"))
    got = [(s.id, s.level, s.title) for s in secs]
    assert got == [
        ("0", 0, "(표지 및 섹션 외 본문)"),
        ("1", 1, "I. 회사의 개요"),
        ("1.1", 2, "1. 회사의 개요"),
        ("1.2", 2, "2. 회사의 연혁"),
        ("1.2.1", 3, "가. 본점 이전"),
        ("2", 1, "II. 사업의 내용"),
    ]
    assert all(s.char_count == len(s.text) for s in secs)


def test_outline_text_scope():
    secs = {s.id: s for s in build_outline(SAMPLE.encode("utf-8"))}
    # 섹션 밖 본문("0")에는 표지만 있고 섹션 내용은 없다
    assert "표지 문단" in secs["0"].text and "# 사업보고서" in secs["0"].text
    assert "개요 본문" not in secs["0"].text and "사업 본문" not in secs["0"].text
    # 상위 섹션은 하위 섹션 내용을 포함한다
    assert "개요 본문" in secs["1"].text and "이전 본문" in secs["1"].text
    assert "이전 본문" in secs["1.2"].text and "개요 본문" not in secs["1.2"].text
    # 섹션 안 표도 같은 규칙으로 변환된다
    assert "| 매출 | 100 |" in secs["2"].text
    assert secs["1"].char_count > secs["1.2"].char_count > secs["1.2.1"].char_count


class _FakeClient:
    def __init__(self, zip_bytes: bytes):
        self.zip_bytes = zip_bytes
        self.calls = 0

    def get_document(self, rcept_no: str) -> bytes:
        self.calls += 1
        return self.zip_bytes


def _make_zip(rcept_no: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{rcept_no}.xml", SAMPLE.encode("utf-8"))
        zf.writestr(f"{rcept_no}_00760.xml", SAMPLE.replace("사업보고서", "감사보고서").encode("utf-8"))
    return buf.getvalue()


def test_cache_hit_skips_api(tmp_path):
    rcept_no = "20250101000001"
    client = _FakeClient(_make_zip(rcept_no))
    cache = DisclosureCache(tmp_path)

    disc = cache.get(rcept_no, client)
    assert client.calls == 1
    assert [f.file_id for f in disc.files] == ["main", "00760"]
    assert (tmp_path / rcept_no / f"{rcept_no}.zip").exists()
    assert (tmp_path / rcept_no / "outline.json").exists()
    assert (tmp_path / rcept_no / "sections_00760.json").exists()

    # 같은 인스턴스: 메모리 히트
    cache.get(rcept_no, client)
    assert client.calls == 1

    # 새 인스턴스(프로세스 재시작 가정): 디스크 히트, client 없이도 읽힌다
    cache2 = DisclosureCache(tmp_path)
    assert cache2.has(rcept_no)
    disc2 = cache2.get(rcept_no, None)
    assert disc2.get_file("main").get_section("1.2.1").title == "가. 본점 이전"
    assert disc2.get_file("00760").sections[0].text.startswith("# 감사보고서")
    assert client.calls == 1


def test_file_id_of():
    assert file_id_of("20250311001085.xml", "20250311001085") == "main"
    assert file_id_of("20250311001085_00760.xml", "20250311001085") == "00760"


NOTES_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<TITLE>1. 일반적 사항</TITLE><P>회사 개요 본문</P>
<TITLE>2. 중요한 회계처리방침</TITLE><P>회계정책 본문</P>
<TABLE><TR><TD>항목</TD><TD>금액</TD></TR></TABLE>
<TITLE>3. 우발부채와 약정사항</TITLE><P>소송 본문</P>
</SECTION-2>
<SECTION-2><TITLE>4. 재무제표</TITLE><P>본표 하나만</P></SECTION-2>
</SECTION-1>
</BODY></DOCUMENT>
"""


def test_title_subsections_are_added_with_t_ids():
    secs = build_outline(NOTES_SAMPLE.encode("utf-8"))
    by_id = {s.id: s for s in secs}
    assert [s.id for s in secs] == ["0", "1", "1.1", "1.1.t1", "1.1.t2", "1.1.t3", "1.2"]
    assert by_id["1.1.t1"].title == "1. 일반적 사항"
    assert by_id["1.1.t2"].title == "2. 중요한 회계처리방침"
    assert by_id["1.1.t3"].title == "3. 우발부채와 약정사항"
    assert all(by_id[f"1.1.t{n}"].kind == "title" and by_id[f"1.1.t{n}"].level == 3 for n in (1, 2, 3))
    assert by_id["1.1"].kind == "section"
    # 구간 텍스트: 자기 소제목 헤딩으로 시작하고 다음 소제목 내용은 포함하지 않음
    t2 = by_id["1.1.t2"].text
    assert t2.startswith("## 2. 중요한 회계처리방침") and "| 항목 | 금액 |" in t2
    assert "회사 개요 본문" not in t2 and "소송 본문" not in t2
    assert by_id["1.1.t2"].char_count == len(t2)


def test_no_title_subsections_when_single_title_or_only_child_sections():
    secs = build_outline(NOTES_SAMPLE.encode("utf-8"))
    ids = [s.id for s in secs]
    # "4. 재무제표"는 TITLE이 1개뿐 → 소제목 없음
    assert not any(i.startswith("1.2.t") for i in ids)
    # SECTION-1은 자체 TITLE 1개 + 자식 SECTION 제목들 → 자식 제목을 소제목으로 오인하지 않음
    assert not any(i.startswith("1.t") for i in ids)
    # 소제목 텍스트를 다 합치면 부모 섹션 본문과 내용이 같다(제목 중복 외 누락 없음)
    by_id = {s.id: s for s in secs}
    joined = "".join(by_id[f"1.1.t{n}"].text for n in (1, 2, 3))
    for phrase in ("회사 개요 본문", "회계정책 본문", "소송 본문", "| 항목 | 금액 |"):
        assert phrase in joined and phrase in by_id["1.1"].text


SEARCH_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>II. 사업의 내용</TITLE>
<SECTION-2><TITLE>6. 연구개발</TITLE><P>경쟁력 확보로 시작하는 문단. 중간 설명이 충분히 길게 이어진다. 중간 설명이 충분히 길게 이어진다. 마지막 문장은 시장의 경쟁력 확보</P></SECTION-2>
<SECTION-2><TITLE>7. 기타 참고사항</TITLE><P>상표 설명이 이어진다. 상표 설명이 이어진다. 상표 설명이 이어진다.</P></SECTION-2>
</SECTION-1>
</BODY></DOCUMENT>
"""


def test_search_reports_subsection_edge_matches_once(tmp_path, monkeypatch):
    """하위 섹션 첫머리·끝머리 매치가 상위(level 1) 섹션에서 다시 보고되지 않는다 (리노공업 2025 '경쟁' 실측 회귀)."""
    from dart_mcp import server

    rcept_no = "20250101000009"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{rcept_no}.xml", SEARCH_SAMPLE.encode("utf-8"))
    cache = DisclosureCache(tmp_path)
    cache.get(rcept_no, _FakeClient(buf.getvalue()))
    monkeypatch.setattr(server, "_cache", cache)

    r = server.search_in_disclosure(rcept_no, "경쟁력", context_chars=10)
    assert r["total_matches"] == 2
    assert {m["section_id"] for m in r["matches"]} == {"1.1"}
