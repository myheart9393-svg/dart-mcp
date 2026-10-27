# 가치평가 사례 DB 사용법 (회계사용)

`reports/valuations/*.json`은 DART 합병·분할·주식교환·IPO 공시에서 평가 주체별 방법·가정·결론을 뽑은 사례다
(2026-10-27 기준 89건: IPO 64·합병 16·주식교환 5·분할 4, 공시 기간 2026-01–10). 조회는 Claude Code에서
`/dart-valuation-search <조건>`(자연어)로 하거나 아래 CLI를 직접 쓴다. CLI는 **거래 단위** 통계다: 한 거래에 값이 여럿이면
외부평가기관 값이 대표값(없으면 그 거래 값들의 중앙값). 결과는 항상 "N건 거래, M개 값"으로 읽는다.

```bash
uv run python -m dart_mcp.valuation stats reports/valuations [--from --to --deal-type --method --purpose --firm --regime]
```

## 조회 예시 5개

| # | 질문 | 명령 | 결과(2026-10-27) |
|---|---|---|---|
| 1 | 업종별 WACC | `stats … --deal-type merger --method DCF --regime 기준시가` 후 `rows[].induty_code` 앞 2–3자리(KSIC)로 거른다 | **현재는 쓸 수 없다**: induty_code가 89건 중 4건에만 있다(배치가 채우지 않음). 업종 없이 합병 DCF 전체는 14건 거래·55개 값, WACC 중앙값 11.09%(Q1–Q3 8.58–11.52%) |
| 2 | 특정 평가기관의 사례 | `stats … --firm 이촌` (외부평가기관 문구 또는 평가 주체에 포함) | 6건 거래·49개 값, WACC 중앙값 11.41%(8.43–17.59%), g 중앙값 1.0%. 외부평가 거래 수 순위는 결과의 `firms` |
| 3 | IPO 비교기업 선정 | `stats … --deal-type ipo` → `ipo.multiple_types`, 각 사례 JSON의 `ipo.peers[]`·`excluded_multiples` | 64건: PER 51·EV/EBITDA 10·PSR 2·PBR 1. PER 중앙값 24.96배, 할인율 하단·상단 중앙값 23.9%·37.8%. 비교기업명·배수는 `ipo.peers[]`(25건에 있음) |
| 4 | 본질가치 가중 | `stats … --method 본질가치` → 사례 JSON의 `valuations[].weights`·`asset_value`·`income_value` | 18건 거래·54개 원소. 가중치는 전부 자산 1 : 수익 1.5(시행세칙 제4조). 예: 보원케미칼(한미회계법인) 자산 2,133원·수익 8,197원 |
| 5 | 민감도 범위 | 사례 JSON의 `sensitivity[]` (`variables` 문구 + `range.min/max`) | 68개 표. 예: 보원케미칼(한미회계법인) WACC 10.77–11.77%·g 0.50–1.50% → 1주당 수익가치 7,210–9,396원 |

- 업종 조회(1)는 induty_code를 채운 뒤에 쓴다. 지금 업종을 보려면 `rows[].company`로 회사를 골라 사례를 하나씩 읽는다.
- 합병·분할·주식교환은 **반드시 `--regime`을 준다.** 2026.12.9 이후 이사회 결의분부터 공정가액 체계라 기준시가 사례와 한 분포로 보지 않는다
  (두 체계가 섞이면 결과에 `warning`). IPO는 `--deal-type ipo`만으로 충분하다.
- 공정가치평가(RCPS 등)·손상검사 원소는 기본값에서 빠진다. 넣으려면 `--purpose all`.

## 평가보고서에 인용할 때

모든 숫자에는 `cite = {rcept_no?, file_id, section_id, offset}`와 원문 표기 `text`가 있다. 인용은 다음 형식으로 쓴다.

> 보원케미칼 합병(한미회계법인) 민감도 1주당 수익가치 7,210–9,396원
> (출처: DART 접수번호 20260102000205, 「II. 합병 가액 및 그 산출근거」(section 5), offset 150323·150265, 원문 표기 "7,210"·"9,396")

- **접수번호**: cite에 rcept_no가 없으면 사례의 `rcept_no`. DART 뷰어 `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<접수번호>`에서 연다.
- **섹션 제목**: 사례 JSON `citations[]`에서 같은 section_id의 title. `file_id`가 main이 아니면 첨부 파일명도 적는다.
- **offset**은 dart-mcp가 변환한 섹션 텍스트 기준 글자 위치다(`get_disclosure_section(rcept_no, section_id, offset=…)`로 재현).
  DART 뷰어의 위치가 아니므로, 뷰어에서는 `text`(원문 표기)로 찾는다.
- 거래 단위 통계를 인용하면 조회 조건·기준일·"N건 거래, M개 값"을 함께 적는다
  (예: "2026-01–10 DART 합병 공시 기준시가 체계 DCF 14건 거래(55개 값), 거래별 대표값 중앙값 11.09%, dart-mcp 사례 DB 2026-10-27").

## 한계

- **summary 등급은 가정이 없다.** 주요사항보고서만 있는 사례는 평가의견서 첨부가 API ZIP에 없어 결론 5행뿐이고 WACC·g·β·멀티플이 null이다.
  분포에는 들어가지 않고 표에는 "원문 없음"으로 남는다(현재 89건 중 1건).
- **통계는 참고용이다.** 표본이 2026년 10개월치이고 IPO에 쏠려 있다(합병 DCF 14건 거래). 거래 10건 미만 조회는 "통계적 의미 제한".
  업종(induty_code)은 현재 4건에만 있다. 평가기관·주관사의 판단을 대신하지 않는다.
- **원문 확인 필수.** 추출은 LLM이 하고 무작위 20%만 독립 리뷰했다(배치 18건 PASS). `validate`의 `warnings`(WACC 0–30% 밖, g ≥ WACC,
  g > 5%, 멀티플 ≤ 0, 할인율 0–70% 밖)는 2026-10-27 현재 0건이지만, 값이 범위 안이라고 맞는 값은 아니다.
  평가보고서에 쓰는 숫자는 DART 원문에서 직접 확인하고 원문을 출처로 적는다. 사례 DB는 찾는 도구이지 출처가 아니다.
- 단위는 원문 그대로다(원·백만원·%·배). 합산·비교 전에 `unit`을 맞춘다.
