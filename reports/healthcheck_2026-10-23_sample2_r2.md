# 파서·재무 매칭 healthcheck (2026-10-23)

- 대상: --corp-codes reports/healthcheck_2026-10-23_sample2.txt — 30개사
- 방식: server 함수 직접 호출(LLM 없음), 캐시 사용

| 검사 | 내용 |
|---|---|
| a | 뒷부분 누락(원문 SECTION-1·TITLE 수 vs 파싱 수) |
| b | U+FFFD(깨진 글자) |
| c | level 1 섹션 수(5–30) |
| d | 재무 API missing |
| e | reprt_code null 분기보고서 |
| f | API 숫자 ↔ 원문 요약재무정보 |
| g | 감사보고서 첨부 |

종합: PASS 28 · WARN 2 · FAIL 0 · ERROR 0

| 회사 | 시장 | 업종 | 본문 rcept_no | FY | fs | a | b | c | d | e | f | g | 종합 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (주)오리온홀딩스 | 유가 | 649 | 20260318000838 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| SK증권(주) | 유가 | 66121 | 20260316000883 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 메이슨캐피탈주식회사 | 코스닥 | 64911 | 20260617000380 | 2026 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)상지건설 | 코스닥 | 411 | 20260319001104 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 코오롱글로벌(주) | 유가 | 41221 | 20260323001556 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 계룡건설산업(주) | 유가 | 412 | 20260325001239 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 유니슨(주) | 코스닥 | 29119 | 20260319001238 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 에이치디현대마린엔진(주) | 유가 | 29119 | 20260316001327 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | WARN | PASS | WARN |
| (주)티앤엘 | 코스닥 | 213 | 20260318001498 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 바이오인프라 | 코스닥 | 70113 | 20260317000604 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | N/A | PASS | PASS |
| 제일약품(주) | 유가 | 212 | 20260316000872 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 한솔홀딩스(주) | 유가 | 64992 | 20260318001586 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 에스케이디스커버리(주) | 유가 | 64992 | 20260317000867 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 에이치엘비테라퓨틱스(주) | 코스닥 | 467 | 20260319001264 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 교촌에프앤비(주) | 유가 | 46313 | 20260323000879 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 크래프톤 | 유가 | 5821 | 20260515002689 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)모비스 | 코스닥 | 620 | 20260312000944 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)시큐브 | 코스닥 | 58221 | 20260323001582 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 페이퍼코리아(주) | 유가 | 171 | 20260323001240 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 삼화전자공업(주) | 유가 | 265 | 20260319001013 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 가온그룹(주) | 코스닥 | 264 | 20260317000844 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)에프에스티 | 코스닥 | 2629 | 20260318001663 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)파루 | 코스닥 | 281 | 20260320001090 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)강원에너지 | 코스닥 | 289 | 20260320000921 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)삼일 | 코스닥 | 49309 | 20260319000769 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)미트박스글로벌 | 코스닥 | 639 | 20260320001342 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 메가스터디교육(주) | 코스닥 | 85503 | 20260318000849 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| (주)콘텐트리중앙 | 유가 | 591 | 20260318001520 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)하이브 | 유가 | 592 | 20260320000802 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)포스코디엑스 | 유가 | 72129 | 20260417000431 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

## 이상 항목 상세

### 에이치디현대마린엔진(주) (00406046, 본문 20260316001327)
- **f WARN** API 숫자 ↔ 원문 요약재무정보: 매출액 402,396,221,904원: 원문 셀에 숫자가 구분자 없이 붙어 있음 '402,39675,912165,102-165,10216'(원문 XML 자체 결함); 자산총계 '814,697' 확인

### 메가스터디교육(주) (01074862, 본문 20260318000849, 첨부 20260326000491)
- **g WARN** 감사보고서 첨부: attachment_rcept_no 다운로드 실패(20260326000491: DART API error [status=014] 파일이 존재하지 않습니다.) → 20260318000849의 감사보고서 사용


## 진단

- 에이치디현대마린엔진 f: 1회차(`healthcheck_2026-10-23_sample2.md`)에선 파서 결함으로 진단했으나 **오진**이었다. 원문 XML 셀 자체가
  `<TD …>402,39675,912165,102-165,102…</TD>`로 구분자 없이 적혀 있다(셀 안 P·BR 없음). 파서로 복원할 수 없는 원문 결함이라
  (f)는 숫자열 속 부분일치를 찾으면 FAIL 대신 WARN(사유 명시)으로 판정한다. 셀 안 블록 경계 공백 처리(캐시 v7)는 예방용으로 넣었고,
  캐시 202개 XML에서 바뀐 셀은 0개다.
- 메가스터디교육 g, (r3) 디엘이앤씨 g: DART가 첨부정정 ZIP을 status=014로 거부 → 같은 그룹 다른 접수본의 감사보고서로 대체.
