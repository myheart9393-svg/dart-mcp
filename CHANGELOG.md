# Changelog

## v1.5.0 (2026-10-27)

사례 DB 정합성(회계 항등식)과 거래 상태. 스키마 변경: `deal.status`·`status_source`·`status_checked`, 최상위 `source_inconsistent[]`.

- **validate 항등식 검사**(`identity_checks`, 경고): a β 재조정(D/E↔D/V 혼동 의심 표시, 동종기업별 세율 재조정 범위 허용), b Ke, c WACC(D/V는 target_dv 우선),
  d 본질가치(상증법 80% 하한), e 기준시가(입력 필드가 없어 skip), f 합병·교환비율(분할합병 skip), g 자산가치 합계(기존 경고를 옮김).
  허용오차: 금리·β는 max(상대 0.5%, 입력 표시 자릿수 반올림 전파), 금액은 표시 자릿수 전파만. `validate <dir>`가 항목별 pass/warn/skip/source_inconsistent를 센다.
- **경고 처리(161건)**: 처음 18건 → 추출 오류 2(우리금융지주 MVS 조정 순자산 total 2행), 원문 자체 불일치 10(표 합계 4·표기와 산식 값 3·원문 추가 조정/항목 3,
  `source_inconsistent`로 표시), 허용오차·규칙 6(동종기업별 세율 2·상증법 하한 2·D/V 우선 1·분할합병 1)+ 입력 반올림 전파 1. 처리 후 경고 0.
- **거래 상태**: `valuation status <dir>` — 같은 회사의 이후 list.json으로 완료(증권발행실적보고서(합병등)·합병등종료보고서)·철회(…결정 철회, 같은 유형 철회신고서) 판정.
  97건: 완료 77·철회·중단 10·진행 10·미확인 0(2026-10-27). stats에 `statuses`, rows에 status.
- **업종 대분류 묶음**: `--industry 제조업|정보통신|금융보험|도소매|…` 또는 대분류 문자(C). `industry.matches`.
- **템플릿**: 원문 산술 불일치는 값은 원문대로 + `source_inconsistent`, MVS의 total은 조정 순자산, 상증법은 basis에 '상증법'·'80%'.

## v1.4.0 (2026-10-27)

업종 코드와 2024–2025 합병·분할·교환 사례.

- **industry.py (신규)** + `ksic.json`(KSIC 10차 대분류·중분류 이름): 사례 induty_code를 기업개황(30일 캐시)으로 채우는 `fill`, 중분류 분포 `dist`.
  조회 실패는 null + notes에 사유. 기존 89건 → 89건 채움(엘리스그룹은 사례에 corp_code가 없어 배치 큐 값으로 보충).
- **casebuild.company()**, **batch record ok**가 corp_code·induty_code를 자동으로 채운다. `batch plan --kinds`(지분증권 제외 시 본문 판별 다운로드 없음).
- **stats**: `--industry <KSIC 접두>`, 결과에 `industries`(중분류 라벨별 거래 수), rows에 `industry` 라벨.
- **validate 경고 추가**: 자산가치 자본총계 + 조정항목 ≠ 조정 순자산(분할 제외).
- **템플릿**: D/E·D/V 라벨이 엇갈리면 Re-levered β 산식으로 판정, 자산가치 adjustments는 원문 "조정항목(a−b)" 합계·괄호는 음수.
- **사례**: 2024-01-01–2025-12-31 합병·분할·분할합병·주식교환 full 등급 75건 → 추출 72건·실패 0, 제외 3(기존 사례). 시험 10건 후 나머지 62건.
  무작위 20%(15건) 리뷰 13 PASS·2 FAIL(목표자본구조 D/V→D/E 1, 조정항목 합계 1) 반영. 반복 유형(자산가치 합계) 전수 검산으로 부호 오류 2건(3행) 추가 수정,
  원문 표 자체 불일치 3건은 note. 전체 161건 validate 오류 0·경고 4.

### v1.3.0 이후 먼저 반영(b5f41ec): 가치평가 사례 DB 운영

