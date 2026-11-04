# Changelog

## v1.6.4 (2026-11-04)

v1.6.3 이후 운영 결함 방지. 새 공시 추출은 없다. 서버 툴은 바뀌지 않았다(CLI·데이터만).

- **v1.6.3 보고값 정정 — 정정 공시 중복.** batch plan은 창 밖 원본의 [기재정정]·[첨부정정]을 새 거래로 보았다. 그래서 같은 거래의 사례가 5쌍 생겼다.
  - v1.6.2에서 2쌍: 아델 20261027000312←20261012000445, 케이엠에프 20261027000388←20261002000390.
  - v1.6.3에서 3쌍: SK이노베이션 20261028000313←20260826000056, 솔리스 20261030000349←20261016000278, 셀트릭스 20261103000135←20261022000156.
  - v1.6.3에서 "비SPAC 합병 DCF 13 → 15건, WACC 중앙값 11.28 → 9.42%"로 보고한 것은 SK이노베이션 한 거래를 두 번 센 값이다.
    맞는 값은 **13 → 14건(샘표만 추가), 11.28 → 10.35%**다.
  - `dedup_cases`: stats·compare·export는 같은 거래(`deal_key` = original_rcept_no 또는 rcept_no)의 가장 늦은 정정본만 쓴다. 빠진 사례가 필터에 걸리면 "정정본으로 대체된 사례" 경고를 낸다.
  - 디렉터리 validate는 옛 사례에 경고한다. 사례 파일은 지우지 않았다.
  - `batch plan`: 정정 꼬리표가 붙은 큐 항목이 같은 회사·유형의 기존 사례(접수 180일 안)와 겹치면 `skip:existing_correction`으로 보고 hint를 단다.
  - 2026-11-04 큐의 대기 IPO 12건 중 5건(에이엘로봇·다비오·에이엔에이치스트럭쳐·엔키화이트햇·씨앤엠)이 기존 사례의 정정이라 skip으로 기록했다.
- **후처리 자동화.**
  - `casedb finalize <json|dir> [--dry-run] [--offline]`은 induty_code·deal.spac/spac_basis·deal.status 초기값·relative_value.kind 규칙 분류·regime을 채운다.
    빈 칸만 채우고, 바꾼 칸은 notes에 남긴다.
    - status 초기값은 본문 접수 후 270일 안이면 "진행"이다.
    - regime은 IPO면 "IPO", 합병·교환·분할합병은 이사회 결의가 2026-12-09 전이면 "기준시가"다. 단순분할은 null로 둔다.
    - 상대가치 규칙 문구는 "3사 미만이므로 … 산정하지 아니"만 쓴다. "3사 미만인 경우에는"(규정 설명)은 제외한다(위메이드맥스·나노엔텍 오탐을 막는다).
  - `batch record … ok`가 finalize를 돌린다.
  - `validate`에 경고 `deal.spac 미설정`·`company.induty_code 비어 있음`·`deal.status 미설정`(IPO 제외)을 추가했다.
  - DB 167건 점검: spac 0·induty 0·status 4(v1.6.3 3건+샘표)가 비어 있었고, regime은 15건(전부 단순분할, 대상 아님)이 비어 있었다.
    finalize로 status 4건, relative_value 10건(카티스·RF시스템즈·위메이드맥스·엠에프씨·에르코스·에스엠씨지·바이오포트·뉴키즈온·애드포러스·코리아써키트, 전부 "산정하지 않음", derived)을 채웠다.
- **손으로 쓴 md 절 보호.**
  - `valuation md`는 생성 내용 끝에 `<!-- generated:end -->`를 두고, 그 아래는 다시 써도 보존한다.
  - 마커 없는 옛 md가 줄을 잃게 되면 잃을 제목·줄을 보여 주고 멈춘다(종료코드 1). `--adopt`는 꼬리 절을 마커 아래로 옮기고, `--force`는 덮어쓴다. `md <dir> --dry-run`으로 미리 본다.
  - dry-run 결과(167건): 그대로 141, 줄만 늘어남 19, 중단 7.
    - 중단 7건 중 6건은 "리뷰 반영 내역"이 있어 `--adopt`했다: 20250604000107·20250730000204·20261019000334·20261022000513·20261026000001·20261102000312.
    - 나머지 1건(엘리스그룹 20261006000447)은 생성 줄 변경(corp_code 채움)이라 `--force`했다.
  - `batch record`·`report`도 `_batch_<날짜>.md`의 마커 아래를 보존한다. v1.6.3의 "추출" 절이 지워져 HEAD에서 복원했다.
