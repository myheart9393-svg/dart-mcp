---
description: 축적한 가치평가 사례(reports/valuations/*.json)를 조건으로 걸러 표와 분포 요약(WACC·g·멀티플)으로. 사용법 /dart-valuation-search <조건 자연어>
argument-hint: <조건 예: "2026년 하반기 DCF WACC">
---

# /dart-valuation-search $ARGUMENTS

`$ARGUMENTS`는 자연어 조건이다(기간·거래유형·평가방법·업종·평가기관·변수). 원문이나 API는 다시 읽지 않는다. **사례 JSON만** 쓴다.

## 순서
1. `uv run python -m dart_mcp.valuation table reports/valuations` → 평가 주체·대상 단위로 펼친 행 목록(JSON).
   열: rcept_no, company, induty_code, deal_type, board_date, regime, firm(외부평가기관), source_grade, subject, target, role,
   method, wacc, g, multiple_type, multiple, result, result_unit.
2. 조건을 행 필터로 옮긴다. 옮긴 규칙을 출력 맨 위에 한 줄로 적는다. 예:
   - "2026년 하반기" → board_date 2026-07-01–2026-12-31 (board_date가 null이면 rcept_no 앞 8자리 접수일로 대신하고 그렇다고 적는다)
   - "DCF" → method == "DCF" (본질가치 원소의 수익가치가 DCF면 그 원소도 포함하고 표시)
   - "WACC"·"g"·"멀티플" 같은 변수 이름은 **행을 거르지 않고** 보여줄 열·분포 요약 대상만 정한다. 값이 null인 행(summary 등급 등)도
     표에 남겨 "원문 없음"으로 보이고, 분포 요약에서만 뺀다. "WACC가 있는 것만"처럼 명시하면 그때 null 행을 뺀다.
   - 업종은 induty_code 앞 2–3자리(KSIC), 평가기관은 firm 또는 subject 부분일치
3. 걸러진 행을 표로:

```
| 회사 | 거래 | 이사회 | 평가기관 | 주체(역할) | 대상 | 방법 | WACC(%) | g(%) | 멀티플 | 결과 | 등급 | rcept_no |
```
   null은 "–". 결과는 result + result_unit 그대로(환산하지 않는다).
4. 분포 요약(값이 있는 행만): WACC·g·멀티플(종류별) 각각 n, 중앙값, 최소–최대(범위는 en dash). 사례가 같은 rcept_no에서 여럿 나오면
   그 사실을 적는다(같은 거래의 주체별 값은 독립 표본이 아니다).
5. **사례(고유 rcept_no)가 10개 미만이면 "통계적 의미 제한: 사례 n건"**을 요약 첫 줄에 쓴다.
6. 조건에 맞는 사례가 없으면 그렇게 말하고, `/dart-valuation-scan`으로 후보를 찾아 `/dart-valuation`으로 추출하라고 안내한다.
