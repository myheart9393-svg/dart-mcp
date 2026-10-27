# dart-mcp

OpenDART 공시 원문을 섹션 단위로 읽는 MCP 서버(`dart`)와, 그 위에서 돌아가는 기업분석 슬래시 커맨드 프로젝트.
코드는 `src/dart_mcp/` (client / document / cache / financials / periodic / valuation / casebuild / batch / tables / report_lint / server / cli), 테스트는 `tests/`, 캐시는 `data/`(git 제외), 보고서는 `reports/`(가치평가 사례는 `reports/valuations/`).

```bash
uv run pytest -q                      # 단위테스트
uv run python -m dart_mcp.cli fetch <rcept_no>   # 원문 ZIP→XML→MD 저장 (디버그용)
```

```bash
uv run python scripts/parser_regression.py            # data/ 모든 XML 재변환 → data/_baseline과 섹션 비교 (--update로 갱신)
uv run python -m dart_mcp.healthcheck --sample 30 --seed 1   # 파서·재무 매칭 일괄 검사 → reports/healthcheck_<날짜>.md
```

**`document.py`를 고치면 커밋 전에 `scripts/parser_regression.py`를 돌려 변경 목록(바뀐 공시·섹션)을 커밋 메시지에 적는다.**
의도한 변경만 있으면 `--update`로 baseline을 갱신한다. 의도하지 않은 변경이 있으면 커밋하지 않고 원인부터 본다.

서버 코드(`server.py`, `document.py`, `cache.py`)를 바꾸면 MCP 서버 프로세스를 다시 시작해야 반영된다
(`financials.py`, `periodic.py`, `valuation.py`, `tables.py`도 마찬가지. 새 세션을 열거나 `/mcp`에서 재연결). 로그는 stderr 전용이며 stdout에 print 하면 프로토콜이 깨진다.

**재연결 규칙.** 재연결 뒤에도 세션의 툴 목록은 옛 것으로 남아 있을 수 있다. 서버를 고친 뒤 MCP 툴로 검증하기 전에
① 새로 추가·변경한 툴/인자가 툴 스키마에 보이는지 먼저 확인하고(ToolSearch `select:mcp__dart__<툴>`),
② 안 보이면 사용자에게 재연결(또는 새 세션)을 요청한다. 그 사이 꼭 필요하면 `uv run python -c "from dart_mcp import server; ..."`로
서버 함수를 직접 호출하되, 보고서·응답에 "MCP 대신 직접 호출"이라고 적는다. 옛 서버의 응답을 새 코드의 결과로 보고하지 않는다.

## dart MCP 툴 사용 원칙

사업보고서 한 건은 변환하면 150만 자가 넘는다. **원문 전체를 받는 툴은 없고, 만들지도 않는다.**

1. **큰 문서는 반드시 outline부터.** `find_company` → `search_disclosures`(연도 미지정이면 `get_latest_reports`) → `get_disclosure_outline` → 섹션 읽기 순서를 지킨다.
   섹션 id는 회사마다 다를 수 있으니 **제목으로 대조**해서 고른다.
2. **섹션을 읽기 전에 char_count를 본다.** 30,000자 이하면 `get_disclosure_section`으로 통째로 읽는다.
3. **30,000자를 넘으면 `search_in_disclosure`를 우선** 써서 키워드 위치(section_id, offset)를 찍고,
   그 하위 id나 offset 범위만 읽는다. 어쩔 수 없이 큰 섹션을 읽을 때는 max_chars/offset으로 나눈다.
4. **재무제표 주석은 depth=3으로.** `get_disclosure_outline(rcept_no, file_id="main", depth=3)`을 쓰면
   주석이 "1. 일반적 사항", "2. 중요한 회계처리방침" … 같은 소제목(id `4.3.t12`, kind="title")으로 쪼개진다.
   필요한 주석 번호만 `get_disclosure_section(rcept_no, "4.3.t12")`로 읽는다. 기본 depth=2는 소제목을 숨긴다.
