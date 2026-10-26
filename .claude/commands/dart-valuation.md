---
description: 가치평가 공시 한 건(합병·분할·영업양수도·주식교환·IPO)에서 평가 주체별 방법·가정·결론을 스키마 JSON과 md로 추출. 사용법 /dart-valuation <rcept_no>
argument-hint: <rcept_no>
---

# /dart-valuation $ARGUMENTS

`$ARGUMENTS`는 접수번호(14자리)다. 그 공시의 가치평가 내용을 `src/dart_mcp/valuation_schema.json`에 맞는 사례 JSON으로 뽑는다.
스키마 설명은 `docs/valuation_schema.md`. CLAUDE.md 공통 원칙을 따른다.

## 절대 규칙
- **원문에 없으면 null. 추정하지 않는다.** 계산으로 채우지 않는다(재계산은 리뷰가 검산용으로만 한다).
- 숫자 필드는 전부 `{"value", "unit", "text", "cite": {"section_id", "offset", "file_id"}}`. `text`는 원문 표기 그대로
  ("8.1543%", "261,345"), `unit`은 원문 단위 그대로(원·백만원·억원·%·배·주). **단위를 환산하지 않는다.**
- `cite.offset`은 그 section_id 텍스트 기준 위치다(find_tables의 표 offset, search_in_disclosure의 offset, get_disclosure_section의
  offset+읽은 위치). 표에서 옮긴 값은 표 offset을 쓴다. section_id는 가능하면 SECTION 단위 id("4", "7")를 쓴다
  (`.hN`은 휴리스틱이라 파서가 바뀌면 달라질 수 있다).
- **평가 주체가 다르면 valuations 원소를 나눈다.** 같은 문서에 WACC가 여럿 나오면(예: 존속회사 재무자문사 DCF, 소멸회사 외부평가기관 DCF,
  특별위원회 회의록에 인용된 값) 각각 subject·target·role을 밝혀 따로 넣는다. 회의록·Q&A에서 인용된 값은 원 평가 주체 원소에 넣지 말고,
  원 평가 표에서 같은 값을 찾으면 그 표를 cite한다. 못 찾으면 notes에 "회의록 인용값: …(cite)"로만 남긴다.
- 원문 장문 복사 금지. `opinion_text`·`basis_text`는 300자 이내.

## (a) 등급·짝 확인
1. `search_valuation_disclosures(bgn_de=<rcept_no 앞 8자리 - 150일>, end_de=<rcept_no 앞 8자리 + 30일, 오늘을 넘지 않게>,
   listed_only=False)`에서 이 rcept_no가 든 거래(rcept_no·supersedes·original_rcept_no 중 하나가 일치)를 찾는다.
   - `source_grade`, `body_rcept_no`(본문을 읽을 번호), `original_rcept_no`, `related_rcept_nos`를 적어 둔다.
   - 못 찾으면 `get_disclosure_outline`의 문서명으로 판단한다(증권신고서 → full, 주요사항보고서 → summary).
2. summary인데 related_rcept_nos에 증권신고서가 있으면: 그 증권신고서도 `/dart-valuation`으로 따로 뽑으라고 notes에 적는다
   (이 실행은 요청한 rcept_no만 한다).

## (b) summary(주요사항보고서): 5행 + 결론만
1. `get_disclosure_outline(body_rcept_no)`. 결정 섹션("회사합병 결정"·"영업양수 결정" 등) char_count가 30,000 이하면 통째로 읽는다.
   넘으면 `search_in_disclosure(body_rcept_no, "외부평가기관의 명칭", context_chars=600)` 한 번 + 결론 위치만 offset으로 읽는다.
2. 채우는 것: `external_valuation` 5행(외부평가 여부·근거 및 사유·외부평가기관의 명칭·외부평가 기간·외부평가 의견),
   `deal`(상대방·회사와의 관계·이사회결의일), `conclusion`(합병가액·비율·양수도가액·의견서의 가치 범위),
   본문에 방법별 가액(자산가치·수익가치·본질가치·기준시가)이 있으면 valuations에 subject=외부평가기관(또는 원문이 밝힌 주체)로.
   할인율·g·베타·멀티플은 **본문에 없으면 null**(정상: 평가의견서 첨부가 API ZIP에 없다). notes에 "평가의견서 첨부 미제공(API)"을 적는다.

