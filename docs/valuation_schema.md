# 가치평가 사례 스키마 (`src/dart_mcp/valuation_schema.json`)

`/dart-valuation <rcept_no>`가 공시 한 건에서 뽑는 사례 JSON의 형식. 저장 위치는 `reports/valuations/<rcept_no>.json`
(rcept_no = 본문을 읽은 최신 접수번호 `body_rcept_no`). 검증은 `uv run python -m dart_mcp.valuation validate <파일>`.

## 대원칙

1. **원문에 없으면 null. 추정하지 않는다.** 계산으로 빈칸을 채우지 않는다(검산은 리뷰가 한다).
2. **숫자는 전부 `{"value", "unit", "text", "cite"}`.** `text`는 원문 표기 그대로("8.1543%", "261,345"), `unit`은 원문 단위
   (원·백만원·%·배·주) 그대로이고 **환산하지 않는다.** value가 숫자면 cite가 반드시 있어야 한다(스키마가 강제).
3. **cite = `{section_id, offset, file_id[, rcept_no]}`.** offset은 그 섹션 텍스트 기준(get_disclosure_section·find_tables와 같다).
   section_id는 가능하면 SECTION 단위("5", "7")를 쓴다. `.hN` 휴리스틱 소제목 id는 파서가 바뀌면 달라질 수 있다.
4. **평가 주체 × 대상 × 방법 하나가 valuations 원소 하나.** 같은 문서의 WACC가 여럿이면(알테오젠: 안진 7.7%·9.7%, 신우 8.1543%·9.7546%,
   이촌 8.43%) 원소를 나눈다. 회의록·Q&A에 인용된 값은 원 평가 원소에 섞지 않고 notes에 위치와 함께 적는다.
5. `source_grade`: `full` = 증권신고서(가정까지 본문에 있다), `summary` = 주요사항보고서(API ZIP에 평가의견서 첨부가 없어
   본문 "외부평가에 관한 사항" 5행과 결론만 있다. 할인율·g·베타·멀티플은 보통 null).

6. **범위 `{min, max}`는 숫자 크기 순서**(min ≤ max). 원문이 "29.83% ~ 11.74%"처럼 큰 값을 먼저 써도 그렇다. `validate`가
   min > max를 오류로 잡는다(JSON Schema는 값 비교를 못 해 `valuation.range_order_errors`로 검사).
   `validate`는 값 분포 밖(WACC 0–30% 밖, g ≥ WACC, g > 5%, 멀티플 ≤ 0, 할인율 0–70% 밖)을 `warnings[]`로 따로 준다 — 오류가 아니라 원문 대조 대상.
   **회계 항등식**(`identity_checks`, 경고): a β 재조정 βL=βu×(1+(1−t)×D/E)(어긋나면 D/E↔D/V 반대 해석·세율 9.9–27.5% 범위 확인),
   b Ke=rf+β×MRP+규모위험, c WACC=Ke×(1−D/V)+Kd×(1−t)×D/V, d 본질가치 가중평균(상증법은 순자산 80% 하한), e 기준시가(입력 필드 없음 → skip),
   f 합병·교환비율=주당 가액의 비(분할합병 skip), g 자본총계+조정항목=조정 순자산. 허용오차: 금리·β는 max(상대 0.5%, 표시 자릿수 반올림 전파),
   금액(d·f·g)은 표시 자릿수 반올림 전파만.
7. **통계는 거래 단위**: `valuation stats`는 거래(rcept_no)마다 대표값 하나 — 외부평가 역할 값(여럿이면 그 중앙값), 없으면 그 거래 값들의 중앙값.

## 최상위

