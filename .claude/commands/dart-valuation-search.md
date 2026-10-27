---
description: 축적한 가치평가 사례(reports/valuations/*.json)를 조건으로 걸러 표와 거래 단위 분포(WACC·g·멀티플)로. 사용법 /dart-valuation-search <조건 자연어>
argument-hint: <조건 예: "2026년 합병 DCF">
---

# /dart-valuation-search $ARGUMENTS

`$ARGUMENTS`는 자연어 조건이다(기간·거래유형·평가방법·평가 목적·업종·평가기관·변수). 원문이나 API는 다시 읽지 않는다. **사례 JSON만** 쓴다.

## 순서
1. 조건을 `stats` 필터로 옮긴다. 옮긴 규칙을 출력 맨 위에 한 줄로 적는다.
   ```
   uv run python -m dart_mcp.valuation stats reports/valuations [--from YYYY-MM-DD] [--to YYYY-MM-DD]
       [--deal-type merger,split,split_merger,business_transfer,share_exchange,ipo] [--method DCF,본질가치,…]
       [--purpose 합병가액,공모가,…|all] [--firm 이촌] [--regime 기준시가|"공정가액(2026.12.9 개정)"|IPO|none]
       [--industry 26,21 (KSIC 코드 접두, 2자리=중분류)]
   ```
   - 기간 기준일은 이사회 결의일, 없으면 접수일(rcept_no 앞 8자리). "2026년" → `--from 2026-01-01 --to 2026-12-31`, "하반기" → 07-01–12-31.
   - "합병" → `--deal-type merger`(분할합병 포함하려면 split_merger도). "IPO"·"공모" → `ipo`.
   - "DCF" → `--method DCF`. 본질가치 원소의 수익가치가 DCF인 경우는 같은 주체의 DCF 원소로 이미 따로 있다.
   - **평가 목적 기본값은 거래가액 평가만**(공정가치평가·손상검사 제외). "RCPS 공정가치"·"손상검사"를 말하거나 "전부"면 `--purpose 공정가치평가` / `all`.
   - "WACC"·"g"·"멀티플" 같은 변수 이름은 **행을 거르지 않고** 보여줄 열·분포 대상만 정한다. 값이 null인 행(summary 등급 등)도 표에
     "원문 없음"으로 남긴다. "WACC가 있는 것만"처럼 명시하면 그때 뺀다.
   - **합병가액 체계(regime)**: 2026.12.9 이후 이사회 결의분부터 기준시가 → 공정가액 체계다. 합병·분할 등에서 두 체계가 섞이면
     결과에 `warning`이 온다 → `--regime`으로 나눠 따로 돌리고 표·분포도 체계별로 낸다. 한 분포로 합치지 않는다.
   - 업종은 `--industry <KSIC 접두>`. "반도체·전자" → 26, "제약·바이오" → 21(의약품)·70(연구개발업), "소프트웨어" → 582(58 출판업 안의
     소프트웨어 개발·공급업), "기계" → 29. 옮긴 접두를 맨 위 한 줄에 적는다. 결과의 `industries`(중분류 라벨별 거래 수)를 요약에 쓰고,
     표에는 `industry` 열(예: "26 전자부품·컴퓨터·영상·음향·통신장비")을 넣는다. induty_code가 없는 사례는 "(없음)".
2. 결과 JSON의 `rows`를 표로:

```
| 회사 | 업종 | 거래 | 이사회 | 평가기관 | 주체(역할) | 대상 | 목적 | 방법 | WACC(%) | g(%) | 멀티플 | 결과 | 등급 | rcept_no |
```
   null은 "–"(변수 열은 "원문 없음"). 결과는 result + result_unit 그대로(환산하지 않는다).
3. **분포는 거래 단위**(`variables`): 한 거래의 값이 여럿이면 외부평가기관 값이 대표값(없으면 그 거래 값들의 중앙값).
   변수마다 "**N건 거래, M개 값**"을 먼저 쓰고 중앙값·1사분위–3사분위·최소–최대(en dash). 거래별 대표값(`per_deal`)도 작은 표로.
   멀티플은 종류별(`multiple:PER` 등)로 따로.
4. 평가기관별 거래 수(`firms`). IPO가 있으면 `ipo`: 적용 멀티플 종류 분포, 종류별 멀티플 중앙값·사분위, 할인율 하단(min)·상단(max) 분포.
5. **거래 수가 10건 미만이면 "통계적 의미 제한: 거래 n건"**을 요약 첫 줄에 쓴다.
6. 조건에 맞는 사례가 없으면 그렇게 말하고, `/dart-valuation-scan`으로 후보를 찾아 `/dart-valuation`(또는 `-batch`)으로 추출하라고 안내한다.
