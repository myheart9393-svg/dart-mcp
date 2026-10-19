# dart-mcp

OpenDART 공시 원문을 섹션 단위로 읽는 MCP 서버(`dart`)와, 그 위에서 돌아가는 기업분석 슬래시 커맨드 프로젝트.
코드는 `src/dart_mcp/` (client / document / cache / server / cli), 테스트는 `tests/`, 캐시는 `data/`(git 제외), 보고서는 `reports/`.

```bash
uv run pytest -q                      # 단위테스트
uv run python -m dart_mcp.cli fetch <rcept_no>   # 원문 ZIP→XML→MD 저장 (디버그용)
```

서버 코드(`server.py`, `document.py`, `cache.py`)를 바꾸면 MCP 서버 프로세스를 다시 시작해야 반영된다
(새 세션을 열거나 `/mcp`에서 재연결). 로그는 stderr 전용이며 stdout에 print 하면 프로토콜이 깨진다.

## dart MCP 툴 사용 원칙

사업보고서 한 건은 변환하면 150만 자가 넘는다. **원문 전체를 받는 툴은 없고, 만들지도 않는다.**

1. **큰 문서는 반드시 outline부터.** `find_company` → `search_disclosures` → `get_disclosure_outline` → 섹션 읽기 순서를 지킨다.
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
7. **에러는 `{"error": ...}`로 온다.** 없는 section_id면 available_ids가 함께 오니 그걸 보고 고친다. 재시도 전에 인자를 확인한다.
8. 숫자·사실을 보고서에 쓸 때는 `(rcept_no, section_id)` 출처를 붙이고, 원문에 없는 해석은 "추정:"으로 표시한다.

### 공시유형 코드 (search_disclosures의 pblntf_ty)
A 정기공시 · B 주요사항보고 · C 발행공시 · D 지분공시 · E 기타공시 · F 외부감사관련 · G 펀드공시 · H 자산유동화 · I 거래소공시 · J 공정위공시
사업보고서는 결산연도 다음 해 3월에 접수된다 (2024 회계연도 → 2025-03, report_nm "사업보고서 (2024.12)").

## 분석 슬래시 커맨드 (`.claude/commands/`)

| 커맨드 | 한 줄 설명 |
|---|---|
| `/dart-analyze <회사명> [사업연도]` | 종합 기업분석. 사업 구조·3개년 재무 추이·경영진 관점·리스크·지배구조·종합 의견 |
| `/dart-financial <회사명> [사업연도]` | 재무 심층. 수익성·안정성·현금흐름 표 + 주석에서 차입금·충당부채·우발·특수관계자만 발췌 |
| `/dart-risk <회사명> [사업연도]` | 리스크 전용. 위험관리·우발부채·소송·제재·감사의견(강조사항·KAM)을 심각도/발생가능성 표로 |
| `/dart-event <rcept_no>` | 수시공시 한 건. 결정 내용·규모·주주 영향·직전 1년 유사 공시 비교를 3단 요약으로 |

공통 규칙: 보고서는 `reports/<회사명>_<종류>_<날짜>.md`로 저장, 마지막에 "참조한 섹션 목록" 부록,
원문 장문 복사 금지(표는 핵심 행만), 끝나면 MCP 툴 호출 횟수와 읽은 총 글자 수를 보고.