| 필드 | 뜻 |
|---|---|
| rcept_no / original_rcept_no / related_rcept_nos | 추출에 쓴 접수번호 / 최초 제출본 / 같은 거래 짝(주요사항보고서↔증권신고서) |
| filing_type, report_nm, source_grade | 주요사항보고서·증권신고서, 원문 보고서명, full·summary |
| company | corp_code, name, market(유가증권·코스닥·코넥스·기타), induty_code(KSIC, 조회용) |
| deal | type(merger·split·split_merger·business_transfer·share_exchange·ipo·rights_offering), counterparty, counterparty_listed, related_party, relation_text(원문 "회사와의 관계"), board_date, regime, ratio_text |
| external_valuation | required, exemption_reason, basis_text(원문 "근거 및 사유" 그대로, 항 번호를 고치지 않는다), firm, firm_type, period, audit_committee_consent, standards_cited[], opinion_text, cite |
| valuations[] | 아래 |
| conclusion | price_per_share[{company, basis, value}], range[{label, subject, range}], ratio, transaction_value, opinion_text, unit |
| sensitivity[] | {subject, target, variables, range} |
| ipo | underwriter, method, multiple_type, excluded_multiples[], applied_earnings(+basis), multiple, shares, value_per_share, discount_range, price_band, peers[], external_comparison |
| citations[] | 읽은 섹션 {rcept_no, file_id, section_id, title, chars_read, how} |
| notes[] | 원문 한계·짝 공시·회의록 인용값 등(추정은 쓰지 않는다) |
| source_inconsistent[] | {check, path, note}: 원문 자체가 회계 항등식에 안 맞는 곳(값은 원문대로). `validate`가 이 경고를 따로 센다 |
| extracted_at, extractor_version | ISO8601(+09:00), `dart_mcp.valuation.EXTRACTOR_VERSION` |

`status`·`status_source`·`status_checked`: 거래 상태(`진행`·`완료`·`철회·중단`·`미확인`, IPO는 null)와 근거 공시·판정일.
`uv run python -m dart_mcp.valuation status reports/valuations`가 같은 회사의 이후 공시 목록(list.json, 원문 안 받음)으로 채운다 —
완료 = 증권발행실적보고서(합병등)·합병등종료보고서, 철회 = "…결정 철회"·철회신고서(바로 앞 증권신고서가 같은 유형). 본문 접수 후 270일 안에 둘 다 없으면 진행, 지나면 미확인.

`regime`: `"기준시가"`(현행 176조의5 ①: 상장사 기준시가, 비상장사 본질가치) · `"공정가액(2026.12.9 개정)"`(2026.9.8 개정 자본시장법, 2026.12.9 이후
이사회 결의분부터 — 알테오젠 증권신고서 기재) · `"IPO"` · null(원문으로 판단 불가).

## valuations[] 원소

| 필드 | 뜻 |
|---|---|
| subject / target / role | 평가 주체 / 대상 회사·사업부 / 외부평가·재무자문·주관사·회사(당사회사가 협의·제시한 가액) |
| purpose | 합병가액·분할·교환비율·양수도가액·공모가·공정가치평가·손상검사·기타. 공정가치평가(예: IPO 신고서의 RCPS 평가)·손상검사는 조회·통계 기본값에서 빠진다 |
| method | DCF·DDM·이익할인·본질가치·기준시가·상대가치·자산가치 |
| weights | {asset, income, basis}. 본질가치는 1:1.5(시행세칙 제4조). 원문이 40%·60%로 쓰면 0.4·0.6 |
| asset_value | per_share, total(조정 순자산), equity_book(직전 사업연도말 자본총계), adjustments, shares, base_date |
| income_value | 본질가치 원소의 주당 수익가치(점 값). 범위만 있으면 null, 범위는 같은 주체의 DCF 원소 result.range |
| dcf | forecast_years, base_date, wacc, rf, mrp, beta_unlevered, beta_levered, size_premium, ke, kd(세전), tax_rate, target_de(D/E), target_dv(D/(D+E)), g, peers[] |
| relative | multiple_type, peers[], multiple, applied_earnings, discount_range, not_applied_reason |
| result | value(점), unit, range(min·max) |
| note | 그 원소 해석에 필요한 원문 근거(예: "민감도 표 가운데 행, '기준' 표기 없음") |

## 법적 근거상 기재 항목 (스키마 뼈대의 출처)

