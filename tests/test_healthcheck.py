from dart_mcp.healthcheck import _SUMMARY_NA_RE, amount_candidates, bounded_in, parse_corp_codes, rounded_match


def test_amount_candidates_won_thousand_million_rounded():
    assert amount_candidates(1_234_567_890_123) == ["1,234,567,890,123", "1,234,567,890", "1,234,568"]
    assert amount_candidates(57_617_000_000) == ["57,617,000,000", "57,617,000", "57,617"]


def test_rounded_match_handles_api_already_rounded_to_millions():
    # 뉴엔에이아이 2025: API 57,617,000,000(백만원 반올림) vs 요약재무정보 원 단위 57,616,790,217
    assert rounded_match("| 자 산 총 계 | 57,616,790,217 | 29,916,957,236 |", 57_617_000_000) == "57,616,790,217(원)"
    # 정밀한 API 값은 원문이 백만원 단위여도 반올림 범위 안이면 일치
    assert rounded_match("| 자산총계 | 70,831 | 33,493 |", 70_831_234_567) == "70,831(백만원)"
    assert rounded_match("| 자산총계 | 70,833 |", 70_831_234_567) is None
    # 원문이 백만원 미만을 절사(한화손해보험)·올림(오리온홀딩스)해도 한 단위 안이면 일치
    assert rounded_match("| 자산총계> | 20,492,834 |", 20_492_834_690_000) == "20,492,834(백만원)"
    assert rounded_match("| 자산총계 | 6,183,411 |", 6_183_410_426_053) == "6,183,411(백만원)"


def test_summary_omitted_wording():
    assert _SUMMARY_NA_RE.search("소규모기업(자산총액 1천억원 미만)에 해당하므로 위 내용을 생략합니다.")
    assert _SUMMARY_NA_RE.search("해당사항 없습니다.")
    assert not _SUMMARY_NA_RE.search("| 자산총계 | 1,000 |")


def test_bounded_in_rejects_partial_numbers():
    text = "| 매출액 | 51,234 | 1,234.5 | 1,234 |"
    assert bounded_in(text, "1,234")
    assert not bounded_in("| 51,234 | 1,234,000 |", "1,234")


def test_parse_corp_codes_inline_and_comments(tmp_path):
    assert parse_corp_codes("00126380, 00164779") == ["00126380", "00164779"]
    p = tmp_path / "c.txt"
    p.write_text("00126380  # 삼성전자\n\n# 주석\n00164779\n", encoding="utf-8")
    assert parse_corp_codes(str(p)) == ["00126380", "00164779"]
