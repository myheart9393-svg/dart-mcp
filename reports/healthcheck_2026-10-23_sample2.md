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

종합: PASS 28 · WARN 1 · FAIL 1 · ERROR 0

| 회사 | 시장 | 업종 | 본문 rcept_no | FY | fs | a | b | c | d | e | f | g | 종합 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (주)오리온홀딩스 | 유가 | 649 | 20260318000838 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| SK증권(주) | 유가 | 66121 | 20260316000883 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 메이슨캐피탈주식회사 | 코스닥 | 64911 | 20260617000380 | 2026 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)상지건설 | 코스닥 | 411 | 20260319001104 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 코오롱글로벌(주) | 유가 | 41221 | 20260323001556 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 계룡건설산업(주) | 유가 | 412 | 20260325001239 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 유니슨(주) | 코스닥 | 29119 | 20260319001238 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 에이치디현대마린엔진(주) | 유가 | 29119 | 20260316001327 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | FAIL |
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
- **f FAIL** API 숫자 ↔ 원문 요약재무정보: 매출액 402,396,221,904원: 4.1 요약재무정보에 원·천원·백만원 표기 모두 없음; 자산총계 '814,697' 확인

### 메가스터디교육(주) (01074862, 본문 20260318000849, 첨부 20260326000491)
- **g WARN** 감사보고서 첨부: attachment_rcept_no 다운로드 실패(20260326000491: DART API error [status=014] 파일이 존재하지 않습니다.) → 20260318000849의 감사보고서 사용


## 진단 (수정 없음)

| 회사 | 결과 | 원인 | 분류 |
|---|---|---|---|
| 에이치디현대마린엔진 | f FAIL | **파서 실결함.** 요약재무정보 표가 한 셀 안에 계정·값을 줄바꿈(<P>)으로 쌓아 두는데, `_Renderer._text_of`가 `"".join(el.itertext())`로 이어 붙여 "402,39675,912165,102…"처럼 숫자가 붙는다(매출액 402,396 백만원이 독립된 숫자로 남지 않음). 셀 안 블록 경계에 공백/구분자를 넣으면 고쳐지지만 표 렌더링 전반이 바뀌므로 parser_regression으로 영향 범위를 본 뒤 다음 단계에서 결정 | 파서 |
| 메가스터디교육 | g WARN | attachment_rcept_no 20260326000491([첨부정정]) 다운로드가 status=014 → 최초 제출본 20260318000849의 감사보고서로 대체 | DART 데이터 |

사전 수정(이번 커밋에 반영): 오리온홀딩스·에프에스티의 f FAIL은 원문이 백만원 미만을 올림해 적은 것(6,183,410.43→6,183,411, 540,070.06→540,071)이라
비교 허용오차를 "한 단위 미만"으로 넓혀 해소. 1차 재실행의 한화손해보험도 절사(20,492,834.69→20,492,834) 동일 사유.
