# 회고 점검 A단계 — MCP 툴 (케이스 1–8)

- 일시: 2026-11-04 09:19–09:26 (벽시계, 세션 전체). 케이스별 시간은 따로 재지 않았고, 아래 "시간"은 호출 수로 어림한 값이다.
- 스키마 확인: ToolSearch `+dart`로 10개 툴(find_company, search_disclosures, search_valuation_disclosures, find_tables, get_disclosure_outline, get_disclosure_section, get_financial_statements, get_key_financials, get_latest_reports, search_in_disclosure)과 최신 인자(`refresh`, `period_type`, `page_no`, `kinds`, `caption_pattern` 등)가 모두 보였다 → **모든 케이스를 MCP로 호출**. 예외: 2(c)의 `pblntf_detail_ty`는 툴에 인자가 없어 **MCP 대신 직접 호출**(`.venv\Scripts\python.exe`, `DartClient.search_disclosures(**extra)`).
- "읽은 글자"는 툴 응답 JSON 크기를 어림한 값이다(본문 텍스트와 목차·메타 포함).
- 코드·문서·템플릿은 고치지 않았다. 가치평가 DB(`reports/valuations/`) 변경 없음(점검 전후 368개 파일, `git status` 64줄로 같음).

## 요약표

| # | 툴 | 판정 | MCP 호출 | 읽은 글자(어림) | 시간(어림) | 핵심 |
|---|---|---|---|---|---|---|
| 1 | find_company | **WARN** | 7 | 4k | 1분 | 후보 목록은 나옴. 상장폐지·옛 법인 구분 정보 없음, 옛 사명으로는 못 찾음, 0건일 때 안내 없음 |
| 2 | search_disclosures | **WARN** | 4 (+직접 1) | 3k | 1분 | 페이지·건수 정상. `pblntf_detail_ty` 인자 없음, `"B001"`을 pblntf_ty로 넣으면 "데이터 없음"으로 조용히 실패 |
| 3 | get_latest_reports | **PASS** (d는 WARN) | 6 | 10k | 1분 | 12월·11월 결산, 기재정정(body≠attachment) 모두 정상. 신규 상장사 오류 문구가 상황에 안 맞음 |
| 4 | get_disclosure_outline | **FAIL** (total_chars) | 8 | 68k | 2분 | depth=3 소제목·첨부·.hN 동작. 단 `total_chars`가 부모+자식 중복 합산으로 약 2.5배 부풀려짐 |
| 5 | get_disclosure_section | **PASS** | 2 (+4.1 재사용) | 4k | <1분 | error+available_ids, offset 분할 정상 |
| 6 | search_in_disclosure | **PASS** | 3 + 섹션 1 | 11k | 1분 | 소송·KAM 위치 찍고 범위만 읽기 정상. 가까운 매치가 겹치는 문맥으로 두 번 나오는 경우 있음 |
| 7 | get_key_financials / get_financial_statements | **WARN** (c는 FAIL) | 10 | 45k | 2분 | 일반·분기·OFS·refresh·교차확인 정상. 은행 순이자이익 null, 자본잠식 사례 N/A |
| 8 | search_valuation_disclosures + find_tables | **FAIL** (body_rcept_no) | 4 | 55k | 1분 | find_tables 정상. 원본이 조회 구간 밖인 첨부정정 건의 body_rcept_no가 본문 없는 정정 ZIP을 가리킴 |
| 계 | | PASS 3 · WARN 3 · FAIL 2 | 약 44 | 약 200k | 약 7분 | 케이스 하나도 안전장치(40회/8만 자)를 넘지 않음. 4번이 68k로 가장 컸음 |

---

## 케이스 1. find_company — WARN

호출: `삼성`(limit 5), `삼성전자`(3), `한진해운`, `POSCO`(5), `쌍용자동차`, `존재하지않는회사명XYZ`, `마키나락스`. 우리금융지주는 7번에서 조회.
고른 이유: 한진해운=2017 상장폐지 대표 사례, 쌍용자동차→KG모빌리티=사명 변경, 마키나락스=valuation DB에 있는 2026-05 IPO 사례(`reports/valuations/20260508000911.json`).

