---
description: 기존 가치평가 사례 한 건에 v1.6 필드(β 산정 방식·규모위험 근거·비교회사·수익가치 점 값·거래 단위 상대가치)를 원문에서 보강. 이미 있는 값은 바꾸지 않음. 사용법 /dart-valuation-backfill <rcept_no>
argument-hint: <rcept_no>
---

# /dart-valuation-backfill $ARGUMENTS

`$ARGUMENTS`는 `reports/valuations/<rcept_no>.json`이 있는 사례의 접수번호다. **새 추출이 아니다.** 비어 있는 v1.6 칸만 원문에서 채운다.
보강은 서브에이전트 한 개(general-purpose)로 돌리고, prompt에는 "프로젝트 루트의 .claude/commands/dart-valuation-backfill.md 의
'## 작업자 지침'을 읽고 rcept_no <rcept_no>에 수행하라. 끝나면 지침의 한 줄 JSON으로만 답하라."만 넣는다.
끝나면 오케스트레이터가 `valuation validate <json>`(errors 0)·`verify-cites <json> --sample 500`(실패 0)을 직접 한 번 더 돌리고,
`casedb audit-null reports/valuations --write`로 감사 사유를 갱신한다(보강이 확인한 칸은 다시 감사하지 않는다).
인용 직전에 한 건씩 돌리는 용도다(SPAC 사례 52건은 일괄 보강하지 않았다 — README).

## 작업자 지침

규칙
- **이미 값이 있는 칸은 바꾸지 않는다.** 원문과 다르면 고치지 말고 답의 diffs에만 적는다.
- 원문에 없으면 null + `absent_reasons` {path, field, reason: "원문에 없음", basis: "보강 확인 <오늘>: <근거, section·offset>"}. 채운 값에는 전부 cite.
- 원문 읽기는 전부 `.venv/Scripts/python.exe -m dart_mcp.casebuild call --log data/valuation_logs/backfill_<rcept_no>.jsonl --tag <rcept_no> <툴> '<json>'`
  (uv가 있으면 `uv run python`). 큰 섹션 위치는 `... casebuild grep ...`. 원문 통째로 읽지 않는다 — 각 원소의 기존 cite(dcf.wacc·result) 부근부터.
- md 재생성 금지(리뷰 반영 내역이 지워진다). git 명령 금지.

**빠른 처리(파일럿 실측: β·규모위험·비교회사는 외부평가기관 원소에서만 원문에 나왔다).** role이 "외부평가"가 아닌 DCF 원소(재무자문·회사)는
그 주체 구간에서 `search_in_disclosure` 한 번("베타|Beta|규모|Size|동종|유사|대용")으로 서술이 없음을 확인하면 beta_method·size_premium_basis·peers를
바로 null + "원문에 없음"(basis에 "재무자문 원소: WACC 점 값만 공시")으로 둔다. **다른 주체의 표를 가져오지 않는다**(같은 섹션의 외부평가기관 표를 집는 실수 — 감사 오탐의 주원인).

채울 칸(평가 원소 = purpose가 공정가치평가·손상검사가 아니고 dcf가 있는 valuations[i])
1. `dcf.beta_method` = {adjusted, period, frequency, index, source, cite} — 동종기업 β 표의 주석. 원문에 있는 항목만.
2. `dcf.size_premium_basis` = {text(원문 문구, 예 "한국공인회계사회 Size Premium 5분위 중 2분위"), cite}.
3. `dcf.size_premium`이 null이고 원문에 값이 있으면 채운다(누락). 원문이 미적용을 명시하면 null 유지 + absent_reasons. 값이 0.00%이고 원문이 미적용을 명시하면
   `dcf.size_premium_applied=false`. 원문 라벨이 Firm Specific이어도 근거가 KICPA 규모위험이면 size_premium, **규모와 별도의 고유위험·성장성 가산**은
   `dcf.specific_risk`(note에 원문 라벨·근거).
4. `dcf.peers`가 비어 있으면 그 주체의 동종기업 표에서 회사마다 {name, beta_l, beta_u, de(D/E만 — D/(D+E) 열이면 null + note), tax_rate, note}.
5. method=본질가치 원소의 `income_value`가 null이면 1주당 수익가치 점 값. 범위만 있으면 null + absent_reasons.
6. 사례 단위 `relative_value` = {applied, reason, cite} — 이미 있으면(derived 포함) 바꾸지 않는다.

작성·검증: builder 스크립트 `data/valuation_logs/backfill_build_<rcept_no>.py`에서 `casebuild.N`/`casebuild.C`로 cite를 만든다(offset 손으로 적지 않음).
저장 뒤 `valuation validate`(errors 0)·`verify-cites --sample 500`(실패 0).

답(한 줄 JSON): {"rcept_no", "calls", "chars", "attempted", "filled", "null_with_reason",
"audit_check": [{"path", "audit": "추출 안 함", "actual": "누락이었음(채움)"|"원문에 없음"|"해당 없음"}], "diffs": [{"path", "json", "source", "cite"}], "notes"}
