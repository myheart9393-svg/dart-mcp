---
description: 보고서 md 한 건을 docx·pptx·html로 변환(LLM 없는 결정적 변환 + 숫자 검증). 사용법 /dart-export <보고서.md> [--docx] [--pptx] [--html] [--out reports/export/] [--style default]
argument-hint: <reports/보고서.md> [--docx] [--pptx] [--html] [--out 폴더] [--style 이름|경로]
---

# /dart-export $ARGUMENTS

`$ARGUMENTS`를 그대로 변환기에 넘긴다. **내용을 쓰거나 고치지 않는다. 변환은 스크립트가 하고, 원본 md는 수정하지 않는다.**

```bash
uv run python -m dart_mcp.export.cli $ARGUMENTS
```

- 형식 플래그가 없으면 셋 다 만든다. 출력은 `reports/export/<보고서명>.{docx,pptx,html}`.
- docx·pptx는 Node가 필요하다. `건너뜀 — Node 패키지 … 없다`가 나오면 `npm install --prefix src/dart_mcp/export`를 한 번 돌린 뒤 다시 실행한다.
  Node가 아예 없으면 html만 만들어지며, 건너뛴 형식과 사유를 사용자에게 알린다.

## 결과 처리

종료코드와 출력 줄을 그대로 보고한다.

- **0**: 형식별 경로와 "숫자 검증 통과"를 알린다.
- **1**: 빌드 실패이거나 숫자 검증 실패다. 누락·초과 숫자 목록을 그대로 보여 준다. 숫자 검증은 다음을 본다.
  - docx·html: md의 숫자 토큰이 개수까지 전부 있어야 한다.
  - pptx: 슬라이드·차트의 숫자가 전부 md에 있어야 한다.
  - 세 형식 공통: "추정:", 출처, 표본·경고, `4–5배` 범위, "이 보고서는 투자 권유가 아니다."의 개수가 줄면 안 된다.
- 검증 실패를 없애려고 md나 결과 파일을 손으로 고치지 않는다. 변환기 버그로 보고 원인을 찾는다.

## 스타일

`--style`은 `src/dart_mcp/export/styles/` 아래 이름 또는 JSON 경로다. 없는 키는 `default.json` 값을 쓴다.
키: `font`, `header`(머리글 문구), `footer`(바닥글 문구), `colors`(`navy`, `green`, `blue`, `accent`, `est`, `chart`). 기본은 머리글·바닥글 문구가 없다.
pptx는 쪽 번호 외의 문구도 숫자 검증 대상이라, `header`·`footer`에 md에 없는 숫자를 넣으면 검증이 실패한다.

## 참고

- 표지: md의 첫 H1(괄호 부분은 부제)과 첫 인용문, 그 안의 "작성일". 표 캡션: 표 바로 앞 제목·라벨, 없으면 `[표] N`.
- pptx는 H2마다 슬라이드를 만들고, 넘치면 "(계속)" 슬라이드로 나눈다. 3개년 이상 지표 표의 매출·이익률 행은 표 값 그대로 네이티브 막대 차트가 된다.
- 세로 폭에 들어가지 않는 넓은 표는 docx에서 가로 페이지에 들어간다. 숫자 검증은 화면 잘림을 보지 못하므로, 열이 많은 표는 결과를 열어 확인한다.
- docx 목차 쪽수는 `soffice`·`pdftotext`·`pdfinfo`가 모두 있을 때만 넣고, 없으면 생략한다.