- **validate 분포 경고**: `distribution_warnings` — WACC 0–30% 밖, g ≥ WACC(같은 원소), g > 5%, 적용 멀티플(relative·ipo) ≤ 0,
  할인율 0–70% 밖이면 `warnings[]`(FAIL 아님, 종료코드 영향 없음). `validate <dir>`로 사례 전체 검사. 89건: 오류 0·경고 0
  (실측 범위 WACC 5.05–17.59%, g 0–1.0%, 멀티플 1.8–47.45, 할인율 7.65–57.48%).
- **stats `--regime`**: 체계별 거래 수(`regimes`), 기준시가·공정가액(2026.12.9 개정) 체계가 섞이면 `warning`.
- **문서**: README 운영 절 "가치평가 사례 DB 갱신 (월초)"(scan → batch → 20% 리뷰 → validate → 커밋, regime 주의),
  `docs/valuation_usage.md`(회계사용: 조회 예시 5개, 인용 표기법, 한계). 사례 89건 중 induty_code는 4건에만 있어 업종 조회는 아직 불가.

## v1.3.0 (2026-10-26)

가치평가 사례 DB 채우기.

- **스키마**: `valuations[].purpose`(필수), `dcf.target_dv`(D/(D+E)), `income_value`, `role="회사"`. `validate`가 범위 min > max도 오류로 잡는다.
- **valuation.py**: `stats` CLI(거래 단위 대표값 — 외부평가기관 값 우선, 없으면 중앙값 — "N건 거래, M개 값", 사분위, 평가기관별 거래 수,
  IPO 멀티플·할인율 분포), `filter_rows`(기본은 거래가액 평가만), `equity_kind`(증권신고서(지분증권) IPO/유상증자를 본문으로 판정:
  corp_cls는 조회 시점이라 올해 상장한 IPO는 K·Y, 상장폐지 회사의 유상증자는 E로 온다), SPAC 제외, 유상증자는 kinds로 명시할 때만.
  `EXTRACTOR_VERSION` 1.1. md 렌더러: 목적 열, 범위 양 끝 cite, 단위 중복("12.85x배")·None 표기 수정.
- **casebuild.py (신규)**: 사례 JSON 작성 도우미(N/R/C/val — cite를 원문에서 앞으로 먼저 찾고 없으면 예외), 툴 호출 기록 CLI(`call`·`grep`·`usage`).
- **batch.py (신규)**: `/dart-valuation-batch`의 큐(plan)·기록(record)·보고(report).
- **커맨드**: `/dart-valuation-batch` 신규. `/dart-valuation`에 purpose·casebuild·범위 순서·D/E vs D/V 규칙, `/dart-valuation-search`에 목적 필터·거래 단위 통계.
- **사례**: 2026-01-01–10-26 full 등급 166건 → 추출 86건 성공·실패 0, 제외 80건(유상증자 58·SPAC 15·판단 불가 4·기존 2·해외 직접공모 1).
  무작위 20%(18건) 독립 리뷰 18건 PASS. 배치 후 정리: IPO 할인율 범위 역순 15건(값·cite 그대로 순서만), D/V 1건.

## v1.2.0 (2026-10-26)

가치평가 사례 추출. 캐시 버전 7 → 8(옛 캐시는 저장된 ZIP으로 자동 재구성).

- **valuation.py (신규)**: 합병·분할·분할합병·영업양수도·주식교환·IPO 공시 분류(`source_grade` full=증권신고서 / summary=주요사항보고서),
  원본·정정본 묶기(`original_rcept_no`·`body_rcept_no`), B↔C 짝(`related_rcept_nos`), 3개월 구간·전 페이지 스캔.
  사례 JSON 검증(`validate`)·cite 실재 확인(`verify-cites`)·md 렌더(`md`)·조회 표(`table`) CLI.
