# 외부 지표 등록부 — Batch 01 (2026-11-02 KST)

> 설계 원칙: 대규모 지표 **수집·검증 Agent**와 **예측 모델의 변수 채택**을 분리한다. 현재 이 자료는 공식 KAMA 발표 본문의 소량 **수동 전사**이며 실제 고객 PC/ABS 소비나 롯데 주문 정답이 아니다.

| indicator_id | 지표명 | 단위/주기/모집단 | 역할 | 근거 | 현재 데이터 상태 |
|---|---|---|---|---|---|
| KAMA_KR_AUTO_PRODUCTION | 국내 자동차 완성차 생산량 | 대/월, KAMA가 집계한 국내 완성차 업체 생산 | 동행 산업활동 보조신호 후보. 공표 지연 시 후행 정보 | [KAMA 월보](https://www.kama.or.kr/NewsController?board_id=971&boardmaster_id=Produce&cmd=V&menunum=0003) | **확정 산업동향 HTML 8개 월 전사**, 원본 XLSX 미확보 |
| KAMA_KR_AUTO_EXPORT | 국내 자동차 완성차 수출량 | 대/월, 통관 또는 선적 기준, 회사 판매와 불일치 가능 | 동행/후행 산업활동 보조신호 후보. 생산과 중복 | 같은 KAMA 월보 | **동일 8개 월 전사**, 원본 XLSX 미확보 |

## 공통 데이터 계약

- 키: `indicator_id + period + release_vintage + publication_date + source_url`. 동일 기준월의 잠정·확정·수정판은 덮어쓰지 말고 판본 별도 저장.
- `period`: 수치의 실제 기준월(YYYY-MM). `publication_date`: 해당 **확정 발표 게시일**(Asia/Seoul 날짜). 정확한 게시 시각은 미확인.
- `available_at` 정책: 적어도 게시일 이후에만 사용. 시각이 없을 때는 보수적으로 게시 다음 날부터 입력 가능하게 관리. 현재 CSV의 `publication_date`는 `available_at` 자체가 아니다.
- `vehicle_production_units`, `vehicle_export_units` 모두 **대(수량)**. 금액(달러)·판매대수와 혼합하지 않는다.
- `source_type`: 이번 자료는 *산업동향 게시물 본문*, 월보 XLSX의 수치 셀을 검증한 것이 아니다.
- `extraction_method`: HTML 본문에 공개된 숫자를 사람이 전사. 공식 XLSX 파싱이나 API 자동 수집이 성공한 것처럼 표시 금지.
- 검증 조건: 단위 일치, 음수/결측/중복 검사, 게시일이 기준월 이후인지 검사, 긴 공백 월을 0으로 채우지 않음, 특정 시점에 공개되지 않은 후행 자료 누수 금지.
- **수요 연결**: 완성차 생산·수출은 일부 서로 중복되고, 차종/부품/BOM/소재 채택률·A–B 공급 배분을 몰라 PC/ABS 톤으로 직접 변환할 수 없다. 자동차 수출량과 생산량을 합산하지 않는다.
- 예측 유용성 평가: 실제 롯데 고객 주문 및 실제 소재 투입 정답이 확보된 다음, 동일 예측 기준 시점에서 각 지표의 추가 기여도를 기준모델과 비교. 그전에는 외부 지표 자체의 시간적 일관성과 접근성만 검증 가능.

## 추가 지표를 위한 스키마 제안

새 지표는 `indicator_id,period,value,unit,source_url,source_document_id,publication_date,available_at,vintage,status,collection_method,extraction_verified_at,scope,geography,aggregation,notes`의 **긴 형식(long-format)**으로 추가한다. 생산량/수출량을 묶은 이번 wide-format CSV는 2지표 첫 배치 검토용이며, 학습용 최종 스키마가 아니다.

**상태:** 24~36개월 연속 데이터 없음. 다음 수집에서 KAMA 원본 XLSX 파일 접근 권한·직접 URL·이전 월보 수치 검증을 우선. 실패하면 권한을 우회하지 말고 산업통상부 공개 산업동향/KOSIS 경로를 대조하되 서로 다른 정의나 잠정/확정 판본을 합쳐 쓰지 않는다.
