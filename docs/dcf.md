# DCF 모델 (`dart_mcp.dcf`, `dart_mcp.dcf_xlsx`)

```bash
uv run python -m dart_mcp.dcf build reports/dcf/<회사>_assumptions.json --out reports/<회사>_DCF_<날짜>.xlsx [--verify]
uv run pytest -q tests/test_dcf.py
```

가정 JSON(`reports/dcf/오리온_assumptions.json`이 예시)이 유일한 입력이다. 과거 재무는 `collect_history`가
`data/fin` 캐시(재무 API, 기준연도·3년 전 사업보고서)에서 모은다.

## 모델링 규칙

- FCFF = EBIT × (1 − 법인세율) + 감가상각비 − CAPEX − 순운전자본 증가
- 추정기간 5년(가정 리스트 길이 5가 아니면 오류). 영구가치는 Gordon: TV = FCFF_N × (1 + g) / (WACC − g)
- 기중(mid-year) 할인: 할인계수 = 1 / (1 + WACC)^(t − `cf_timing_adj`), TV는 N − `tv_timing_adj`.
  기본 0.5 / 0.5. 연말 할인이면 0 / 0. **(오너 확인 필요: 실무 관행에 따라 수정)**
- 주주가치 = 기업가치 − 순차입금 + 비영업자산 − 비지배지분
  - 순차입금 = 차입금·사채 + 리스부채 − (현금 + 단기·장기금융예치금 + 유동 FVPL)
  - 비영업자산 = 지분법투자 + 투자부동산 + FVOCI 지분상품 (장부가)
- **리스: 방법 2(영업비용 관점, 구 운용리스 방식)로 일관 처리.** 두 관점을 섞으면(상각비 가산 + 리스부채 차감 +
  신규 리스 미차감) 미래 리스료가 어디에도 반영되지 않는다.
  - 감가상각비에 사용권자산 상각비를 넣지 않는다(보고 영업이익에 이미 차감돼 있음). 과거재무에는 참고 행으로만 표시.
  - 리스부채 이자비용을 EBIT에서 뺀다: EBIT = 보고 영업이익 − 리스 이자. 기준연도 이자는 `lease.base_interest`
    (재무API에 없어 원문 주석에서 입력), 추정은 `forecast.lease_interest_pct`(매출 대비).
  - 사용권자산 취득은 CAPEX에 넣지 않는다. 리스부채는 순차입금·WACC 타인자본에서 제외(DCF 시트에 참고 행).
  - EBITDA = EBIT(리스료 차감 후) + 감가상각비. 내재 EV/EBITDA를 비교회사와 볼 때 같은 기준(리스료 차감 후, 리스부채 제외 EV)으로 맞춘다.
- g ≥ WACC면 엔진은 `ValueError`, 엑셀 TV·민감도 칸은 `#N/A`, 체크 행 `g < WACC`가 1(빨강).
- 부호: 법인세·CAPEX·순운전자본 증가는 양수, 수식에서 차감.
- 단위: 백만원. DART 원 단위는 `collect_history`(`_extract`)에서 한 번만 환산. 주당 가치 환산(원/백만원)도 가정 입력.
- 모든 가정(법인세율·WACC 구성·g·할인시점·민감도 간격)은 가정 JSON → 가정 시트 입력 셀. 코드 상수 없음.

## Excel 규칙

- 시트: `가정`, `과거재무`, `추정`, `DCF`, `민감도` (이 순서, 이 이름만)
- 입력값은 `가정` 시트에만(과거 재무 입력·rcept_no 포함). 다른 시트 값 셀은 전부 수식. 수식 안 숫자는 0·1·ROUND 자릿수 4만.
- 입력 셀 파랑, 수식 셀 검정(머리행 연도 수식 포함).
- 민감도(WACC 7행 × g 5열): 데이터 표 없이 셀마다 닫힌 SUMPRODUCT 수식. 간격은 가정 입력.
- `DCF` 시트 하단 체크 행(0이 아니면 빨강): 자산 = 부채 + 자본(전 연도), 현재가치 합계(독립 재할인) = 기업가치,
  FCFF 재계산, EBIT = 보고 영업이익 − 리스 이자, 기준연도 감가상각비(사용권자산 제외) 원값 대조,
  순차입금(리스부채 제외) 원값 대조, 주주가치 브리지, 민감도 중앙 = 주당 가치, g < WACC.
- openpyxl은 수식을 계산하지 않는다. `--verify`와 `tests/test_dcf.py`는 LibreOffice headless로 재계산한 값과
  엔진 결과를 비교한다(상대오차 1e-9, 체크 행은 0). soffice가 없으면 테스트는 skip, `--verify`는 종료코드 1.
  `SOFFICE` 환경변수로 경로를 줄 수 있다.