5. **같은 섹션을 세션 중 두 번 읽지 않는다.** 이미 읽은 내용은 기억에서 쓴다.
6. **첨부 파일도 목차가 있다.** 감사보고서는 file_id "00760"(별도)/"00761"(연결) 같은 첨부에 있고,
   `get_disclosure_outline(rcept_no, file_id="00761")`로 그 파일만 볼 수 있다.
   정정 ZIP에는 바뀐 부분만 있으므로 본문은 `get_latest_reports`의 `body_rcept_no`, 감사보고서는 `attachment_rcept_no`로 연다
   (첨부정정 ZIP엔 본문이 없고, 기재정정 ZIP엔 감사보고서가 없을 수 있다). outline의 `parse_warnings`가 있으면 뒷부분 누락을 의심한다.
6-1. **감사보고서 첨부의 주석은 depth=3이어도 쪼개지지 않는다**(TITLE 태그 없음). 본문 "재무제표 주석" 섹션을 쓰거나 첨부는 search_in_disclosure로 찍어 offset으로 읽는다.
7. **에러는 `{"error": ...}`로 온다.** 없는 section_id면 available_ids가 함께 오니 그걸 보고 고친다. 재시도 전에 인자를 확인한다.
8. **숫자는 API, 서술은 원문.** 재무 숫자는 `get_key_financials`(핵심 10계정 + 비율, 3개년)나
   `get_financial_statements`(BS/IS/CIS/CF 전체 계정, 원 단위)로 받는다. 원문 III장 요약재무정보·본표는 읽지 않는다.
   캐시는 `data/fin/<corp_code>_<연도>_<reprt_code>_<fs_div>.json`(90일, 재무제표 정정이 의심되면 `refresh=True`). 출처는 `(rcept_no, 재무API)`.
   ROE·ROA는 평균잔액 기준이고 지배주주 계정이 있으면 지배주주 기준(`ratios.roe.basis`). `flags`에 `capital_impairment`가 있으면 자본잠식을 표 아래 명시.
   원문에서 숫자를 옮길 때는 표의 단위 행을 확인해 함께 적고, "USD 3,653억원"처럼 통화·단위를 섞지 않는다.
   **분기·반기**: `get_key_financials(..., reprt_code="11012"|"11013"|"11014", period_type="cumulative"|"quarter")`.
   결과는 current vs prior(손익=전년 동기, 재무상태표=직전 사업연도말)이고, 연간 수치와 한 표에 섞지 않는다.
   **금융업**: 응답에 `warning`이 있으면(sector="financial") 매출액·영업이익률 대신 `financial_accounts`(순이자이익 등)를 쓰고,
   보고서에 "금융업 기준"을 밝힌다. 일반 기업과 같은 비교 표에 넣지 않는다. 연결 조회가 013이면 `fs_div="OFS"`(종속회사 없는 회사).
9. 숫자·사실을 보고서에 쓸 때는 `(rcept_no, section_id)` 출처를 붙이고, 원문에 없는 해석은 "추정:"으로 표시한다.

### 공시유형 코드 (search_disclosures의 pblntf_ty)
A 정기공시 · B 주요사항보고 · C 발행공시 · D 지분공시 · E 기타공시 · F 외부감사관련 · G 펀드공시 · H 자산유동화 · I 거래소공시 · J 공정위공시
사업보고서는 결산연도 다음 해 3월에 접수된다 (2024 회계연도 → 2025-03, report_nm "사업보고서 (2024.12)").

## 분석 슬래시 커맨드 (`.claude/commands/`)

