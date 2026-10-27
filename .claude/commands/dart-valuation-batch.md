---
description: 기간 안의 가치평가 공시를 일괄 추출(/dart-valuation을 건마다 서브에이전트로). 실패는 기록하고 멈추지 않음, 끝나고 무작위 20% 리뷰. 사용법 /dart-valuation-batch <bgn> <end> [--grade full] [--limit N]
argument-hint: <bgn_de> <end_de> [--grade full|summary] [--limit N]
---

# /dart-valuation-batch $ARGUMENTS

## 1. 계획 (결정적, 코드)
```
uv run python -m dart_mcp.batch plan <bgn> <end> --grade full [--limit N] [--kinds merger,split,split_merger,share_exchange] --state reports/valuations/_batch_<오늘>.json
```
- `--kinds`로 거래 유형을 고른다(지분증권 IPO·유상증자를 빼면 본문 판별 다운로드도 없다). 생략하면 전부.
- search_valuation_disclosures 결과에서 등급이 맞는 거래만, 접수일 오래된 순. 이미 `reports/valuations/`에 있는 거래는 `skip:existing`.
- 상장사 증권신고서(지분증권)은 본문을 받아 IPO/유상증자를 가린다(`equity_kind`): 유상증자 `skip:rights_offering`, 판단 불가 `skip:equity_unknown`.
  SPAC 상장 공모는 `skip:spac`.
- `--limit N`이면 todo N건, 나머지는 queued. 이어서 돌릴 때는 같은 state로 queued를 todo로 바꿔(`batch record … todo`) 진행한다.
  plan을 다시 만들면 이미 추출한 건은 skip:existing이 된다.

## 2. 추출 (건마다 서브에이전트, 동시에 최대 5개)
todo 건마다 Agent(subagent_type `general-purpose`)를 띄우고 prompt는 아래 한 단락만:

```
너는 DART 가치평가 사례 추출기다. 프로젝트 루트의 .claude/commands/dart-valuation.md를 읽고 /dart-valuation <body_rcept_no>를 수행하라.
배치 실행이므로 리뷰는 돌리지 않는다. 툴 호출은 전부 `uv run python -m dart_mcp.casebuild call --log data/valuation_logs/<body_rcept_no>.jsonl --tag <body_rcept_no> ...`로 하고
(MCP 대신 직접 호출), builder 스크립트는 data/valuation_logs/build_<body_rcept_no>.py에 둔다.
끝나면 한 줄 JSON으로만 답하라: {"rcept_no":..., "status":"ok|fail|skip", "reason":"(fail·skip이면 사유: schema_invalid|no_body|no_valuation_section|rights_offering|기타 설명)", "calls":N, "chars":N}
(calls·chars는 casebuild usage 결과).
```

- 서브에이전트가 끝나면 오케스트레이터는 `uv run python -m dart_mcp.batch record --state <state> <rcept_no> <status> --reason … --calls … --chars … --seconds <duration_ms/1000>`.
  `record … ok`는 사례 JSON의 `company.corp_code`(비면 큐 값)와 `induty_code`(비면 기업개황 조회)를 채운다 — 실패 사유는 notes에.
  **실패해도 멈추지 않는다.** 응답이 JSON이 아니거나 JSON 파일이 없거나 `validate`가 실패하면 fail(`schema_invalid`)로 기록한다.
- 오케스트레이터는 각 결과 JSON에 대해 `valuation validate`와 `verify-cites --sample 500`을 직접 한 번 더 돌린다(서브에이전트 보고를 믿지 않는다).
  verify가 실패한 건은 fail(`cite_mismatch`).

## 3. 리뷰 (끝난 뒤 무작위 20%)
- ok 건 중 `ceil(0.2 × n)`건을 `python -c "import random; random.seed(<state 파일 크기>); …"`로 뽑아 `/dart-valuation-review`를 서브에이전트로 1회씩.
- 결과를 `batch record … ok --review PASS|FAIL(<항목>)`로 기록.
- **같은 FAIL 유형이 2건 이상**이면 `/dart-valuation` 템플릿(.claude/commands/dart-valuation.md)을 고치고, 그 유형이 의심되는 건을 재추출한다
  (리뷰한 건 + 같은 deal_type 중 같은 패턴). 고친 내용은 `_batch_<날짜>.md` 끝 "템플릿 수정"에 적는다.

## 4. 보고
`uv run python -m dart_mcp.batch report --state <state>` → `_batch_<날짜>.md`(상태·실패 사유 분포·건별 호출/글자/초·리뷰).
채팅에는 성공/실패/제외 건수, 실패 사유 분포, 합계·건당 평균 호출·글자·소요 시간, 리뷰 PASS/FAIL을 보고한다.