자본시장법 시행령 제176조의5는 법령 조회로 확인했다(2026-10-13 시행본). 시행세칙 조항은 알테오젠 증권신고서에 인용된 원문으로 확인했다.
금감원 「외부평가업무 가이드라인」(2009.6)과 KICPA 「자본시장법에 따른 외부평가업무 수행기준」(2024.11)은 공시가 준수했다고 적는 기준이며,
가이드라인 문단 30(최근 2년 거래가격·과거 평가실적 고려)은 알테오젠 이촌회계법인 의견서에 인용돼 있다. 그 밖의 가이드라인 세부 항목은 원문 미확인이다.

| 근거 | 내용 | 스키마 필드 |
|---|---|---|
| 176조의5 ① 1호 | 기준시가 = 1개월·1주일 거래량가중 평균종가와 최근일 종가의 산술평균, ±10%(SPAC 30%) 할인·할증 | valuations(method=기준시가).result, note |
| 176조의5 ① 2호 가목 | 상장사는 기준시가, 자산가치에 미달하면 자산가치 가능 | asset_value.per_share, conclusion.price_per_share.basis |
| 176조의5 ① 2호 나목·② | 비상장사 = 자산가치와 수익가치 가중평균, 상대가치는 비교 공시 | weights, asset_value, income_value, relative(not_applied_reason) |
| 176조의5 ⑧ | 외부평가 의무 대상(계열사 합병 등)과 단서(발행주식 총수 소유·신주 미발행 시 제외) | external_valuation.required, exemption_reason, basis_text |
| 176조의5 ⑨ | 외부평가기관 = 인수업 인가 금융투자업자·신용평가회사·회계법인 | external_valuation.firm_type |
| 176조의5 ⑩ | 계열사 합병 시 외부평가기관 선정에 감사(위원회) 동의 | external_valuation.audit_committee_consent |
| 176조의5 ⑪·⑬ | 품질관리규정, 특수관계 평가 금지 | standards_cited, notes(독립성 문구) |
| 176조의5 ⑥ | 이사회 의견서(목적·합병가액·거래조건 적정성) | deal.board_date, notes |
| 176조의6 | 영업·자산 양수도, 분할합병, 주식교환에 준용 | deal.type, external_valuation |
| 시행세칙 제4조 | 자산가치:수익가치 = 1:1.5 | weights |
| 시행세칙 제5조 | 자산가치 = 직전 사업연도말 자본총계 ± 조정항목(무형자산·회수불능채권·손상차손·자기주식·증자·배당·잠재주식 등) ÷ 발행주식수 | asset_value.equity_book·adjustments·total·shares |
| 시행세칙 제6조 | 수익가치 = 현금흐름할인모형·배당할인모형 등 | dcf.*, method |
| 시행세칙 제7조 | 상대가치 = 유사회사(업종 동일, 3사 이상) 비교가치 평균의 30% 이상 할인 등 | relative.peers, not_applied_reason |
| 증권 인수업무 등에 관한 규정 제5조 | IPO 공모가 = 수요예측 등으로 인수회사·발행회사 협의 | ipo.*, external_valuation.basis_text(IPO) |

## 실측으로 정한 것 (2026-10)

- 주요사항보고서 ZIP(B001)에는 본문 XML만 있다(우성 원본·기재정정, 아센디오, 주성, 에스트래픽, 알테오젠 [첨부추가]). 평가의견서를 고친
  [첨부정정] 접수번호는 document.xml이 status=014. → summary 등급.
- list.json은 corp_code 없으면 3개월 한도, pblntf_ty를 같이 주면 pblntf_detail_ty가 무시된다 → search_valuation_disclosures는 상세유형만 준다.
- 증권신고서의 평가 섹션은 TITLE이 없어 depth=3에도 안 쪼개진다 → 5만 자 이상이면 `.hN` 휴리스틱 소제목(정기보고서·첨부 제외).
- 표 캡션·단위는 별도의 한 칸짜리 표로 온다 → find_tables가 다음 표에 붙인다.