| 확인 | 결과 |
|---|---|
| 모호한 이름 "삼성" | limit=5가 지켜짐. 상장사 우선이지만 같은 길이 안에서는 순서가 임의라 1위가 **삼성수산**, 삼성전자는 상위 5위 밖. `count`는 반환 건수일 뿐 전체 매치 수가 아님 |
| 상장폐지(한진해운) | `stock_code "117930"`이 그대로 나오고 폐지 표시가 없음. 응답만으로는 상장사로 보임 |
| 같은 이름 두 법인(우리금융지주) | `00375302`(053000, 옛 법인)와 `01350869`(316140, 현 법인)가 구분 정보 없이 나란히 나옴 |
| 사명 변경(쌍용자동차) | 정비사업소 8곳만 나오고 KG모빌리티는 안 나옴. corp_codes에 옛 이름 별칭이 없음 |
| 0건 | `{"count":0,"results":[]}`. 기대한 "corp_codes 캐시 갱신 안내" 없음 |
| 캐시 | `data/corp_codes.json`이 점검 첫 호출 때(09:19) 다시 받아짐 → `CORP_CODES_MAX_AGE_DAYS` 자동 갱신은 동작. 다만 응답에 캐시 날짜가 없어 사용자는 알 수 없음 |
| 신규 상장(마키나락스) | 정상 조회(01709065, 477850) |

마찰: 캐시에 `modify_date`가 있는데 응답에 안 나와서 폐지·옛 법인을 가릴 단서가 없다.

## 케이스 2. search_disclosures — WARN

| 확인 | 결과 |
|---|---|
| (a) 삼성전자 A, 2024-11-04~2026-11-03, max_results=5, page_no=2 | `total_count 8, total_page 2, has_more false, returned 3`. 정상 |
| (b) corp_code="" + 5개월 | `DartApiError ... [status=100] corp_code가 없는 경우 검색기간은 3개월만 가능합니다.` 이해는 되지만 DART 원문 그대로이고, 기간을 나누거나 `search_valuation_disclosures`를 쓰라는 안내가 없음 |
| (c) `pblntf_ty="B001"` (툴 경유) | `[status=013] 조회된 데이타가 없습니다.` → 잘못된 코드인데 "데이터 없음"으로 보임. 값 검증 없음 |
| (c) 직접 호출, 같은 주 | `detail=B001` 단독 **240건** / `ty=B + detail=B001` **271건** / `ty=B` **271건** → pblntf_ty와 같이 주면 detail이 무시됨(valuation.py 9행 주석과 같은 결과) |
| 관찰 | corp_code=""로 조회하면 결과 항목에 `corp_code`가 없어 다음 호출 전에 find_company를 또 불러야 함 |

마찰: `uv`가 PATH에 없어 CLAUDE.md의 `uv run ...`이 Bash·PowerShell 모두 실패. `.venv\Scripts\python.exe`로 대신 실행.

## 케이스 3. get_latest_reports — PASS (d만 WARN)

| 확인 | 결과 |
|---|---|
| (a) 삼성전자 | latest_annual `20260310002820`(2025.12), 그 뒤 1분기 `20260515002181`, 반기 `20260814003699`. 3분기(마감 11/14)는 아직 없음 → 정상 |
| (b) 현대약품(11월 결산) | `fy_end_month 11`, 사업 2025.11, 분기 2026.02(11013)·반기 2026.05(11012)·분기 2026.08(11014) 모두 `bsns_year 2026`. 정상 |
| (c) HD현대마린엔진 | 1분기가 `[기재정정]` → `body_rcept_no 20260519000171`, `attachment_rcept_no 20260515001116`(원본)으로 갈림, superseded에 원본. 정상. late_corrections는 비어 있음(해당 없음) |
| (d) 마키나락스(2026 IPO) | `error: "최근 2년 안에 사업보고서가 없습니다. search_disclosures로 기간을 넓혀 확인하세요."`, `periodic_count 2`. 기대대로 오류는 나지만, 신규 상장사에게 "기간을 넓혀"는 맞지 않는 안내. 이미 있는 반기·분기 2건도 돌려주지 않음 |

고른 이유: 현대약품=대표적 11월 결산 상장사, HD현대마린엔진=4(c) 대상이라 같이 확인.

## 케이스 4. get_disclosure_outline — FAIL (total_chars), 나머지 PASS/관찰

대상: HD현대마린엔진 사업보고서(2025.12) `20260316001327`, 마키나락스 증권신고서 `20260508000911`(발행조건확정)·`20260325001168`(최초).

