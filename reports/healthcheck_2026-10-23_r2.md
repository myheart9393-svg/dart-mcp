# 파서·재무 매칭 healthcheck (2026-10-23)

- 대상: --corp-codes reports/healthcheck_2026-10-23_sample1.txt — 30개사
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

종합: PASS 29 · WARN 1 · FAIL 0 · ERROR 0

| 회사 | 시장 | 업종 | 본문 rcept_no | FY | fs | a | b | c | d | e | f | g | 종합 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (주)푸른저축은행 | 코스닥 | 64132 | 20260407003063 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 한화손해보험(주) | 유가 | 65121 | 20260331000594 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 한화생명보험(주) | 유가 | 65110 | 20260331003585 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)대우건설 | 유가 | 41112 | 20260318001029 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 디엘이앤씨 주식회사 | 유가 | 412 | 20260814003447 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| (주)삼일기업공사 | 코스닥 | 411 | 20260320001358 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 두산에너빌리티(주) | 유가 | 29119 | 20260320001246 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)제이브이엠 | 코스닥 | 29192 | 20260323001116 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)대성미생물연구소 | 코스닥 | 21230 | 20260316000567 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | N/A | PASS | PASS |
| 에이치케이이노엔 주식회사 | 코스닥 | 212 | 20260318000705 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 대원제약(주) | 유가 | 212 | 20260318001398 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)비지에프 | 유가 | 64992 | 20260318000777 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 에프앤에프홀딩스 | 유가 | 64992 | 20260318001442 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 현대그린푸드 | 유가 | 471 | 20260316001009 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)원익 | 코스닥 | 4659 | 20260323000632 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 오픈놀 | 코스닥 | 58222 | 20260812000028 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)뉴엔에이아이 | 코스닥 | 58222 | 20260318000699 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)미래아이앤지 | 유가 | 620 | 20260323000816 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | N/A | PASS | PASS |
| (주)뉴온 | 코스닥 | 108 | 20260320001292 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)아이앤씨테크놀로지 | 코스닥 | 2611 | 20260318001683 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)휴스틸 | 유가 | 2413 | 20260602000398 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 두산로보틱스 주식회사 | 유가 | 2928 | 20260318001562 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 경남스틸(주) | 코스닥 | 24199 | 20260309001568 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)얼라인드제네틱스 | 코스닥 | 273 | 20260323001245 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 씨제이씨지브이(주) | 유가 | 59141 | 20260318001114 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)케이티밀리의서재 | 코스닥 | 581 | 20260323000748 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)엠83 | 코스닥 | 59111 | 20260320000986 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 파라택시스 코리아(주) | 코스닥 | 739 | 20260407003707 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)INVENI | 유가 | 715 | 20260605000111 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 에이치엠엠(주)  | 유가 | 50112 | 20260318001444 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

## 이상 항목 상세

### 디엘이앤씨 주식회사 (01524093, 본문 20260814003447, 첨부 20260317000901)
- **g WARN** 감사보고서 첨부: attachment_rcept_no 다운로드 실패(20260317000901: DART API error [status=014] 파일이 존재하지 않습니다.) → 20260317000887의 감사보고서 사용


## 진단 (1차 대비)

1차(`healthcheck_2026-10-23_r1.md`)의 FAIL 4·ERROR 1·WARN 8이 모두 해소됐다: 두산에너빌리티(속성값 따옴표 전처리로 I–XII 복구),
제이브이엠(본문은 body_rcept_no 20260323001116), f 오탐 4건(요약 생략 N/A·반올림/절사 허용), g 6건(attachment_rcept_no의 첨부),
capex 2건(assumed_zero).

남은 WARN 1건은 실제 사유다: 디엘이앤씨 attachment_rcept_no 20260317000901([첨부정정])의 원문 다운로드를 DART가
status=014(파일 없음)로 거부 → 최초 제출본 20260317000887의 감사보고서로 대체.
