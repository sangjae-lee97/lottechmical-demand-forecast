# 외부 산업지표 Batch 01 — KAMA 국내 자동차 생산·수출

작성: 2026-11-02 KST / 연구·데이터 접근 확인. **기존 예측코드/지원서/결과는 변경하지 않음.**

## 접근 결과

- **확인 성공:** KAMA 산업동향 공식 **확정 게시물 HTML**에서 8개 기준월 생산·수출 수치(16개 숫자)를 직접 확인하여 `work/data/external/kama_auto_monthly_transcribed_partial.csv`에 전사.
- **확인 미완료:** 월보 XLSX 게시물/파일명(예: [Monthly2026-09.xlsx](https://www.kama.or.kr/NewsController?board_id=971&boardmaster_id=Produce&cmd=V&menunum=0003))은 확인했지만 이번 환경에서 원본 XLSX 다운로드 실패. 정확한 파일 URL 및 접근 권한·워크북 셀/열/전체 기간은 검증 못함. KAMA 사이트 일부 메뉴에 유료회원 안내가 있으나 이로써 모든 공개 링크가 유료라고 단정할 수 없음.
- **24~36개월 확보 실패:** 아래는 **2025-09~12, 2026-05~06, 2026-08~09의 불연속 8개월**만 확인. 2026-01~04, 2026-07을 0으로 보간하거나 연속 데이터라고 표현하지 않는다. 나머지 과거 기간도 미확보.

## 이번 배치의 확인 숫자

| 기준월 | 생산(대) | 수출(대) | 확정 발표 게시일 | 출처 |
|---|---:|---:|---|---|
| 2025-09 | 334,289 | 228,189 | 2025-10-30 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12362&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2025-10 | 302,819 | 202,928 | 2025-11-27 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12365&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2025-11 | 354,204 | 236,560 | 2025-12-31 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12369&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2025-12 | 362,564 | 244,772 | 2026-01-29 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12374&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2026-05 | 329,533 | 230,264 | 2026-07-16 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12386&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2026-06 | 394,331 | 268,351 | 2026-07-28 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12388&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2026-08 | 206,036 | 146,989 | 2026-09-17 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12392&boardmaster_id=industry&cmd=V&menunum=0004) |
| 2026-09 | 346,564 | 237,403 | 2026-10-19 | [KAMA 확정](https://www.kama.or.kr/NewsController?board_id=12393&boardmaster_id=industry&cmd=V&menunum=0004) |

- 월보의 국내 완성차 7개사 기준과 수출의 통관/선적 정의는 [KAMA 월보 설명](https://www.kama.or.kr/NewsController?board_id=971&boardmaster_id=Produce&cmd=V&menunum=0003)을 참고. 위 정확한 숫자는 **산업동향 확정 발표 본문**을 전사함. 판매·생산·수출·국산/수입·금액의 범위 혼합 금지.
- 각 기준월 수치는 해당 **확정 발표일 이후**에만 입력으로 사용. 발표 시각이 확인되지 않아 월말 origin 테스트에는 게시 다음 날 기준으로 사용 권고.
- 발표일은 확정 게시물의 게시일이지 최초 잠정치 공개일이 아니다. 이 CSV를 과거 시점의 가장 이른 가용 정보라고 주장하지 않는다. 과거 백테스트는 실제 해당 origin 이전에 존재하던 판본만 사용.

## 배치 검증 결과

- 8행, 생산/수출 각각 8개 수치, 모든 단위 '대'.
- 기준월 8개 중복 없음, 음수·0·누락 수치 없음, 확정 게시일은 모두 기준월 이후.
- **연속성 미통과:** 2025-09에서 2026-09까지 총 13개월 중 5개월 누락(2026-01~04, 2026-07). 현재 상태는 모델 학습 불가.
- **근본적인 정답 부재:** 고객 소재 소비 C·B 전체 주문 O/R/I·롯데 자사 주문과의 조인키·BOM·공급비중 미확보. 산업지표로 실제 소비 복원 정확도를 평가할 수 없다.
- **원본 무결성:** XLSX 원본과 셀 대조를 수행하지 않았으므로 '원본 파일 검증' PASS라고 쓰지 않는다.

## 순차 추가시 확인할 것

1. 사용자의 로컬 Windows 또는 Codex 환경에서 KAMA XLSX 접근을 확인하고 원본을 정당한 방법으로 다운로드; 다운로드 성공·권한·다운로드 URL·SHA-256 및 시트 구조 검증.
2. 각 월별 첫 발표일·확정일·수정판 및 숫자 차이를 보존하고, 최근 24~36개월 **같은 범위**의 연속 수치를 우선 확보.
3. 자료 접근이 막힐 경우 산업통상부의 공식 월별 발표와 [KOSIS](https://kosis.kr/)에서 같은 정의의 보조 경로를 검토. 출처 혼용을 정당화하려면 집계 정의와 잠정·확정 차이를 별도 기록.
4. 지표가 확보돼도 현재 합성 `experiment.py`에 자동 연결하지 않는다. 실제 고객 C 정답이 없어 관련성/예측력 검증은 불가능하며, 수집 파이프라인 설계부터 분리 검토.
