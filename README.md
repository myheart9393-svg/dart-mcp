# dart-mcp

OpenDART(금융감독원 전자공시) 공시 원문을 **섹션 단위**로 읽고 재무 API 숫자를 구조화해 주는 MCP 서버(`dart`)와,
그 위에서 Claude Code가 기업분석 보고서를 쓰는 슬래시 커맨드 모음.

- 원문: 공시 ZIP → XML → Markdown(표 포함) → 목차·섹션으로 쪼개 필요한 부분만 읽는다. 원문 전체를 한 번에 주는 툴은 없다.
- 숫자: `fnlttSinglAcntAll` 재무 API를 받아 핵심 10계정·비율로 정리한다. 원칙은 **숫자는 API, 서술은 원문**.

## 설치

```bash
uv sync
cp .env.example .env   # DART_API_KEY=<https://opendart.fss.or.kr 에서 발급한 키>
uv run pytest -q
```

`.env`는 git에서 제외된다. 키가 없으면 캐시에 있는 공시만 읽을 수 있고, 나머지 툴은 `{"error": ...}`를 돌려준다.

## Claude Code 등록

프로젝트 루트의 `.mcp.json`이 서버를 등록한다(프로젝트를 열면 `dart` 서버가 뜬다).

```json
{"mcpServers": {"dart": {"command": "<uv.exe 절대경로>",
  "args": ["run", "--directory", "<프로젝트 절대경로(슬래시)>", "python", "-m", "dart_mcp.server"]}}}
```

- 데스크톱 앱은 PATH가 짧아 `uv` 대신 **uv.exe 절대경로**를 써야 한다. 경로는 `/`로 적는다(JSON 이스케이프 문제).
- `server.py`·`document.py`·`cache.py`·`financials.py`·`periodic.py`를 고치면 서버를 다시 시작해야 반영된다(새 세션 또는 `/mcp` 재연결).
- 로그는 stderr 전용. stdout에 print하면 MCP 프로토콜이 깨진다.

## MCP 툴 (8개)

| 툴 | 하는 일 |
|---|---|
| `find_company(name)` | 회사명 부분일치 → corp_code (상장사 우선) |
| `search_disclosures(corp_code, bgn_de, end_de, pblntf_ty)` | 기간별 공시 목록 (A 정기, B 주요사항, … J 공정위) |
| `get_latest_reports(corp_code)` | 최근 2년 정기공시에서 최신 사업보고서 + 그 이후 반기·분기보고서(reprt_code 포함). 정정본 우선, 원본은 superseded |
| `get_disclosure_outline(rcept_no, file_id, depth)` | 파일·섹션 목차와 섹션별 글자 수. depth=3이면 주석 소제목(`4.3.t12`)까지 |
| `get_disclosure_section(rcept_no, section_id, file_id, max_chars, offset)` | 한 섹션의 Markdown 본문(나눠 읽기 가능) |
| `search_in_disclosure(rcept_no, query, file_id)` | 원문 키워드 위치(section_id, offset)와 앞뒤 문맥 |
| `get_financial_statements(corp_code, bsns_year, reprt_code, fs_div, sj_div)` | BS/IS/CIS/CF 전체 계정(원 단위) |
| `get_key_financials(corp_code, bsns_year, fs_div, reprt_code, period_type)` | 핵심 10계정 + 비율. 사업보고서는 3개년(`annual`), 반기·분기는 당기 vs 전년 동기(`cumulative`/`quarter`). 업종(`sector`)을 판단해 금융업이면 `warning`과 금융 계정을 준다 |

## 슬래시 커맨드 (`.claude/commands/`, 6개)

| 커맨드 | 한 줄 설명 |
|---|---|
| `/dart-analyze <회사> [연도]` | 종합 기업분석: 사업 구조·3개년 재무·최근 분기 동향·경영진 관점·리스크·지배구조 |
| `/dart-financial <회사> [연도]` | 재무 심층: 수익성·안정성·현금흐름 + 주석(차입금·충당부채·우발·특수관계자) |
| `/dart-risk <회사> [연도]` | 리스크 전용: 위험관리·우발부채·소송·제재·감사의견(KAM) 매트릭스 |
| `/dart-compare <회사1> <회사2> [<회사3>] [연도]` | 2~3사 비교: 3개년 핵심 지표 같은 행 비교 + 경영진 전망 |
| `/dart-event <rcept_no>` | 수시공시 한 건 요약과 직전 1년 유사 공시 비교 |
| `/dart-review <보고서.md>` | 독립 서브에이전트 리뷰: 출처 누락·재무 API 재대조·원문 샘플 5개·표현 오류·"추정:" 누락 → `.review.md` |

- 연도를 생략하면 `get_latest_reports`로 최신 사업보고서를 고르고, 이후 반기·분기보고서가 있으면 "최근 분기 동향"(전년 동기 비교만)을 붙인다.
- analyze/financial/risk/compare는 마지막에 `/dart-review`를 1회 돌리고 FAIL을 반영해 "리뷰 반영 내역"을 남긴다.
- 표현 오류 정규식 점검은 단독으로도 쓸 수 있다: `uv run python -m dart_mcp.report_lint reports/<보고서>.md`

## 캐시 구조 (`data/`, git 제외)

```
data/corp_codes.json                          기업코드 전체(7일 캐시)
data/<rcept_no>/<rcept_no>.zip                공시 원본 ZIP (불변, 만료 없음)
data/<rcept_no>/*.xml, *.md                   추출 XML·변환 Markdown
data/<rcept_no>/outline.json                  목차(본문 제외)
data/<rcept_no>/sections_<file_id>.json       섹션 본문
data/fin/<corp_code>_<연도>_<reprt_code>_<fs_div>.json   재무 API 원본 응답
data/company/<corp_code>.json                 기업개황(company.json: 시장구분 corp_cls, 업종 induty_code), 30일 캐시
```

