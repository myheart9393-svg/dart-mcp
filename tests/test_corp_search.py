from dart_mcp.client import search_corp_codes

ENTRIES = [
    {"corp_code": "00688996", "corp_name": "KB금융", "stock_code": "105560"},
    {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
    {"corp_code": "00000001", "corp_name": "삼성전자판매", "stock_code": ""},
]


def test_legal_name_suffix_fallback():
    # DART 목록은 상장 약칭("KB금융")이라 법인명("KB금융지주", "(주)KB금융지주")으로는 부분일치가 안 된다
    assert [e["corp_code"] for e in search_corp_codes(ENTRIES, "KB금융지주")] == ["00688996"]
    assert [e["corp_code"] for e in search_corp_codes(ENTRIES, "(주)KB금융지주")] == ["00688996"]
    assert search_corp_codes(ENTRIES, "삼성전자주식회사")[0]["corp_code"] == "00126380"
    # 정상 검색은 그대로: 상장사 우선
    assert [e["corp_code"] for e in search_corp_codes(ENTRIES, "삼성전자")] == ["00126380", "00000001"]
    assert search_corp_codes(ENTRIES, "없는회사지주") == []