| 확인 | 결과 |
|---|---|
| (a) depth=2 vs 3 | depth=2: 59개 표시(재무 섹션 4.3 = 86,981자 한 덩어리). depth=3: 145개, `4.3.t1`–`4.3.t38`(주석 1–38) `kind="title"`이 나옴. **PASS** |
| (a) 관찰 | depth=2에도 `8.t1 "VII. 주주에 관한 사항"`, `8.t2 "소액주주현황>"`(kind=title)이 나옴 — 문서는 "title은 depth=3"이라고 함. 제목 끝 `>`도 잘림 흔적 |
| **total_chars** | 본문 `total_chars 840,063`인데 level-1 섹션 합은 약 **328k**. `cache.py:141` `total = sum(s.char_count for s in sections)`가 부모·자식을 모두 더함(상위 char_count는 하위 포함). 첨부 00761도 142,693 vs 실제 약 78k. **FAIL**(숫자가 틀림; "150만 자 넘는 문서" 판단·비용 추정에 영향) |
| (b) 첨부 00760/00761 | 둘 다 열림. 00761 depth=3에서도 `2.1 주석` 61,839자 한 덩어리 → CLAUDE.md 6-1과 같음. 단, 툴 설명은 "TITLE 없이 5만 자 넘는 섹션은 depth=3에서 .hN"이라는데 첨부 주석(61k)엔 .hN이 안 생김(본문에서만 동작하는 것으로 보임). 관찰 |
| (c) HD현대마린엔진 parse_warnings | **비어 있음**. 저장소 기록상 parse_warnings 사례는 GS건설·두산에너빌리티(수정됨)이고, HD현대마린엔진의 알려진 문제는 **원문 셀 숫자 붙음**(README 161행). 4.1 요약재무정보에서 `402,39675,912165,102…`로 붙은 것 재확인. 케이스 전제와 다름 → 관찰 |
| (d) 증권신고서 .hN | 최초본 `20260325001168` depth=3에서 `6.h1 "가. 평가결과"`–`6.h34`, `5.1.h1`–`h5`, `11.3.h1`–`h30` 등 나옴. **동작은 함**. 문제: `5.1.h1 "(2) 국내 경기 동향"`이 93,500자(첫 표지 앞 내용이 다 들어감), 순서가 (2)→(1)→(3), 제목에 본문 섞임("(1) 미국시장당사는 …"), level-1 제목이 빈 문자열인 섹션(`2`, `20`) |
| (d) 발행조건확정본 | `20260508000911` main = 섹션 `0` 하나(186,158자), 구조 없음, .hN도 없음. 이 IPO 사례 JSON의 cite 21개가 모두 `section_id "0"` |

## 케이스 5. get_disclosure_section — PASS

| 확인 | 결과 |
|---|---|
| (a) 30,000자 이하 통째로 | `4.1`(2,263자) 한 번에, `has_more false` |
| (b) 없는 id `4.9` | `{"error": "section_id '4.9' 없음 (file_id=main). get_disclosure_outline로 id를 확인하세요.", "available_ids": [...]}` 기대대로 |
| (b) 관찰 | available_ids에 depth=3 outline에도 안 보이던 `4.7.1.t1`–`t6`가 있음(depth 4 상당). 숨은 id가 있다는 걸 outline으로는 알 수 없음 |
| (c) 분할 읽기 | `4.3` offset=40000, max_chars=1500 → `has_more true, next_offset 41500`. 정상 |
| (c) 관찰 | 자른 위치가 표 중간이라 그 조각엔 머리행·단위 행이 없음(표 앞부분 "(단위 : 천원)"을 따로 봐야 함) |

## 케이스 6. search_in_disclosure — PASS

| 확인 | 결과 |
|---|---|
| "소송"(본문) | `total_matches 19, total_clusters 8`. `4.3.t35`(연결 주석 35)·`4.5.t35`·`12.2`(우발부채 등)·`7.2`로 찍힘. 12.2에 방위사업청 손해배상 소송가액 6,799백만원 (20260316001327, 12.2) |
| "핵심감사사항"(00761) | `section_id "1"` offset 688·1159·3333. offset 1000부터 900자 읽어 KAM "해외매출 기간귀속의 적정성" 확인 (20260316001327, 00761 §1) |
| 첨부 주석 안 쪼개짐 | "우발부채"(00761) → `2.1 주석` offset 57,748 한 섹션 안에서만 찍힘. 6-1 규칙 확인 |
| 관찰 | 같은 섹션에서 226자 떨어진 매치가 두 클러스터로 나와 context가 거의 겹침(4.3.t35 offset 507·733). 첨부 텍스트는 단락 사이 공백이 빠져 "…않습니다.해외매출 기간귀속의 적정성연결회사는"처럼 붙음 |

