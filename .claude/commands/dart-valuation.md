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
- **목표자본구조**: D/E는 `target_de`, D/(D+E) 구성비율은 `target_dv`. 원문 표가 "부채비율"이라 적어도 "자기자본비율"과 합이 100%면
  D/V다(알에프텍 2026 실측). 원문 라벨이 아니라 정의로 고른다.
  라벨끼리 엇갈리면(서술은 "D/E", WACC 표는 "타인자본비율") **Re-levered β 산식에 들어간 값**으로 정한다:
  βl = βu×(1+(1−t)×x)가 맞으면 x는 D/E(애드포러스 2025 리뷰: 30.18%를 표는 D/V로 적었지만 β·WACC 검산은 D/E). note에 엇갈림을 적는다.
- **범위(`R(lo, hi)`)는 숫자 크기 순서**: min ≤ max. 원문이 "29.83% ~ 11.74%"처럼 큰 값을 먼저 써도 `R(11.74, 29.83)`.
  어느 끝이 하단 공모가에 대응하는지는 note에 적는다. `validate`가 min > max를 오류로 잡는다(배치 1차에서 IPO 15건 발생).
- **자산가치 `adjustments`는 원문 "조정항목(a − b)" 합계 한 값**(가산항목 한 줄이 아니다). 괄호 "(81,583,335)"는 음수:
  `N("(81,583,335)", sid, off, "원", value=-81583335)`. 저장 전 equity_book + adjustments = total을 확인하고, 원문 표 자체가 안 맞으면
  값은 원문대로 두고 note에 적는다(`validate`가 경고로 잡는다). 2026-10 배치 리뷰 실측: 부호 누락 2건, 가산항목만 넣은 1건.
- **valuations[].purpose 필수**: 합병가액 · 분할·교환비율 · 양수도가액 · 공모가 · 공정가치평가(RCPS·파생상품 등 회계용) · 손상검사 · 기타.
  같은 문서라도 목적이 다르면 그대로 적는다(예: IPO 신고서의 RCPS 공정가치 평가 = 공정가치평가). 조회 기본값은 공정가치평가·손상검사를 뺀다.

## (0) 작성 도구 — cite는 손으로 적지 않는다
- JSON은 `dart_mcp.casebuild`로 만든다(작업 폴더의 builder 스크립트, 커밋하지 않음):
  `B.RCEPT = "<body_rcept_no>"`, 숫자는 `N("<원문 표기>", "<section_id>", <그 표의 offset>, "<단위>")`, 범위는 `R(lo, hi)`,
  `company`는 `B.company(corp_code, name, market)`(induty_code를 기업개황에서 채움 — 원문 cite 없는 조회용 필드),
  원소는 `val(subject, target, role, method, purpose=..., ...)`, 문자 필드 cite는 `C(section_id, "<원문 구절>", offset)`.
  N은 offset부터 4,000자 안에서 원문 표기를 **앞으로 먼저** 찾아 실제 위치를 cite로 쓰고, 없으면 예외를 낸다(원문에 없는 숫자 방지).
  anchor는 **그 주체의 표 offset**을 준다(바로 앞 다른 주체 표의 같은 숫자를 잡지 않게).
- 툴 호출은 MCP 툴을 쓰되, 새 툴(find_tables·search_valuation_disclosures)이 툴 목록에 없으면(서버 재연결 전) 모든 dart 호출을
  `uv run python -m dart_mcp.casebuild call --log <log> --tag <rcept_no> <툴> '<json>'`로 하고 notes에 "MCP 대신 직접 호출"을 적는다.
  큰 섹션 키워드 위치는 `... casebuild grep --log <log> --tag <rcept_no> <rcept_no> <section_id> '<정규식>' 150 8`(섹션 기준 offset).
  끝나면 `casebuild usage --log <log> --tag <rcept_no>`로 호출 수·읽은 글자 수, `casebuild.citations_from_log(...)`로 citations를 채운다.

## (a) 등급·짝 확인
1. `search_valuation_disclosures(bgn_de=<rcept_no 앞 8자리 - 150일>, end_de=<rcept_no 앞 8자리 + 30일, 오늘을 넘지 않게>,
   listed_only=False)`에서 이 rcept_no가 든 거래(rcept_no·supersedes·original_rcept_no 중 하나가 일치)를 찾는다.
   - `source_grade`, `body_rcept_no`(본문을 읽을 번호), `original_rcept_no`, `related_rcept_nos`를 적어 둔다.
   - 못 찾으면 `get_disclosure_outline`의 문서명으로 판단한다(증권신고서 → full, 주요사항보고서 → summary).
   - 증권신고서(지분증권)인데 deal_type이 rights_offering이면 IPO일 수 있다(corp_cls는 조회 시점 상태). 본문에 "희망공모가액"·"상장예비심사"가
     있으면 IPO로 뽑고, 구주주·주주배정 유상증자면 사례 대상이 아니므로 추출하지 않고 "유상증자: 대상 아님"으로 끝낸다.
     SPAC(기업인수목적회사) 상장 공모도 평가가 없어 대상이 아니다.
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
  이어서 `... valuation verify-cites <json> --sample 500`(전수)으로 모든 숫자가 cite 위치에 있는지 확인한다. md는 `... valuation md <json>`.
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
`/dart-valuation-batch` 안에서 부를 때는 리뷰를 돌리지 않는다(배치가 끝난 뒤 무작위 20%만). 단독 실행이면
작성 후 `/dart-valuation-review reports/valuations/<rcept_no>.json`을 1회 돌리고(서브에이전트), FAIL을 반영한 뒤
md 맨 끝에 `## 리뷰 반영 내역` 표(`| 리뷰 항목 | 위치 | 수정 전 | 수정 후 / 미반영 사유 |`)를 붙인다. 리뷰는 1회로 끝낸다.
채팅에는 valuations 요약, 리뷰 PASS/FAIL, MCP 툴 호출 횟수와 읽은 글자 수(작성/리뷰 분리)를 보고한다.
