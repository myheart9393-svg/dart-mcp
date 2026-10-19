# dart-mcp

OpenDART(금융감독원 전자공시) 원문을 ZIP → XML → Markdown 텍스트로 뽑아내는 파이프라인.
최종 목표는 MCP 서버이지만, 현재 단계는 원문 추출/변환 핵심 모듈만 포함한다.

## 설치

```bash
uv sync
cp .env.example .env   # DART_API_KEY 입력
```

## 사용

```bash
uv run python -m dart_mcp.cli fetch <rcept_no> --out ./data/<rcept_no>/
uv run pytest
```
