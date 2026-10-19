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