섹션 규칙이 바뀌면 `cache.CACHE_VERSION`을 올린다. 버전이 다른 캐시는 저장된 ZIP으로 다시 만든다(API 재호출 없음).
재무 API의 "데이터 없음"(status 013)은 캐시하지 않는다.

## 알려진 한계

- **이미지 섹션**: 원문에 이미지로만 들어간 표·도표(조직도, 일부 그래프)는 텍스트가 없어 빈 섹션처럼 보인다.
- **계정명 매칭 실패 → missing**: 핵심 계정은 account_id → 계정명 완전일치 → 부분일치 순으로 찾는다. 회사 고유 계정명이라 못 찾으면
  값이 null이고 `missing`에 키가 들어간다. 이때는 `get_financial_statements`로 표를 직접 본다.
- **분기 데이터 누적 주의**: 반기·분기 응답에서 손익계산서는 `thstrm_amount`=당분기 3개월, `thstrm_add_amount`=누적이고,
  현금흐름표는 `thstrm_amount`가 이미 누적이다(3개월 값 없음). 재무상태표의 비교 열은 전년 동기말이 아니라 **직전 사업연도말**이다.
  `get_key_financials`는 `period_type`과 계정별 `basis`로 이를 구분하니, 분기 수치는 전년 동기와만 비교하고 연간 수치와 섞지 않는다.
- **금융업(은행·보험·증권·금융지주)**: 업종은 기업개황 `induty_code`(KSIC 64·65·66)로 판단한다. 64992(지주회사)는
  SK·LG 같은 비금융 지주도 같은 코드라서, 손익계산서에 순이자손익·보험수익·순수수료손익 계정이 있고 매출액 계정이 없을 때만 금융업으로 본다.
  금융업이면 `sector.sector="financial"`과 `warning`을 붙이고, `revenue`는 `not_applicable`(missing 아님), 영업이익률·순이익률은 null,
  대신 `financial_accounts`(순이자이익·순수수료이익·보험수익·신용손실충당금전입)를 준다. 업종별 계정 구성이 달라
  보험사에는 순이자이익·충당금 계정이 없을 수 있다(`financial_missing`). NIM·BIS비율·CET1·K-ICS 같은 업권 지표는 재무 API에 없어 계산하지 않는다.
  금융사의 부채비율(KB금융 2025 약 1,212%)은 예수부채·보험부채를 포함하므로 제조업과 비교하지 않는다.
- **현금및현금성자산**: 재무상태표에 해당 행이 없는 회사(은행의 "현금 및 예치금")는 현금흐름표의 기말 현금으로 대체하고 `matched.by`에
  "CF 기말현금 대체"라고 적는다. 반기·분기에서 이 값의 비교열은 전기말이 아니라 **전년 동기말**이다(`basis`에 표기).
- **연결 대상이 없는 회사**(예: 리노공업)는 연결재무제표가 없어 CFS 조회가 013이다. `fs_div="OFS"`로 받고 보고서에 "별도" 기준을 적는다.
  사업보고서의 "연결재무제표"·"연결재무제표 주석" 섹션은 수십 자짜리 빈 섹션으로 남는다.
- **감사보고서 첨부(00760/00761)의 주석은 소제목으로 쪼개지지 않는다.** 첨부 파일의 주석 번호는 TITLE 태그가 아니라 본문 문단
  (`<P>1. 회사의 개요리노공업…`)이라 제목과 본문이 붙어 있어 안전하게 자를 수 없다. 본문의 "재무제표 주석" 섹션(depth=3)을 쓰거나,
  첨부는 `search_in_disclosure(..., file_id="00760")`로 위치를 찍어 offset으로 읽는다. 2015년 이전 문서는 주석이 첨부에만 있다.
- **구형 공시(2012년 사업보고서 실측)**: XML 선언은 `utf-8`인데 실제 바이트는 cp949였다. 선언 → cp949 → utf-8 순으로 시도해
  대체문자 없이 읽힌다. 편집기 템플릿 태그(`COMMENT` "◆click◆ …", `LIBRARYLIST`, `FILENAME`, `WARNING`)가 본문에 섞여 있어 출력에서 뺀다(캐시 v3).
  재무 API(`fnlttSinglAcntAll`)는 2015년 이후만 있어 구형 공시의 숫자는 원문 표에서 단위 행을 확인해 옮겨야 한다.
- **회사명 검색**: DART 목록은 상장 약칭이다("KB금융", "신한지주"). 결과가 없으면 법인명 꼬리("지주", "지주회사", "주식회사", "(주)")를
  떼고 한 번 더 찾는다. "신한금융지주회사"처럼 약칭이 전혀 다른 경우는 여전히 못 찾으니 짧은 이름으로 다시 검색한다.
- **소형주 원문에는 없는 항목이 있다**: 리노공업 2025 사업보고서에는 시장점유율 기재가 없고, 주주 장(VII)에 하위 SECTION이 없어
  TITLE 소제목(`8.t1`, `8.t2`)으로만 나뉜다. 템플릿 항목이 원문에 없으면 "원문 기재 없음(검색 0건)"으로 적고 다른 섹션으로 메우지 않는다.
- 12월 결산이 아닌 회사는 `get_latest_reports`의 reprt_code·bsns_year를 결산월 기준으로 추정한다. 보고서명과 대조할 것.
- 디버그: `uv run python -m dart_mcp.cli fetch <rcept_no>` (원문 ZIP→XML→MD 저장).