- **valuation_schema.json (신규)** + `docs/valuation_schema.md`: 숫자는 전부 `{value, unit, text, cite}`, 원문에 없으면 null.
- **tables.py (신규)**: 섹션 Markdown에서 표 블록 + 한 칸짜리 캡션·단위 표를 붙여 찾기.
- **server.py**: `search_disclosures`에 `page_no`(응답 `total_page`·`has_more`, 한 페이지 ≤100), 새 툴 `search_valuation_disclosures`·`find_tables`,
  끝난 구간 list.json 페이지 캐시 `data/lists/`. `_sort_key`가 `.hN` id 처리, `.hN`은 depth≥3에서만 목차에 보임.
- **document.py**: TITLE 없는 5만 자 이상 섹션에 줄머리('가.'·'(1)'·단독 '[캡션]') 휴리스틱 소제목 `.hN`(kind="heading").
  본문 파일·정기보고서가 아닐 때만(사업보고서·감사보고서 첨부는 그대로). parser_regression: 93건 중 4건(증권신고서 2·주요사항보고서 2)에 `.hN`만 추가, 기존 섹션 변경 0.
- **scripts/parser_regression.py**: `build_outline`에 `main=(file_id=="main")`을 넘겨 cache.store와 같은 결과로 비교.
- **커맨드**: `/dart-valuation`, `/dart-valuation-review`, `/dart-valuation-scan`, `/dart-valuation-search`.
- **reports/valuations**: 알테오젠 합병(full), 제논 IPO(full), 우성 합병(summary) 사례와 리뷰, 2026-07–10 스캔.
- 의존성: `jsonschema` 명시.

## v1.1.0 (2026-10-23)

v1.0.0 이후 변경. 캐시 버전 3 → 7 (옛 캐시는 저장된 ZIP으로 자동 재구성, API 호출 없음).

- **document.py**: 원문 꺾쇠 이스케이프(`<연결기업의 연혁>`)·속성값 안 따옴표 `&quot;` 전처리로 트리 붕괴·뒷부분 누락 수정(GS건설·두산에너빌리티), `<SECTION-1`·`<TITLE` 수 비교로 누락 검출(`parse_warnings`), utf-8 우선 디코딩, 표 머리글·ROWSPAN 수정, 직계 TITLE 제목, 셀·TITLE 안 P·DIV·LI·BR 경계 공백.
- **cache.py**: 파일별 `parse_warnings` 저장, CACHE_VERSION 7.
- **periodic.py**: 정정 종류(기재정정/첨부정정/첨부추가)·`late_corrections`(최신 사업보고서 최초 제출일 기준)·`original_rcept_no`, 본문 `body_rcept_no`와 감사보고서 `attachment_rcept_no` 분리.
- **server.py**: outline에 `parse_warnings`, 본문 없는 첨부정정 ZIP은 error + hint(body_rcept_no), `reprt_code=None` 명확한 에러, 재무 툴 `refresh`.
- **financials.py**: 지배주주 기준 평균잔액 ROE·ROA, 자본잠식 flag, 90일 재무 캐시·변경 계정 로그, 결산기 라벨(periods), capex 이름 보강과 `assumed_zero`(현금흐름표에 취득 행 없음 → 0).
- **healthcheck.py (신규)**: LLM 없는 일괄 건전성 검사 a–g(뒷부분 누락·깨진 글자·장 수·missing·reprt_code null·API↔요약재무정보 숫자·감사보고서 첨부) → `reports/healthcheck_<날짜>.md`.
- **scripts/parser_regression.py (신규)**: 캐시 XML 전체를 재변환해 섹션 (id, 제목, 글자 수)을 `data/_baseline`과 비교.
- **슬래시 커맨드**: `[기재정정본]` 머리·정정사유 한 줄·late_corrections 리스크 한 줄, 본문은 body_rcept_no·감사보고서는 attachment_rcept_no, `parse_warnings` 표기, 자본잠식 표기.
- **문서**: README 알려진 한계·운영(정기 점검 절차, healthcheck 항목), CLAUDE.md parser_regression 커밋 규칙.
- **reports**: GS건설 정정본 예시, healthcheck 1·2차 60개사 이력.

## v1.0.0

최초 릴리스: MCP 툴 8개, 슬래시 커맨드 6개, 예시 보고서.
