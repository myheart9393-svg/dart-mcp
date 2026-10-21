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
| `get_latest_reports(corp_code)` | 최근 2년 정기공시에서 최신 사업보고서 + 그 이후 반기·분기보고서(reprt_code 포함). 정정본 우선(`correction_kind`), 원본은 superseded, 과거 기간 늦은 정정은 `late_corrections` |
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

## 예시 보고서 (`reports/examples/`)

커맨드를 실제로 돌려 만든 산출물이다. `.review.md`는 같은 보고서에 대한 `/dart-review` 결과.

| 보고서 | 커맨드 | 무엇을 보여주나 |
|---|---|---|
| [삼성전자 종합분석 (2025 사업보고서)](reports/examples/삼성전자_종합분석_2026-10-19.md) · [리뷰](reports/examples/삼성전자_종합분석_2026-10-19.review.md) | `/dart-analyze 삼성전자` | 연도 생략 → `get_latest_reports`로 최신 사업보고서 + 반기 동향 |
| [삼성전자 종합분석 (2025, 초판)](reports/examples/삼성전자_종합분석_2025연도_2026-10-18.md) · [리뷰](reports/examples/삼성전자_종합분석_2025연도_2026-10-18.review.md) | `/dart-analyze 삼성전자` | 같은 공시의 이전 실행(`get_latest_reports` 도입 직후 첫 실행) |
| [삼성전자 종합분석 (2024)](reports/examples/삼성전자_종합분석_2026-10-18.md) | `/dart-analyze 삼성전자 2024` | 재무 API 도입 전 버전(숫자를 원문에서 옮김) |
| [삼성전자 재무 교차검증](reports/examples/삼성전자_재무교차검증_2026-10-18.md) | (수동) | 위 2024 보고서의 원문 숫자 vs 재무 API 대조 → "숫자는 API" 원칙의 근거 |
| [리노공업 종합분석 (2025, 별도)](reports/examples/리노공업_종합분석_2026-10-19.md) · [리뷰](reports/examples/리노공업_종합분석_2026-10-19.review.md) | `/dart-analyze 리노공업` | 코스닥 소형주, 종속회사 없음 → CFS 013 → OFS, "원문 기재 없음" 처리 |
| [삼성전자 vs SK하이닉스](reports/examples/비교_삼성전자_SK하이닉스_2026-10-18.md) · [리뷰](reports/examples/비교_삼성전자_SK하이닉스_2026-10-18.review.md) | `/dart-compare 삼성전자 SK하이닉스 2024` | 2사 3개년 지표 같은 행 비교 |
| [삼성전자 자기주식 취득 결정](reports/examples/삼성전자_수시공시_20250708000011.md) | `/dart-event 20250708000011` | 수시공시 한 건 3단 요약 |

리뷰어 성능 시험은 `reports/_test/`에 있다: 오류 7개를 심은 비교 보고서와 정답지, 리뷰 결과,
[scorecard.md](reports/_test/scorecard.md)(검출 7/7, 오탐 0).

## 캐시 구조 (`data/`, git 제외)

```
data/corp_codes.json                          기업코드 전체(7일 캐시, 아래 참고)
data/<rcept_no>/<rcept_no>.zip                공시 원본 ZIP (불변, 만료 없음)
data/<rcept_no>/*.xml, *.md                   추출 XML·변환 Markdown
data/<rcept_no>/outline.json                  목차(본문 제외)
data/<rcept_no>/sections_<file_id>.json       섹션 본문
data/fin/<corp_code>_<연도>_<reprt_code>_<fs_div>.json   재무 API 원본 응답, 90일 캐시(정정 의심 시 refresh=True)
data/company/<corp_code>.json                 기업개황(company.json: 시장구분 corp_cls, 업종 induty_code), 30일 캐시
```

섹션 규칙이 바뀌면 `cache.CACHE_VERSION`을 올린다. 버전이 다른 캐시는 저장된 ZIP으로 다시 만든다(API 재호출 없음).
재무 API의 "데이터 없음"(status 013)은 캐시하지 않는다.

**`data/corp_codes.json` 생성·갱신 규칙**
- 생성: 처음 `find_company`를 부를 때 OpenDART `corpCode.xml`(전체 법인 ZIP, API 1건)을 받아 만든다. 약 13MB, 11만여 법인.
  파일 안의 `fetched_at`(epoch 초)이 생성 시각이다. 저장소에 커밋하지 않으므로 클론 직후에는 없다.
- 갱신: `fetched_at`이 **7일**(`client.CORP_CODES_MAX_AGE_DAYS`)을 넘으면 다음 `find_company` 호출 때 자동으로 다시 받는다.
  그 전에는 API를 쓰지 않는다.