| 커맨드 | 한 줄 설명 |
|---|---|
| `/dart-analyze <회사명> [사업연도]` | 종합 기업분석. 사업 구조·3개년 재무 추이·경영진 관점·리스크·지배구조·종합 의견 |
| `/dart-financial <회사명> [사업연도]` | 재무 심층. 수익성·안정성·현금흐름 표 + 주석에서 차입금·충당부채·우발·특수관계자만 발췌 |
| `/dart-risk <회사명> [사업연도]` | 리스크 전용. 위험관리·우발부채·소송·제재·감사의견(강조사항·KAM)을 심각도/발생가능성 표로 |
| `/dart-compare <회사1> <회사2> [<회사3>] [사업연도]` | 2~3사 비교. 3개년 핵심 지표(API) 같은 행 비교 + 규모·성장·수익성·안정성 + 경영진 전망 |
| `/dart-event <rcept_no>` | 수시공시 한 건. 결정 내용·규모·주주 영향·직전 1년 유사 공시 비교를 3단 요약으로 |
| `/dart-review <보고서.md>` | 독립 서브에이전트 리뷰(출처·API 재대조·원문 샘플 5개·표현 오류·추정 표기) → `<보고서>.review.md` |
| `/dart-valuation <rcept_no>` | 가치평가 공시 한 건 → 사례 JSON(`valuation_schema.json`)+md. 평가 주체별 방법·WACC·g·β·멀티플·결론. 끝에 `/dart-valuation-review` |
| `/dart-valuation-scan <bgn> <end> [유형]` | 기간 안의 합병·분할·영업양수도·주식교환·IPO 공시 표(외부평가 여부·기관, 증권신고서 짝, 등급, 추출 여부). 추출 안 함 |
| `/dart-valuation-search <조건>` | `reports/valuations/*.json`을 조건으로 걸러 표 + **거래 단위** WACC·g·멀티플 분포("N건 거래, M개 값"). 기본은 거래가액 평가만(공정가치평가·손상검사 제외). 거래 10건 미만이면 "통계적 의미 제한". `--industry <KSIC 접두·대분류>`·`--regime`. 결과 rows의 status(진행·완료·철회·중단)는 빼지 않고 열로 |
| `/dart-valuation-batch <bgn> <end> [--grade full] [--limit N]` | 대상 큐(`dart_mcp.batch plan`) → 건마다 서브에이전트로 `/dart-valuation`, 실패는 기록하고 계속, 끝나고 무작위 20% 리뷰 → `_batch_<날짜>.md` |

### 가치평가 사례 규칙 (`/dart-valuation*`)
- **원문에 없으면 null. 추정 금지.** 빈칸을 계산·유추로 채우지 않는다. 숫자는 전부 `{value, unit, text, cite}`이고 단위는 원문 그대로(환산 금지).
- 평가 주체(외부평가기관·각 재무자문사·주관사·회사)가 다르면 valuations 원소를 나눈다. 회의록에 인용된 값은 notes로.
- 원소마다 `purpose`(합병가액·분할·교환비율·양수도가액·공모가·공정가치평가·손상검사·기타). 범위는 숫자 크기 순(min ≤ max, `validate`가 검사).
  JSON은 `dart_mcp.casebuild`(N/R/C/val — cite를 원문에서 직접 찾음)로 만든다.
- 통계는 거래 단위: 같은 거래의 값 여럿은 외부평가기관 값이 대표값(없으면 중앙값) — `uv run python -m dart_mcp.valuation stats reports/valuations [필터]`.
- 증권신고서(지분증권)의 IPO/유상증자는 corp_cls(조회 시점)로 못 가린다(올해 상장한 IPO는 K·Y, 상장폐지 회사의 유상증자는 E) → 본문 `equity_kind`.
- 주요사항보고서는 API ZIP에 평가의견서 첨부가 없다 → `source_grade="summary"`(5행+결론). 가정은 짝 증권신고서(full)에서 뽑는다.
- 큰 평가 섹션은 `find_tables(rcept_no, section_id, caption_pattern)`로 표부터, 나머지만 search_in_disclosure. 스키마 문서: `docs/valuation_schema.md`.
- 검증·조회 CLI: `uv run python -m dart_mcp.valuation validate|verify-cites|md <json>`, `... table|stats reports/valuations`.
  배치: `uv run python -m dart_mcp.batch plan|record|report`. MCP 재연결 전 툴 호출: `uv run python -m dart_mcp.casebuild call|grep|usage`.

공통 규칙: 보고서는 `reports/<회사명>_<종류>_<날짜>.md`로 저장, 마지막에 "참조한 섹션 목록" 부록,
원문 장문 복사 금지(표는 핵심 행만), 범위는 `4–5배`(en dash — `~` 두 개는 Markdown 취소선이 됨),
끝나면 `/dart-review` 1회 → FAIL 반영 → "리뷰 반영 내역", MCP 툴 호출 횟수와 읽은 총 글자 수를 작성/리뷰로 나눠 보고.
