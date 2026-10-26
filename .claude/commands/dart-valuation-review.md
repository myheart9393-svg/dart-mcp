---
description: /dart-valuation이 만든 가치평가 사례 JSON을 독립 서브에이전트로 검토(cite 실재·가중치·재계산·주체 혼입·단위). 사용법 /dart-valuation-review <reports/valuations/rcept_no.json>
argument-hint: <reports/valuations/<rcept_no>.json>
---

# /dart-valuation-review $ARGUMENTS

`$ARGUMENTS`는 사례 JSON 경로다. `/dart-review`와 같은 방식: 이 커맨드를 받은 쪽(작성자)은 **직접 리뷰하지 않는다.**
Agent 툴(subagent_type `general-purpose`)로 리뷰어를 띄우고 prompt에는 아래 한 단락**만** 넣는다.

```
너는 DART 가치평가 사례 JSON의 독립 리뷰어다. 프로젝트 루트의 .claude/commands/dart-valuation-review.md 에서
"## 리뷰어 지침" 절을 읽고 그대로 수행하라. 리뷰 대상: <JSON 경로>.
dart MCP 툴(get_disclosure_section, search_in_disclosure, find_tables 등)과 Bash(uv run python ...)를 써도 된다.
끝나면 리뷰 파일 경로, 항목별 PASS/FAIL, MCP 툴 호출 횟수(툴별), 읽은 글자 수를 짧게 답하라.
```

리뷰어가 끝나면 작성자는 `<rcept_no>.review.md`의 FAIL을 하나씩 JSON·md에 반영하고(리뷰가 틀렸으면 이유를 적고 고치지 않는다),
`validate`를 다시 돌린 뒤 md 끝에 `## 리뷰 반영 내역`을 붙인다. 리뷰는 1회로 끝낸다.

---

## 리뷰어 지침

너는 추출 과정을 모른다. JSON·md 파일과 원문(dart MCP 또는 캐시)만으로 판정한다. JSON을 고치지 말고 리뷰 파일만 쓴다.
원문을 통째로 읽지 않는다: cite 위치 부근(±1,500자)만 읽는다.

### 0. 준비
- `uv run python -m dart_mcp.valuation validate <JSON>` → 스키마 위반이 있으면 그 자체로 a 항목 FAIL.
- MCP 툴에 `find_tables`가 없으면(옛 서버) Bash로 `uv run python -c "from dart_mcp import server; print(server.find_tables(...))"`를
  쓰고 리뷰 파일에 "MCP 대신 직접 호출"이라고 적는다.

### a. cite 실재 (무작위 8개)
- `uv run python -m dart_mcp.valuation verify-cites <JSON> --sample 8` (seed는 파일 크기, 재현 가능).
  `missing_cite`가 비어 있지 않으면 FAIL(값이 있는데 cite가 없다).
- `ok=false`인 항목은 직접 `get_disclosure_section(rcept_no, section_id, offset=<cite.offset-1500>, max_chars=3000)`으로 확인해
  ① 숫자가 다른 표기로 있을 뿐인지(PASS로 정정) ② 정말 없는지(FAIL) 판정한다.
- ok=true 중 2개를 골라 숫자의 **의미**도 맞는지 본다(예: 그 8.1543%가 정말 그 subject·target의 WACC인지, 같은 줄의 다른 회사 값이 아닌지).

### b. 가중치
- valuations 중 method="본질가치"인 원소: weights가 asset:income = 1:1.5(합 2.5) 또는 0.4:0.6(합 1)이어야 한다.
  다른 값이면 원문(weights.basis와 cite 부근)을 확인해 원문이 그렇게 적었는지 본다. weights가 있는데 method가 본질가치가 아니면 확인.

### c. 재계산 (본질가치 건)
- 본질가치 = (자산가치×w_asset + 수익가치×w_income) / (w_asset+w_income)를 asset_value.per_share·dcf 결과(또는 같은 주체·대상의
  수익가치 원소)로 다시 계산해 result.value와 비교한다. 원 단위 반올림 차이(±1)는 일치. conclusion.price_per_share의 해당 회사 값과도 비교.
- 합병비율이 있으면 소멸회사 가액 / 존속회사 가액을 계산해 ratio와 소수 넷째 자리까지 비교한다.
- 계산할 재료가 null이면 "검산 불가"(FAIL 아님).

### d. 주체 혼입
- valuations 원소마다 subject·target·role이 원문 표의 캡션·소제목·주변 서술과 맞는지 cite 부근으로 확인한다.
- 같은 원소 안의 숫자들 cite가 서로 다른 주체의 표·구간(예: 존속회사 재무자문사 구간과 외부평가기관 구간)에 흩어져 있으면 FAIL.
- 같은 문서에 같은 변수(WACC 등)가 여러 값으로 나오는데 JSON에 하나만 있거나 한 원소에 섞였으면 FAIL.
  `search_in_disclosure(rcept_no, "WACC")`·`"가중평균자본비용"`으로 값 목록을 확인한다.

### e. 단위
- 각 숫자의 unit이 원문 단위 행·표기와 맞는지(원/백만원/%/배). 같은 원소에서 result.unit과 range 단위가 같은지.
  %인 값이 0–1 소수로(0.081543) 들어갔거나 백만원 값이 원으로 적혔으면 FAIL. md 표의 단위 표기도 JSON과 같은지.

### 리뷰 파일
`reports/valuations/<rcept_no>.review.md`:

```
# 리뷰: <rcept_no>.json
> 리뷰일 <오늘> / 리뷰어: 독립 서브에이전트 / 스키마 valid: <true/false>

## 요약
| 항목 | 결과 | FAIL 수 |
|---|---|---|
| a. cite 실재(8개) | PASS/FAIL | n |
| b. 가중치 | … | … |
| c. 재계산 | … | … |
| d. 주체 혼입 | … | … |
| e. 단위 | … | … |

## a. cite 실재
| # | JSON 경로 | 값 | cite | 판정 | 비고 |
## b–e
(FAIL마다: JSON 경로 / 문제 / 원문 근거(section_id, offset) / 수정 제안)
## 리뷰어 툴 사용
(MCP 툴별 호출 횟수, 직접 호출 여부, 읽은 글자 수)
```
