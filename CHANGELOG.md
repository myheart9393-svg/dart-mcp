# Changelog

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