- **통계 안정성.**
  - stats·compare: 거래 3–30건인 변수에 `median_stability`(거래 1건씩 빼고 낸 중앙값의 min–max, 그 거래 목록, band_pct)를 붙인다.
    ±10%를 넘으면 "중앙값 안정성 … 거래 1건에 흔들림, 개별 선례로 확인" 경고를 낸다.
  - `--list [N]`은 개별 선례 표를 낸다(회사·접수번호·결의일·SPAC·상태·WACC·g·규모위험·자산가치 총액. 시가총액은 스키마에 없다).
  - 필터 `--exclude-rcept`를 추가했다.
  - 비SPAC 합병 DCF WACC는 14건, 중앙값 10.35%, LOO 9.42–11.28%(±9.0%, 경고 아님)다. 샘표·SK이노베이션을 빼면 12건, 11.38%다.
- **문서.**
  - docs/valuation_usage.md에 "인용 규칙"을 넣었다: n<20이면 개별 선례 표 우선, n·범위·SPAC·상태 병기, SPAC 분리, 규모 혼재 주의, 11.28 → 10.35(→ v1.6.3 오보 9.42) 예.
  - README 월초 절차를 8단계로 다시 썼다. CLAUDE.md·dart-valuation*·dart-valuation-search도 맞췄다.
- 저장소: `.gitignore`에 `/reports/*.md`·`/reports/*.csv`를 넣었다(healthcheck 결과는 제외). 개별 분석 보고서 5개는 커밋하지 않고 무시한다.

## v1.6.3 (2026-11-04)

v1.6.2 이후 마무리. 서버 코드(`server.py`·`financials.py`·`valuation.py`)가 바뀌었으니 MCP 재연결이 필요하다.

- **경고 분모**: `sample_warnings`의 분모를 분석 거래(통계 변수·멀티플 중 값이 하나라도 있는 거래)로 바꿨다. 값 없는 거래는 "값 없는 거래 k건 제외"로 따로 적는다.
  SPAC 쏠림은 "분석 거래 n건 중 SPAC s건(비SPAC만 m건, 판정 불가 u건)"이다. `--spac false`면 쏠림 경고 대신 "비SPAC n건(--spac false 적용)"을 낸다. compare·export도 같다.
- **보험업 계정**: `detect_sector`에 `subsector`를 추가했다(KSIC 65 insurance·641 bank·6612 securities). 보험사는 이자수익−이자비용을 `interest_net_investment`(투자손익의 일부)로 옮기고,
  `net_interest_income`은 `not_applicable(보험업)`으로 둔다. `insurance_service_result`(보험손익)·`investment_result`(투자손익) 계정을 추가했다.
- **relative_value.kind 재대조**: 상장사 간 기준주가 합병 6건(컴투스엔·대한항공·휴맥스·알에프텍·SK이노베이션·로젠)을 산정하지 않음 → 기재 생략으로 고쳤다
  (원문 "상대가치 등은 별도로 기재하지 않았습니다"). validate가 이 문구 + "산정하지 않음" 조합을 잡는다.
- **문서**:
  - CLAUDE.md·README에 Windows uv 폴백을 적었다. `valuation md`는 파일을 직접 쓴다(리다이렉트 금지).
  - 주석은 outline 제목으로 찾는다(`notes_sections`: 연결 주석이 비면 별도 주석 — 동양파일 4.5).
  - dart-risk는 첨부 outline 중복 조회를 하지 않는다.
  - C2 docstring을 정정했다(.hN은 비정기 본문에서만 생긴다).
  - dart-event에 같은 날 짝 공시·공개매수 단계를 넣었고, dart-event·dart-compare 저장 경로를 공통 규칙에 맞췄다.
- **스캔·배치**:
  - `search_valuation_disclosures`가 `excluded_unlisted`·`excluded_unlisted_by_type`을 돌려준다.
  - dart-valuation-scan에 `--include-unlisted`, 014 처리, related_rcept_nos 짝 확인을 추가했다.
  - `batch sample`(seed = 대상 rcept_no 정렬 목록의 sha256)을 추가했고, 리뷰 FAIL 건 수정 단계를 넣었다.
- **작은 도구**:
  - `casedb backfill-queue <dir> [--all] [--md]`는 보강 대기 목록(사례·필드·사유·근거)을 보여 준다.
  - `casedb diff <json> [--against <rev|json>]`는 보강 전후 필드별 diff를 보여 준다.
  - get_latest_reports는 사업보고서 없는 신규 상장사에 `interim_reports`(reprt_code·bsns_year, 결산월은 acc_mt)와 warning을 준다(B4).
  - search_disclosures에 `pblntf_detail_ty` 인자를 추가했다. pblntf_ty에 "B001" 같은 상세유형이 오면 옮기고 note를 단다. A–J 밖이면 error를 낸다(B5).
