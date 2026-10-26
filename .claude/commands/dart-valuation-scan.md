---
description: 기간 안의 가치평가 공시(합병·분할·영업양수도·주식교환·IPO)를 표로 훑기 — 외부평가 여부·기관, 증권신고서 유무, 등급, 추출 여부. 추출은 하지 않음. 사용법 /dart-valuation-scan <bgn YYYYMMDD> <end YYYYMMDD> [유형]
argument-hint: <bgn_de> <end_de> [합병|분할|영업양수|주식교환|IPO]
---

# /dart-valuation-scan $ARGUMENTS

인자: 시작일·종료일(YYYYMMDD), 선택으로 유형(쉼표로 여럿: 합병, 분할, 분할합병, 영업양수, 주식교환, IPO, 유상증자).
**추출(/dart-valuation)은 하지 않는다.** 목록과 외부평가 5행 중 2행(여부·기관)만 채운다.

## 순서
1. `search_valuation_disclosures(bgn_de, end_de, kinds=<유형 또는 생략>)`. has_more면 next_offset으로 끝까지 받는다.
   (6개월이면 처음엔 API 약 50회로 느리다. 끝난 구간은 data/lists/에 저장돼 다음 실행부터는 빠르다.)
2. summary 건(주요사항보고서)마다 `search_in_disclosure(body_rcept_no, "외부평가기관의 명칭", context_chars=400, max_results=1)` 한 번으로
   "외부평가 여부"(예/아니오/미해당)·"외부평가기관의 명칭"·"회사와의 관계"를 읽는다. 매치가 없으면
   `search_in_disclosure(body_rcept_no, "외부평가", context_chars=300, max_results=1)`. 그래도 없으면 "원문 확인 불가".
   full 건(증권신고서)은 `search_in_disclosure(body_rcept_no, "외부평가기관", context_chars=200, max_results=2)`로 기관명만.
   IPO는 기관 칸에 대표주관회사(`"대표주관회사"` 검색 1회)를 적는다.
3. `reports/valuations/<rcept_no>.json`이 있는 건(rcept_no·original_rcept_no·supersedes 중 하나라도)은 ✓.
4. 건수가 많으면(50건 초과) 2단계는 최신순 50건만 하고 나머지는 "미확인"으로 두고 그 사실을 적는다.

## 출력 (채팅 + `reports/valuations/_scan_<bgn>_<end>.md`)

```
# 가치평가 공시 스캔 <bgn>–<end> [유형]
> search_valuation_disclosures: 거래 N건 (유형/등급별 counts), API 페이지 M회

| # | 접수일 | 회사 | 시장 | 거래 | 상대방(관계) | 외부평가 | 평가기관 | 증권신고서 | 등급 | rcept_no | 추출 |
|---|---|---|---|---|---|---|---|---|---|---|---|
```
- 증권신고서 칸: summary 건이면 related_rcept_nos의 증권신고서 rcept_no(없으면 "없음"), full 건이면 "본건".
- 외부평가 칸은 원문 그대로(예/아니오/미해당). 면제 사유가 "발행주식총수 소유 … 신주 미발행"이면 "미해당(100% 자회사)"처럼 짧게.
- 끝에 MCP 툴 호출 횟수, 읽은 글자 수(context 합).