- 수동 갱신: 신규 상장·사명 변경 직후 회사가 안 잡히면 `data/corp_codes.json`을 지우고 `find_company`를 다시 부른다.
- 만료 후 재다운로드가 실패하면(키 오류·네트워크) 옛 파일로 대체하지 않고 `{"error": ...}`를 돌려준다.

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
- **구형 공시(2012년 사업보고서 실측)**: XML 선언은 `utf-8`인데 실제 바이트는 cp949였다. utf-8(엄격) → cp949 → 선언 순으로 시도해
  대체문자 없이 읽힌다(utf-8은 자기검증이 되지만 cp949는 거의 모든 바이트를 읽어 버려 거짓 선언을 못 잡기 때문). 편집기 템플릿 태그(`COMMENT` "◆click◆ …", `LIBRARYLIST`, `FILENAME`, `WARNING`)가 본문에 섞여 있어 출력에서 뺀다(캐시 v3).
  재무 API(`fnlttSinglAcntAll`)는 2015년 이후만 있어 구형 공시의 숫자는 원문 표에서 단위 행을 확인해 옮겨야 한다.
- **표 머리글**: 첫 행이 전부 TH이거나 THEAD 안일 때만 Markdown 머리글로 쓰고, 아니면 빈 머리글 행(`| | |`)을 넣는다(캐시 v4).
  DART 원문은 머리글을 TD/TE로 쓰는 표가 많아 삼성전자 2025 사업보고서 본문 2,071개 표 중 787개가 빈 머리글이 되며,
  그중 일부(약 100개)는 첫 데이터 행이 실제 열 제목("구분 | 결산배당 | …")이다. 첫 행을 열 제목으로 읽을지는 내용을 보고 판단한다.
- **회사명 검색**: DART 목록은 상장 약칭이다("KB금융", "신한지주"). 결과가 없으면 법인명 꼬리("지주", "지주회사", "주식회사", "(주)")를
  떼고 한 번 더 찾는다. "신한금융지주회사"처럼 약칭이 전혀 다른 경우는 여전히 못 찾으니 짧은 이름으로 다시 검색한다.
- **소형주 원문에는 없는 항목이 있다**: 리노공업 2025 사업보고서에는 시장점유율 기재가 없고, 주주 장(VII)에 하위 SECTION이 없어
  TITLE 소제목(`8.t1`, `8.t2`)으로만 나뉜다. 템플릿 항목이 원문에 없으면 "원문 기재 없음(검색 0건)"으로 적고 다른 섹션으로 메우지 않는다.
- 12월 결산이 아닌 회사는 `get_latest_reports`의 reprt_code·bsns_year를 결산월 기준으로 추정한다. 보고서명과 대조할 것.
- **결산기 변경 회사**: reprt_code는 최신 사업보고서의 결산월 기준 경과 개월수(3·6·9)로 정하므로, 결산기를 바꾼 회사는
  변경 전 기간의 분기·반기보고서 reprt_code가 틀리거나 null일 수 있다. null을 `get_key_financials`에 넘기면
  "reprt_code가 null입니다…" 에러가 나니 `search_disclosures`로 기간을 확인해 직접 넣는다.
- **정정본 구분**: `get_latest_reports`는 `correction_kind`로 `[기재정정]`(본문·재무제표가 바뀌었을 수 있음)과
  `[첨부정정]`·`[첨부추가]`(감사보고서 등 첨부만)를 나눈다. `is_correction`은 기재정정만 True.
  최신 사업보고서 접수 뒤에 과거 기간 정정본이 나오면 `late_corrections`에 담긴다(전기 재무제표 재작성 신호일 수 있음).
- 디버그: `uv run python -m dart_mcp.cli fetch <rcept_no>` (원문 ZIP→XML→MD 저장).

## 운영

### 세션 시작 체크리스트

1. Claude Code에서 `/mcp` → `dart`가 **connected**인지 본다. failed면 `.mcp.json`의 uv.exe 절대경로와 `.env`의 `DART_API_KEY`를 확인한다.
2. 툴이 **8개** 다 보이는지 본다: `find_company`, `search_disclosures`, `get_latest_reports`, `get_disclosure_outline`,
   `get_disclosure_section`, `search_in_disclosure`, `get_financial_statements`, `get_key_financials`.
   (ToolSearch `select:mcp__dart__get_latest_reports`처럼 이름으로 확인할 수 있다. `get_latest_reports`가 마지막에 추가된 툴이라 옛 서버면 이것부터 빠진다.)
3. 안 보이거나 서버 코드를 고친 뒤라면 `/mcp`에서 **reconnect**(또는 새 세션). 재연결 뒤에도 툴 목록이 옛 것일 수 있으니 2를 다시 본다.

### API 호출량 (하루 한도 20,000건 기준)

OpenDART 인증키 하나당 하루 20,000건이다. 아래는 `/dart-analyze <회사>`(연도 생략)의 툴 호출 순서를
임시 캐시 디렉터리에서 그대로 재현해 OpenDART HTTP 요청을 센 실측값이다(2026-10-19, 리뷰 단계의 `get_key_financials` 재조회 포함).