## 케이스 7. 재무 API — WARN (c는 FAIL, d는 N/A)

| 확인 | 결과 |
|---|---|
| (a) 삼성전자 2025 CFS | 10계정+optional 2개 모두 matched. ROE 2025 10.85% = 44.26조 / ((424.31+391.69)/2)조로 재계산 일치, `basis "지배주주 기준"`, denominator 2023 `"ending"`. **PASS** |
| (a) 관찰 | ROA "지배주주 기준" = 지배주주 순이익 / **총자산** 평균. 분자만 지배주주라 개념이 섞임 |
| (b) 11012 quarter vs cumulative | 매출 누적 305.37조 = 1분기 133.87 + 2분기 171.50(quarter). 전년도 누적 153.71 − 2분기 74.57 = 1분기 79.14 → 맞음. BS prior = 2025 사업연도말(자산 566.94조, 연간과 같음). quarter의 CF는 null+사유. **PASS** |
| (b) 11014 2026 | 아직 미제출 → `message` "조회 데이터 없음(status 013)…". 013은 캐시하지 않음(financials.py 575행) 확인 |
| (b) 11011 + quarter | `{"error": "사업보고서(11011)는 period_type='annual'만 가능합니다"}` 명확 |
| (b) 관찰 | cumulative CF의 `fields.prior`가 `"frmtrm_q_amount"`로 적혀 라벨이 헷갈림(값은 누적) |
| (c) 카카오뱅크 | CFS → 013, message가 OFS 재호출을 안내(좋음). OFS → `sector financial`, `warning` 있음, revenue not_applicable. **그러나 `net_interest_income`·`net_fee_income` null(financial_missing)**. 캐시를 보면 이자수익 2,456,860백만·이자비용 1,138,216백만, 수수료수익·비용 행은 있고 "순이자" 소계 행만 없음 → 은행의 핵심 지표가 빠짐. **FAIL** |
| (d) 자본잠식 | 캐시된 사업보고서 76건 중 자본총계 음수 없음, 알려진 실사례 없음 → **N/A**(단위테스트 `test_capital_impairment_flag_nulls_equity_ratios`만 있음) |
| (e) 연결 013 → OFS | 카카오뱅크로 확인(위). **PASS** |
| (f) refresh=True | `data/fin/00126380_2025_11011_CFS.json` mtime 2026-10-18 16:40 → 2026-11-04 09:24, 크기 122,947→122,969. **PASS** |
| (g) 교차 확인 | `get_financial_statements(IS, refresh)`의 매출 333,605,938백만·영업이익 43,601,051백만·순이익 45,206,805백만·지배순이익 44,260,956백만이 key 값과 같음. BS·CF는 비용 때문에 부르지 않음(BS는 (b)에서 연간 자산총계와 일치 확인) |
| 관찰 | IS 행이 재무제표 순서가 아님(영업이익이 맨 앞, 매출액이 끝에서 두 번째). key_financials 응답이 `matched` 메타 때문에 건당 9k자 안팎 |

## 케이스 8. search_valuation_disclosures + find_tables — FAIL (body_rcept_no), find_tables는 PASS