- 데이터:
  - 대기 큐의 합병 3건을 추출했다(IPO 12건은 queued로 남김). 3건 모두 validate·verify-cites 전수 통과, 리뷰 표본 1건(셀트릭스) PASS.
    - SK이노베이션 20261028000313: 비SPAC, 20회·56,624자.
    - 솔리스 20261030000349: SPAC, 9회·25,806자.
    - 셀트릭스 20261103000135: SPAC, 22회·95,816자.
  - v1.6.2에서 빠뜨린 `casedb derive`를 돌렸다. 아델·케이엠에프(20261027000388)·샘표(20261102000312)에 `deal.spac`이 없어 `--spac` 필터에서 빠지고 있었다.
  - 비SPAC 합병 DCF는 분석 거래 13 → 15건이다(SK이노베이션·샘표). WACC 중앙값은 11.28 → 9.42%, g 중앙값은 0.5% 그대로다.
  - 샘표 md를 다시 만들면서 손으로 붙인 "리뷰 반영 내역" 절이 사라져 HEAD에서 복원했다(`valuation md`는 덧붙인 절을 보존하지 않는다).

## v1.6.2 (2026-11-04)

회고 점검(`reports/_retro/retro_2026-11-04.md`) 정확성 수정. 서버 코드가 바뀌었으니 MCP 재연결이 필요하다.

- **본문 없는 [첨부정정] ZIP (B1)**: `search_valuation_disclosures`·`batch plan`에서 목록에 [첨부정정]·[첨부추가]만 있는 거래는
  corp_code로 150일 전까지 다시 조회해 원본·마지막 [기재정정]을 `body_rcept_no`로 되돌린다(`original_rcept_no`·`supersedes`도 채움).
  못 찾으면 `body_available=false`+`hint`, batch plan은 `skip:no_body`. 014 오류 응답에도 hint(본문 접수번호 또는 original_rcept_no 안내).
  2026-10-27–11-03 재현 5건(휴맥스·아이윈·애경케미칼·에이루트·APS) 모두 원본으로 복원.
- **표본 경고**: `valuation stats`·`casedb compare`·`casedb export` JSON 맨 앞 `warnings[]` — n<5 "표본 부족", n<10 "통계적 의미 제한",
  SPAC 비중 >50% "SPAC 쏠림(비SPAC만 n건)", 사분위 동일 "분포 정보 없음", 철회·중단·진행 포함 수, 체계 혼재, 최근접 선례의 SPAC 과반.
  compare: `nearest_table`(SPAC·상태 열), `filters`의 n → `nearest_n`, `--help`가 도움말 출력 (B6).
- **기관 필터 (B8)**: `--firm`은 부분 문자열이 아니라 기관 이름 일치(`firm_match`: 법인 표지·역할 괄호를 떼고, 꼬리 없는 질의는
  회계법인·증권·투자증권 꼬리를 뗀 이름과 비교). 행에 `firms[]`, 외부평가 원소의 `firm` 열은 그 원소의 기관(알에프텍 이촌·정동 혼입 해소).
- **비교 열 머리**: `get_key_financials` 연간 응답에 `acc_mt`·`column_labels`("FY2025(결산 11월)·별도"),
  `financials.comparison_header`가 연결·별도 혼재, 결산월 다름, ROE 기준 다름 경고. 분기·반기 응답에 `periods`(결산월로 계산한 실제 누적 기간,
  비12월 결산은 column_labels도 실제 기간). /dart-compare 문서 반영.
- **금융업 (B3)**: 순이자이익·순수수료이익 소계 행이 없고 수익·비용 행이 둘 다 있으면 수익 − |비용|, `derived=true`·`formula`. 한쪽이 없으면 null.
- **total_chars (B2)**: 상위 섹션이 하위 글자를 포함해 2배 넘게 셌다 → 최상위 섹션 합(`cache.top_level_chars`), 예전 캐시도 읽을 때 다시 셈.
- **리뷰**: /dart-review에 "f. 계정 분류·단위 해석 3건"(유동/비유동·자산/부채·천원/백만원·"원문 미확인" 사실 확인),
  /dart-analyze에 같은 회사 보고서끼리 숫자 교차 확인(선택 단계).
- 데이터: 아델 20261027000312 notes(rNPV WACC 8.5%, 리뷰 FAIL 반영).

이전 미배포 분(v1.6.2에 포함):

- **거래 단위 상대가치 구분** `relative_value.kind` = 산정 / 산정하지 않음 / 기재 생략. 기존 47건 이관: 산정하지 않음 36(규칙 분류 25 + 보강 11),
  기재 생략 11(규칙 분류 중 "자산가치 및 수익가치, 상대가치 등은 별도로 기재하지 않았습니다" — 11건 모두 상장사 간 기준주가 합병, 시행령 176조의5 ①1. 사유도 원문대로 고침).
  `stats`는 거래 단위 `relative_kind` 건수, `casedb export`는 "상대가치(거래)"·"상대가치 사유" 열. validate가 kind↔applied 정합을 검사.

## v1.6.1 (2026-10-27)

