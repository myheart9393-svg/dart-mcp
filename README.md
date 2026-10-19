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
| `get_key_financials(corp_code, bsns_year, fs_div, reprt_code, period_type)` | 핵심 10계정 + 비율. 사업보고서는 3개년(`annual`), 반기·분기는 당기 vs 전년 동기(`cumulative`/`quarter`) |

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
- 12월 결산이 아닌 회사는 `get_latest_reports`의 reprt_code·bsns_year를 결산월 기준으로 추정한다. 보고서명과 대조할 것.
- 디버그: `uv run python -m dart_mcp.cli fetch <rcept_no>` (원문 ZIP→XML→MD 저장).
