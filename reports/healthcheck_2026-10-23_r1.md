# 파서·재무 매칭 healthcheck (2026-10-23)

- 대상: --corp-codes reports/healthcheck_2026-10-23_sample1.txt — 30개사
- 방식: server 함수 직접 호출(LLM 없음), 캐시 사용

| 검사 | 내용 |
|---|---|
| a | 트리 붕괴(level≥2 섹션 > 문서 50%) |
| b | U+FFFD(깨진 글자) |
| c | level 1 섹션 수(5–30) |
| d | 재무 API missing |
| e | reprt_code null 분기보고서 |
| f | API 숫자 ↔ 원문 요약재무정보 |
| g | 감사보고서 첨부 |

종합: PASS 17 · WARN 8 · FAIL 4 · ERROR 1

| 회사 | 시장 | 업종 | rcept_no | FY | fs | a | b | c | d | e | f | g | 종합 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (주)푸른저축은행 | 코스닥 | 64132 | 20260407003063 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 한화손해보험(주) | 유가 | 65121 | 20260331000594 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| 한화생명보험(주) | 유가 | 65110 | 20260331003585 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| (주)대우건설 | 유가 | 41112 | 20260318001029 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 디엘이앤씨 주식회사 | 유가 | 412 | 20260814003447 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| (주)삼일기업공사 | 코스닥 | 411 | 20260320001358 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 두산에너빌리티(주) | 유가 | 29119 | 20260320001246 | 2025 | CFS | PASS | PASS | WARN | PASS | PASS | PASS | PASS | WARN |
| 00361381 |  |  |  |  |  |  |  |  |  |  |  |  | ERROR |
| (주)대성미생물연구소 | 코스닥 | 21230 | 20260316000567 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | FAIL |
| 에이치케이이노엔 주식회사 | 코스닥 | 212 | 20260318000705 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 대원제약(주) | 유가 | 212 | 20260318001398 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)비지에프 | 유가 | 64992 | 20260318000777 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 에프앤에프홀딩스 | 유가 | 64992 | 20260318001442 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 현대그린푸드 | 유가 | 471 | 20260316001009 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)원익 | 코스닥 | 4659 | 20260323000632 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 주식회사 오픈놀 | 코스닥 | 58222 | 20260812000028 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| (주)뉴엔에이아이 | 코스닥 | 58222 | 20260318000699 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | FAIL |
| (주)미래아이앤지 | 유가 | 620 | 20260323000816 | 2025 | OFS | PASS | PASS | PASS | WARN | PASS | FAIL | PASS | FAIL |
| (주)뉴온 | 코스닥 | 108 | 20260320001292 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)아이앤씨테크놀로지 | 코스닥 | 2611 | 20260318001683 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)휴스틸 | 유가 | 2413 | 20260602000398 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| 두산로보틱스 주식회사 | 유가 | 2928 | 20260318001562 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 경남스틸(주) | 코스닥 | 24199 | 20260309001568 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)얼라인드제네틱스 | 코스닥 | 273 | 20260323001245 | 2025 | CFS | PASS | PASS | PASS | WARN | PASS | PASS | PASS | WARN |
| 씨제이씨지브이(주) | 유가 | 59141 | 20260318001114 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)케이티밀리의서재 | 코스닥 | 581 | 20260323000748 | 2025 | OFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| (주)엠83 | 코스닥 | 59111 | 20260320000986 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 파라택시스 코리아(주) | 코스닥 | 739 | 20260407003707 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | FAIL |
| (주)INVENI | 유가 | 715 | 20260605000111 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | WARN |
| 에이치엠엠(주)  | 유가 | 50112 | 20260318001444 | 2025 | CFS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

## 이상 항목 상세

### 한화손해보험(주) (00135917, 20260331000594)
- **g WARN** 감사보고서 첨부: 첨부 없음 중 감사보고서 없음

### 한화생명보험(주) (00113058, 20260331003585)
- **g WARN** 감사보고서 첨부: 첨부 없음 중 감사보고서 없음

### 디엘이앤씨 주식회사 (01524093, 20260814003447)
- **g WARN** 감사보고서 첨부: 첨부 없음 중 감사보고서 없음

### 두산에너빌리티(주) (00159616, 20260320001246)
- **c WARN** level 1 섹션 수(5–30): 4개

### 00361381 (00361381, -)
- ERROR: AttributeError: 'NoneType' object has no attribute 'sections'

### (주)대성미생물연구소 (00177320, 20260316000567)
- **f FAIL** API 숫자 ↔ 원문 요약재무정보: 매출액 25,988,810,012원: 4.1 요약재무정보엔 없고 다른 섹션에만(25,988,810,012 → ['4.4.t3']); 자산총계 57,979,205,426원: 4.1 요약재무정보엔 없고 다른 섹션에만(57,979,205,426 → ['4.4.t2'])