보강(backfill) 파일럿·2차와 규모위험 정리. 스키마: `dcf.size_premium_applied`, `size_premium_basis`에 {text, cite}, `peers[]`에 beta_l·beta_u·de·tax_rate, `relative_value.derived`.

- **보강**: 비SPAC DCF 합병 17건(파일럿 10 + 2차 7). 파일럿 169칸 중 62칸 채움(36.7% — 재무자문 DCF는 WACC 점 값만 공시), 2차 31칸 중 31칸.
  건당 평균 파일럿 6.2회·16,555자·약 10만 토큰·131초, 2차 1.1회·3,476자·약 7.8만 토큰·68초. 기존 숫자 값 변경 0. 독립 리뷰 4건 PASS.
- **null 감사 정밀도**(파일럿): "추출 안 함" 60칸 중 실제 누락 13(21.7%) — 상대가치 10/10, 비교회사 3/39, 규모위험 0/10. 섹션 단위 검색이 같은 섹션의
  다른 평가 주체 표를 집는 것이 주원인. 감사는 이제 보강이 확인한 칸을 다시 감사하지 않고, 거래 단위 relative_value를 인식한다(버그 2건 수정).
- **규모위험 정리**: size_premium 72개 값 중 격자 밖이거나 라벨이 규모가 아닌 25개를 원문 근거로 분류 — 규모위험 22(라벨만 Firm Specific·FSRP),
  고유위험·성장성 가산 2(휴맥스 이촌·보현 3.00% → specific_risk), 미적용 명시 0.00% 2(size_premium_applied=false), 판단 불가 2(SK이노베이션 삼정 '규모 및 국가위험' 0.00%, 그대로).
  stats·compare·export는 적용 값만 쓰고 `size_premium_not_applied`를 센다. specific_risk는 별도 변수(compare `--specific`). Ke 항등식에 specific_risk 포함.
- **상대가치 규칙 분류**: 거래 단위 relative_value가 없던 합병·교환 47건 중 캐시 원문의 정해진 사유 문구가 있는 36건(유사회사 3사 미만 25 · 기재하지 않음 11)을
  "미산정 + 사유"로 채움(derived=true, cite 검증). 문구 없는 11건은 그대로.
- **`/dart-valuation-backfill <rcept_no>`** 신규: 파일럿 절차, 재무자문 원소는 "원문에 없음"으로 빠르게. SPAC 사례는 인용할 때 건별 보강(README).

## v1.6.0 (2026-10-27)

사례 DB를 실무 질의에 쓸 수 있게(새 추출 없음). 스키마: `deal.spac`·`spac_basis`, `dcf.specific_risk`·`size_premium_basis`·`beta_method`, `relative_value`, `absent_reasons[]`.

- **`--firm` 의미 수정**: 그 기관이 subject인 원소만, `--as 외부평가(기본)|재무자문|any`. v1.5까지는 external_valuation.firm 문구로도 맞춰 같은 거래의 다른 기관 값이
  행에 섞였다(이촌 26개 값 → 외부평가 10개 값). 한울 외부평가 WACC 중앙값 10.88 → 11.59%, 삼도 10.37 → 12.87%.
- **SPAC 파생**(`casedb derive`): 합병·분할합병 70건 SPAC 36(이름+문구 34, 문구만 2: 지슨·씨피시스템)·비SPAC 34·unknown 0.
- **공통 필터** `--status`·`--exclude-status`·`--spac`·`--as`, **통계 변수** rf·mrp·size_premium·beta_u·beta_l·ke·kd·tax_rate·d_over_e(거래 단위 대표값).
- **`casedb compare`**: 내 가정의 백분위·최근접 선례 N건·n<5 표본 부족. 2026-10 실무 시험 시나리오 1의 수작업 결과와 숫자 일치.
- **`casedb export --csv`**: 평가 요소 1행, UTF-8 BOM.
- **`casedb audit-null --write`**: 규모위험·비교회사·상대가치·수익가치 null을 캐시 원문 키워드로 감사(키워드 ±80자 미적용 문구면 "원문에 없음") → `absent_reasons`.
  161건 전부 캐시 있음. 규모위험 51: 원문에 없음 35(미적용 명시 5)·추출 안 함 16 / 비교회사 59: 14·45 / 상대가치 72: 원문에 없음 3·추출 안 함 54(미산정 명시 13)·해당 없음 15 / 수익가치 10: 5·5.
- **Firm Specific Risk 3건**(삼덕·한경·참 회계법인): 원문 주석상 근거가 KICPA 규모위험이라 size_premium 유지(분리하지 않음), `specific_risk` 칸만 신설.
- **템플릿**: SPAC 근거·SPAC 법인명 그대로, β 산정 방식, 규모위험 근거, 거래 단위 상대가치, 본질가치 수익가치 점 값.

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