| 확인 | 결과 |
|---|---|
| 1주일 조회 | `api_pages 5, total 37`: IPO/full 14, 합병/summary 16, 합병/full 2, 주식교환·이전/summary 3, 영업양수도/summary 1, 분할/summary 1. 등급은 잘 나옴 |
| 외부평가 여부·기관 | **응답에 필드 없음**. 외부평가 여부는 `/dart-valuation-scan`처럼 본문을 따로 읽어야 알 수 있음. 관찰 |
| 짝 공시 | 샘표식품 B(`20261030000695`)↔C(`20261102000312`), SK이노베이션 B↔C가 related_rcept_nos로 연결됨. 정상 |
| **body_rcept_no 오류** | 원본이 구간 밖인 `[첨부정정]` 건(휴맥스 `20261028000235`, 아이윈·애경케미칼·에이루트·APS 등 5건)은 `body_rcept_no`가 **첨부정정 자신**. 휴맥스 outline → `DartApiError [status=014] 파일이 존재하지 않습니다.` hint 없음. 다음 단계 안내대로 하면 바로 실패 → **FAIL** |
| 관찰 | 37건 중 25건에 "목록에 원본이 없음" note. 1주일 창이라 당연하지만, 원본을 찾으러 기간을 넓히라는 안내는 없음 |
| find_tables | 샘표식품 증권신고서(합병) full `20261102000312`, 섹션 `4` "II. 합병 가액 및 그 산출근거"(45,341자), `caption_pattern="합병가액|합병비율|평가|할인율|WACC"` → `total_matched 22`, 6개 반환, `has_more`·`next_offset 8912`. `[샘표식품(주)의 합병가액 산정(기산일: 2026년 10월 29일)]` 21,050원, 샘표(주) 43,955원, `[비교표]` 외부재무전문가(삼정) DCF 71,209–86,141원·비율 범위 1:1.9884501–1:2.1655639. **PASS** |
| 사례 JSON 방식과 맞는지 | 사례 cite는 `{section_id, offset, file_id}`이고 find_tables의 `offset`이 같은 좌표(섹션 텍스트 기준) → 그대로 옮길 수 있음. caption은 JSON에 쓰지 않음 |
| find_tables 관찰 | `caption_source "line"`이 긴 본문 단락을 캡션으로 잡음(200자 "…"), 단위가 머리행 `금액(원)`에만 있으면 `unit null`. 합병 신고서의 당사회사 두 곳 섹션(`12`–`21`, `22`–`31`)이 같은 제목("I. 회사의 개요")이라 회사 구분이 outline에 안 보임 |

---

## 문제 목록 (고치지 않음, 관찰만)

| # | 심각도 | 위치 | 내용 |
|---|---|---|---|
| P1 | 높음 | `valuation.py` (search_valuation_disclosures) | 원본이 조회 구간 밖인 `[첨부정정]` 건의 `body_rcept_no`가 본문 없는 첨부정정 ZIP → outline이 014로 실패 |
| P2 | 중간 | `cache.py:141` | `total_chars`가 부모·자식 char_count를 중복 합산(약 2.5배) |
| P3 | 중간 | `financials.py` 금융업 계정 매칭 | 순이자이익 소계 행이 없는 은행(카카오뱅크)에서 net_interest_income·net_fee_income null. 수익−비용으로 계산하지 않음 |
| P4 | 중간 | find_company | 상장폐지·옛 법인 구분 없음(한진해운, 우리금융지주 2건), 옛 사명 검색 불가, 0건 안내 없음, 같은 길이 안 순서가 임의 |
| P5 | 중간 | search_disclosures | `pblntf_detail_ty` 인자 없음, 잘못된 pblntf_ty 값을 검증하지 않아 "데이터 없음"으로 보임, corp_code="" 결과에 corp_code 없음, 3개월 오류에 대안 안내 없음 |
| P6 | 낮음 | get_latest_reports | 신규 상장사 오류가 "기간을 넓혀"라고 안내하고 이미 있는 반기·분기를 안 줌 |
| P7 | 낮음 | document.py .hN 휴리스틱 | 첫 heading이 앞부분을 다 먹음(93k자), 순서 뒤섞임, 제목에 본문 혼입, 첨부 주석엔 미적용 |
| P8 | 낮음 | outline | depth=2에 title 항목 노출, depth=3에도 안 보이는 id(`4.7.1.tN`)가 available_ids에만 있음 |
| P9 | 낮음 | search_valuation_disclosures | 외부평가 여부·기관 필드 없음 |
| P10 | 낮음 | 재무 API | ROA 지배주주 기준의 분모가 총자산, cumulative CF `fields.prior` 라벨, IS 행 순서, 응답이 장황 |
| P11 | 낮음 | 사례 DB | IPO 사례 `20260508000911`이 발행조건확정본(섹션 0 하나)을 써서 cite가 모두 `section_id "0"` |
| P12 | 환경 | CLAUDE.md | `uv`가 PATH에 없어 `uv run …` 명령이 이 환경에서 바로 안 됨 |

## 변경 파일

- 새로 만든 파일: `reports/_retro/A_mcp_tools_2026-11-04.md`(이 파일)만.
- `reports/valuations/`: 변경·추가 없음(전후 368개, `git status --short` 64줄로 같음 — 64줄은 점검 전부터 있던 수정분).
- 캐시(git 제외): `data/corp_codes.json` 자동 재다운로드, `data/fin/00126380_2025_11011_CFS.json` refresh, `data/fin/01133217_2025_11011_OFS.json` 등 새 재무 캐시, `data/lists/`·`data/<rcept_no>/` 원문 캐시 추가.