### 주식회사 오픈놀 (01585155, 20260812000028)
- **g WARN** 감사보고서 첨부: 첨부 없음 중 감사보고서 없음

### (주)뉴엔에이아이 (01639508, 20260318000699)
- **f FAIL** API 숫자 ↔ 원문 요약재무정보: 매출액 18,819,000,000원: 4.1 요약재무정보엔 없고 다른 섹션에만(18,819 → ['12.4', '4.4.t2', '5.2']); 자산총계 57,617,000,000원: 4.1 요약재무정보엔 없고 다른 섹션에만(57,617 → ['3.1', '4.4.t1', '5.3'])

### (주)미래아이앤지 (00104786, 20260323000816)
- **d WARN** 재무 API missing: OFS missing=['capex']
- **f FAIL** API 숫자 ↔ 원문 요약재무정보: 매출액 14,128,766,686원: 4.1 요약재무정보엔 없고 다른 섹션에만(14,128,766,686 → ['4.4.t2']); 자산총계 70,534,354,404원: 4.1 요약재무정보엔 없고 다른 섹션에만(70,534,354,404 → ['4.4.t1'])

### (주)휴스틸 (00156488, 20260602000398)
- **g WARN** 감사보고서 첨부: 첨부 없음 중 감사보고서 없음

### (주)얼라인드제네틱스 (01073678, 20260323001245)
- **d WARN** 재무 API missing: CFS missing=['capex']

### 파라택시스 코리아(주) (01227039, 20260407003707)
- **f FAIL** API 숫자 ↔ 원문 요약재무정보: 매출액 9,000,000원: 4.1 요약재무정보엔 없고 다른 섹션에만(9,000,000 → ['4.2.t2', '4.3', '4.5']); 자산총계 '70,831' 확인

### (주)INVENI (00105101, 20260605000111)
- **g WARN** 감사보고서 첨부: 첨부 없음 중 감사보고서 없음


## 원인 진단 (2026-10-23, 수정 없음)

표본: `reports/healthcheck_2026-10-23_sample1.txt` — 요청한 업종 할당 합이 24라 "기타 업종(비제조) 3유가·3코스닥"을 더해 30개, 코스닥 15개(50%).

| 회사 | 결과 | 원인 | 분류 |
|---|---|---|---|
| 두산에너빌리티 | c WARN(4개) | **파서 실결함.** XML 66715·66956행 `ENG="Doosan Power Systems S.A. ("DPS S.A.") [member}"` — 속성값 안 이스케이프 안 된 `"`. lxml recover가 TH 시작 태그를 못 닫고, 이후 닫는 태그마다 스택이 한 단계씩 올라가 III장 끝(101133행)에서 BODY·DOCUMENT까지 닫힘 → IV–XII장·전문가 확인(약 88만 자 XML) 통째로 누락. 캐시 88개 XML 중 이 패턴은 이 1건뿐 | 파서 |
| 두산에너빌리티 | a PASS(오탐 누락) | a는 level≥2만 보므로 **level 1 절단**(뒤 장 누락)을 못 잡음. III장이 문서의 82%인데 PASS | 검사 설계 |
| 제이브이엠 | ERROR | 최신 사업보고서가 `[첨부정정]`(20260325000430)이고 그 ZIP에 본문 없이 첨부 00760·00761만 있음 → main 파일 None. get_latest_reports가 첨부정정을 latest_annual로 고르므로 MCP 사용자도 같은 rcept_no로 본문을 못 읽는다 | periodic/server |
| 대성미생물연구소, 미래아이앤지 | f FAIL | 4.1 요약재무정보가 "소규모기업(자산 1천억 미만) 생략" 문구뿐. 숫자는 4.4 본표에 원 단위로 정확히 있음 | 검사 오탐 |
| 뉴엔에이아이 | f FAIL | 재무 API 값이 백만원 반올림(57,617,000,000)이고 4.1은 원 단위(57,616,790,217). 반올림하면 일치 | 검사 오탐 |
| 파라택시스 코리아 | f FAIL | 매출(영업수익) 9백만원 → 4.1(백만원)엔 "9"로 표기, 후보 생성이 3자리 미만을 버려 못 찾음. 자산총계는 확인 | 검사 오탐 |
| 한화손보·한화생명·디엘이앤씨·오픈놀·휴스틸·INVENI | g WARN | 최신본이 `[기재정정]`이고 정정 ZIP에 본문만 있음(감사보고서는 최초 제출본 original_rcept_no에) | 데이터 특성 |
| 미래아이앤지, 얼라인드제네틱스 | d WARN capex | 현금흐름표에 유형자산 취득 계정 자체가 없고 원문에도 "유형자산의 취득" 0건 → 실제로 취득 없음으로 추정 | 정상(추정) |

부수 관찰: document.py의 트리 붕괴 경고가 감사보고서 첨부의 "주석" 섹션(첨부 전체의 75–85%)마다 뜬다 — 첨부에선 정상 구조라 경고 노이즈.