## (c) full(증권신고서): 표 우선
1. `get_disclosure_outline(body_rcept_no, depth=3)` → 평가 섹션을 제목으로 고른다:
   합병·분할·교환은 "합병 가액 및 그 산출근거"(또는 "분할…"·"교환…가액"), 요약은 "평가 및 신주배정 등",
   IPO는 "인수인의 의견(분석기관의 평가의견)"과 "공모가격 결정방법". `.hN` 소제목("가. 평가결과", "(2) 유사기업 PER 산출" 등)으로
   어느 구간에 무엇이 있는지 본다.
2. `find_tables`로 표부터 꺼낸다(섹션마다, 필요한 패턴만):
   - `"요약|평가결과|산정 결과"` → 결론 표(주체별 가액·비율)
   - `"할인율|WACC|가중평균자본비용|자기자본비용"` → WACC 구성표(rf·MRP·β·규모위험·Kd·세율·목표자본구조)
   - `"민감도"` → 민감도 표, `"유사(기업|회사)|비교기업|베타"` → 유사기업·β 표, `"PER|EV/EBITDA|PBR|PSR"` → 멀티플 표
   - IPO: `"공모가 산정 요약표"`, `"PER 산출"`, `"할인율"`, `"외부평가"`
   표마다 caption·unit을 보고 어느 주체·대상의 것인지 정한다(표가 든 `.hN` 구간 제목도 근거로 쓴다).
3. 표에 없는 값만 `search_in_disclosure(body_rcept_no, q)` (q: 할인율|WACC|영구성장률|베타|EV/EBITDA|PER 중 필요한 것,
   context_chars=200, max_results≤8)로 위치를 찍고 `get_disclosure_section(..., offset=<매치-500>, max_chars≤3000)`으로 그 부근만 읽는다.
4. 외부평가기관 명칭·근거·기간·감사위원회 동의·준수 기준은 "외부평가" 검색 또는 요약 섹션에서.
5. `regime`: 원문이 2026.12.9 시행 개정법을 적용했다고 쓰면 "공정가액(2026.12.9 개정)", 기준시가·본질가치 체계면 "기준시가",
   IPO면 "IPO". 원문으로 판단할 수 없으면 null.

## (d) 출력
- `reports/valuations/<rcept_no>.json` — 사례 JSON. `extracted_at`은 지금 시각(ISO8601, +09:00), `extractor_version`은
  `dart_mcp.valuation.EXTRACTOR_VERSION`. `citations`에 읽은 섹션(rcept_no, file_id, section_id, title, chars_read, how).
- 저장 직후 검증: `uv run python -m dart_mcp.valuation validate reports/valuations/<rcept_no>.json` → valid=false면 고친다.
- `reports/valuations/<rcept_no>.md` — 사람용:

```
# <회사명> <거래 라벨> 가치평가 (rcept_no <rcept_no>, <filing_type>, 등급 <source_grade>)
> 원본 <original_rcept_no> / 짝 공시 <related_rcept_nos> / 이사회 <board_date> / 체계 <regime>

## 1. 거래 개요
(상대방·관계·외부평가 여부·기관·근거 원문·기간 — 표)
## 2. 평가 주체별 방법·가정
| 주체 | 대상 | 역할 | 방법 | 가중 | WACC | g | β(U/L) | 멀티플 | 결과 | 출처 |
(값이 null이면 "원문 없음". 출처는 (section_id, offset))
## 3. 결론
(회사별 주당 가액, 비율, 범위, 의견 요지 — 출처)
## 4. 민감도
(없으면 "원문 없음")
## 부록. 출처
| rcept_no | file_id | section_id | 제목 | 읽은 글자 수 | 방법 |
```

## (e) 리뷰
작성 후 `/dart-valuation-review reports/valuations/<rcept_no>.json`을 1회 돌리고(서브에이전트), FAIL을 반영한 뒤
md 맨 끝에 `## 리뷰 반영 내역` 표(`| 리뷰 항목 | 위치 | 수정 전 | 수정 후 / 미반영 사유 |`)를 붙인다. 리뷰는 1회로 끝낸다.
채팅에는 valuations 요약, 리뷰 PASS/FAIL, MCP 툴 호출 횟수와 읽은 글자 수(작성/리뷰 분리)를 보고한다.