| 경우 | 삼성전자 (연결) | 리노공업 (종속회사 없음 → OFS) |
|---|---|---|
| 캐시 미스 (첫 분석) | **6건**: corpCode 1 · list 1 · 재무 2(사업+반기) · company 1 · document 1 | **7건**: corpCode 1 · list 1 · 재무 3(CFS 013 + OFS 사업 + OFS 반기) · company 1 · document 1 |
| 캐시 히트 (재분석) | **1건**: list 1 | **2건**: list 1 · 재무 1(CFS 013 재확인) |

- 원문 섹션 읽기·검색(`get_disclosure_section`, `search_in_disclosure`)과 depth를 바꾼 outline은 저장된 ZIP으로 처리해 API를 쓰지 않는다.
  섹션을 몇 번 읽든 공시 1건당 `document.xml` 1건이다.
- `list.json`(공시 목록)은 캐시하지 않으므로 `get_latest_reports`·`search_disclosures`는 매번 1건(결과 100건마다 1건 추가).
- status 013은 캐시하지 않으므로 OFS 회사는 CFS를 먼저 부를 때마다 1건씩 더 쓴다. OFS 회사임을 알면 처음부터 `fs_div="OFS"`.
- corpCode는 7일에 1건, company는 회사당 30일에 1건.
- 연도를 지정하면 `search_disclosures` 1건이 `get_latest_reports`를 대신하고 반기 조회가 빠져 미스 5건(OFS 6건)이다.
  `/dart-compare` 3사는 대략 회사 수 × 위 값. 네트워크 오류·5xx 때의 재시도(요청당 최대 3회 시도)도 건수에 들어간다.
- 결론: 한도에 걸릴 일은 사실상 없다(전부 캐시 미스여도 하루 약 2,800–3,300회 분석). 한도 초과 시 OpenDART는 status 020을 주고 툴은 `{"error": ...}`를 돌려준다.

### 흔한 실패와 대처

| 증상 | 원인 | 대처 |
|---|---|---|
| `get_key_financials`가 `rcept_no: null`, message에 "조회 데이터 없음(status 013)" | 연결 대상 종속회사가 없는 회사(CFS가 없음), 또는 그 연도·보고서 종류 데이터가 아직 없음 | `fs_div="OFS"`로 재호출하고 보고서에 "별도 기준" 명시. OFS도 013이면 연도(`bsns_year`)·`reprt_code`를 확인한다(2015년 이전은 재무 API 자체가 없음) |
| `find_company`가 `count: 0` | DART 목록은 상장 약칭이다("KB금융", "신한지주"). 툴은 이미 법인명 꼬리("주식회사", "(주)", "지주회사", "지주")를 떼고 한 번 더 찾은 뒤의 결과 | 더 짧은 핵심 단어로 다시 검색("신한금융지주회사" → "신한"). 동명 회사가 많으면 `stock_code`가 있는 행을 고른다. 최근 상장·사명 변경이면 `data/corp_codes.json`을 지우고 재시도 |
| 같은 기간 사업보고서가 여러 건(원본 + `[기재정정]` + `[첨부추가]` …) | 정정공시 | `get_latest_reports`는 같은 종류·같은 기간(report_nm의 "(2025.12)") 중 **접수일(rcept_dt)이 가장 늦은 것, 같으면 rcept_no가 큰 것**을 쓰고 나머지는 `superseded`로 돌린다. 연도를 지정해 `search_disclosures`로 직접 고를 때도 같은 규칙(가장 늦은 정정본)을 따른다 |
| 툴이 없다 / 인자가 없다는 에러 | 옛 서버 프로세스 | 위 체크리스트 3 |
| `{"error": "... DART_API_KEY가 없습니다"}` | `.env` 없음 | `.env.example`을 복사해 키 입력 후 재연결. 캐시된 공시는 키 없이도 읽힌다 |

### 새 회사 분석 전 권장 순서

1. `find_company("<회사>")` → stock_code가 있는 정확 일치 행의 corp_code.
2. `get_latest_reports(corp_code)` → 최신 사업보고서 rcept_no·bsns_year, 이후 반기·분기, 정정본 선택 결과 확인.
   12월 결산이 아니면 report_nm의 결산월과 bsns_year가 맞는지 본다.
3. `get_disclosure_outline(rcept_no, depth=2)`로 구조를 한 번 본다: 장 제목이 표준(I~XII)인지, "연결재무제표" 섹션이 수십 자짜리 빈 섹션인지
   (→ OFS 회사), 30,000자를 넘는 섹션이 어디인지, 하위 SECTION 없이 TITLE 소제목(`8.t1`)만 있는 장이 있는지.
4. 그다음 `/dart-analyze`·`/dart-financial`·`/dart-risk` 등 커맨드를 실행한다. 1~3의 결과는 캐시에 남아 커맨드가 다시 부를 때 API를 쓰지 않는다
   (`get_latest_reports`의 목록 조회 1건 제외).
