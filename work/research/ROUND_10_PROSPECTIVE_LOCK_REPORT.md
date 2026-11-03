# ROUND 10 — 미공표 실적 예측 고정

실행일: 2026-11-03 KST / Codex. 기준 계획 커밋 `1a035a9` 반영 후 실제 실행했다. **2개 업종×2개 목표월×3개 모델 = 12개 예측 생성·고정 성공. 현재 실적 채점은 하지 않았다.**

## 1. 공개 봉인 증거

| 항목 | 실제 기록 |
|---|---|
| 실험 | `PROSPECTIVE_LOCK_OF_UNRELEASED_ACTIVITY` |
| 실제 실행 원점 | **2026-11-03T16:50:18.307691+09:00** |
| 같은 원점 UTC | 2026-11-03T07:50:18.307691+00:00 |
| 예측 JSON 생성·고정 시각 | **2026-11-03T16:50:18.433777+09:00** |
| 예측 개수 | **12개**, `(업종, 목표월, 모델)` 중복 없음 |
| 실행 소스 커밋 | **`b258e99396b8a0ba36a89f3039fbb96d29344627`** — 코드·테스트를 먼저 커밋한 뒤 이 커밋에서 1회 실행 |
| 고정 JSON | 로컬 `work/data/local_only/round10_prospective/forecasts.canonical.json` |
| JSON SHA-256 | **`a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7`** |
| 원본·설정·소스 사본 | 데이터/근거/검증 기록 12개 + 소스·테스트·계획 6개 = **18개 파일**, 각각 해시 고정 |
| 현재 평가 상태 | `NOT_PERFORMED_NO_ACTUALS`; MAE·RMSE·편향·개선율 없음 |

이 보고서를 추가한 GitHub 커밋에 위 해시와 시각을 공개하여 봉인 증거를 남긴다. 최종 Push 커밋 SHA는 완료 메시지에서 별도 전달한다. SHA는 파일 내용의 동일성을 검증하며 **그 자체로 과거 생성 시각을 증명하지 않는다**. 위 시각은 실행 호스트 시계에 따른 실제 기록이다. Git 커밋 시각도 호스트 설정에 의존하며, GitHub 공개 커밋은 별도의 외부 확인 지점이다. 공인 타임스탬프·전자공증을 받은 것은 아니다.

## 2. 미래 실적 미포함·현재 입력 검증

- 현재 로컬 공식 KOSIS 원본·DSD에서 C222·C303 **각 57개월, 합계 114행**, 마지막 생산 기준월 **2026-09**를 확인했다. 원본의 TIME 태그를 먼저 검사하며 2026-10 이후 생산월이 하나라도 있으면 수치 사용 전에 중단하도록 했다. 두 목표월의 실적은 원본·학습자료·생성 JSON에 없다.
- KOSIS `101 / DT_1F02001 / A=00 / T10 / 2020=100`, C222·C303의 코드·항목·단위와 이전 ROUND 09 원본 해시를 검증했다. 기존 원본을 수정하지 않고 읽은 바로 그 바이트를 별도 봉인 폴더에 복사했다.
- ECOS `512Y008 / BD / C3000` 자동차와 `C0000` 제조업 전체의 **각 36개월, 총 72행**을 사용했다. 원 API 응답과 기존 정규화 값 전체를 대조하고 이전 manifest 해시를 확인했다.
- 최근 두 목표월×두 BSI의 **4개 값·공표일·보수적 이용 가능 시점**을 이전에 시각 검증한 PDF 전사 표본과 재대조했다. PDF와 전사 표본도 최초 보관 manifest와 해시가 일치했다. 새 시계열이나 새 생산 실적을 조회하지 않았다.
- 공표 근거는 [한국은행 2026년 9월 조사](https://www.bok.or.kr/portal/bbs/B0000501/view.do?menuNo=201264&nttId=11065072)(게시일 2026-09-29, 10월 전망)와 [2026년 10월 조사](https://www.bok.or.kr/portal/bbs/B0000501/view.do?menuNo=201264&nttId=11066009)(게시일 2026-10-29, 11월 전망)다. 이전 PDF 전망표 물리 13쪽·14쪽의 확인 기록을 사용했고, 현재 API 스냅샷의 값과 일치했다. 제조업 BSI를 플라스틱 업종 전용 지표로 바꾸어 부르지 않는다.
- 위 BSI의 보수적 이용 가능 시각은 각각 2026-09-30·10-30 00:00 KST로 실제 실행 원점보다 앞섰다. 생산 스냅샷은 2026-11-03에 확보됐고 화면 갱신일은 2026-10-30이었다. **현재 손에 있는 입력의 이용 가능성**과 **과거 모든 시점의 원 발표판 검증**은 구분한다. 후자는 여전히 미검증이다.

계획의 ‘새 생산 실적 조회 금지’를 지켜 공식 전체 공개 상태를 재검색하지 않았다. 따라서 결과 확인 전 고정의 직접 확인 범위는 **현재 로컬 원본에 두 목표 Y가 없으며 예측 계산에 참조하지 않았다는 것**이다. 외부의 모든 공개 경로에서 미공표임을 독립적으로 새 확인했다는 주장과 구분한다.

## 3. 사전 지정 매핑·모델·학습 마감

타깃은 업종별 생산 원지수 `P`의 `100×(P_t/P_(t-12)−1)`(% YoY)다. 원지수 수준이나 고객별 PC/ABS 소비 톤수를 예측한 것이 아니다.

| 타깃 | BSI 매핑 | 목표월 | 학습 마지막 월 | 학습 행 | 예측 종류 |
|---|---|---|---|---:|---|
| C303 자동차 신품 부품 | 자동차 `C3000` | 2026-10 | 2026-08 | 33 | 미공표 실적 nowcast |
| C303 자동차 신품 부품 | 자동차 `C3000` | 2026-11 | 2026-09 | 34 | 월중 prospective forecast |
| C222 플라스틱 제품 | 제조업 전체 `C0000` | 2026-10 | 2026-08 | 33 | 미공표 실적 nowcast |
| C222 플라스틱 제품 | 제조업 전체 `C0000` | 2026-11 | 2026-09 | 34 | 월중 prospective forecast |

학습 시작은 모두 공통 패널 첫 월 **2023-12**다. 원점별로 타깃 t의 **t-2 이하** 모든 공통 월을 사용하고 X와 Y를 같은 전망 대상월로 결합했다. BSI 조사월은 t-1이다. 11월 3일 실제 원점을 10월 1일·11월 1일의 월초 원점으로 바꾸지 않는다. 10월은 이미 종료된 달이므로 선행 예측, 11월은 아직 진행 중이므로 한 달 선행 예측이라고 표현하지 않는다.

각 행에서 다음 3개를 계산해 총 12개를 고정했다.

1. 계절 Naive: `g_hat_t=0`.
2. 과거 YoY 평균: 같은 공통 학습 행의 평균.
3. BSI 단일변수 OLS: 같은 학습 행에서 절편 포함 `g=a+b×BSI`, 현재 확보한 해당 목표월 BSI 대입.

최소 학습 12행, 상수 BSI·분모 부재·중복·잘못된 산업/조사월·입력 해시 불일치·미래 생산월·고정 날짜 외 실행은 중단한다. 튜닝·클리핑·지표 자동 선택·시차 변경은 없다. 각 원점의 학습 월 목록·계수·입력 매핑을 `model_params.json`과 고정 JSON 안에 함께 보존했다. 계절 Naive·평균·OLS 사이에 학습 행을 달리하지 않았다.

**2026-11 BSI는 2026-10 조사 표본개편·KSIC-11 이후 자료**다. 두 업종의 학습에는 개편 이후 행이 0개다. 특히 자동차 BSI의 11월 입력은 해당 학습 BSI 범위 밖이어서 외삽 위험 플래그도 true다. 제조업 BSI 11월은 범위 안이지만 개편 위험 플래그는 동일하게 유지했다. 이 위험을 보고 예측을 조정하거나 다시 선택하지 않았다. 학습에 포함되는 2026-08·09 생산값은 잠정치일 수 있으며 이 현재 판본 그대로 봉인했다.

## 4. 파일 고정·재생성 방지와 검증 결과

로컬 전용 `round10_prospective/`에는 canonical JSON, `forecasts.sha256`, `input_manifest.json`, `model_params.json`, 원본·소스의 `sealed_inputs/` 사본을 저장했다. JSON 직렬화는 UTF-8, 키 정렬, 공백 없는 구분자, 비ASCII 보존, NaN 금지이며 **끝 줄바꿈 없는 실제 바이트**의 SHA-256이다. 예측값·계수·개별 관측값을 공개 저장소에 넣지 않는다.

폴더·파일은 배타적 생성으로 기록한다. 기존 봉인 폴더가 있으면 `--lock`이 재생성을 거부하며 force/overwrite 기능은 없다. 파일시스템 자체가 WORM 저장소인 것은 아니므로 향후 수정 여부는 **GitHub에 공개한 이 해시를 외부 기준**으로 확인해야 한다. 별도 사본을 검증할 때도 원본 SHA를 사용한다.

실제 검증:

- **합성 fixture 테스트 7개 통과**: 12개 고유 매핑·t-2 마감·33/34 학습 행, 독립 OLS/평균 검산, 10월 예측에 9월 생산을 쓰지 않음, 미래 생산월 포함 시 중단, 분모/중복/상수 BSI/학습 부족/미래 이용 시점/잘못된 원점·조사월 거부, canonical 해시·NaN 차단, 재생성 거부·외부 SHA/입력 변조 검출.
- 실제 실행 후 `--verify`가 **12개 예측 JSON·18개 입력 사본·모델 파라미터·manifest의 일치**를 확인했다.
- 봉인된 입력을 읽기만 하는 별도 감사에서 4개 OLS를 표준 라이브러리 `statistics.linear_regression`과 대조했고, 고정된 12개 예측의 산술이 일치했다. 파일 재생성·수정 없이 해시가 그대로임을 확인했다.
- 성능 지표를 계산하는 경로는 이번 코드에 없다. 기존 V1·ROUND 07~09 코드·결과·지원서는 수정하지 않았다.

재검증 명령(예측을 다시 만들지 않는다):

```powershell
python -X utf8 work/research/round10_lock_forecasts.py --verify --expected-sha256 a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7
python -X utf8 -m unittest discover -s work/research -p test_round10.py -v
```

## 5. 고정한 입력 해시

아래 경로는 프로젝트 상대 경로다. 로컬 원본/검증 근거와 실행 소스 모두 사본으로 보존했다. 개별 파일의 해시까지 포함한 전체 manifest는 예측 canonical JSON의 공개 SHA에 묶여 있다.

| 파일 | SHA-256 |
|---|---|
| `work/data/local_only/round09_industry/industry_generic.xml` | `316582069d7109a8c494e342fbe1b9dbc902fd5cc03abd3ecb90597ee21d6fc6` |
| `work/data/local_only/round09_industry/industry_dsd.xml` | `f8683f8fa5123a78a33a660da3bfde604fd900f443693bdc5f3ea51f7d7a06cf` |
| `work/data/local_only/round09_industry/source_observations.json` | `e326963394d8d3257de314b896e0a46687122027cd67bebe4ce984068a5ddf42` |
| `work/data/local_only/round09_industry/summary.json` | `3854631ce8c55ad2f8e30cb2db23a9c3cd1048608efc999071ae058b7cb8cc80` |
| `work/data/local_only/round07c_ecos/normalized_snapshot.json` | `e23d642dcfd502b018c0bba7956d5eb762e1d79a6fe94defb5b9eb6bcec08ecf` |
| `work/data/local_only/round07c_ecos/search_512Y008_M_202312_202611_BD_C0000.json` | `0190fdf152b6e9095b8be32e507c7e4b165ecefcdbfa3ee656a294418d9f23b1` |
| `work/data/local_only/round07c_ecos/search_512Y008_M_202312_202611_BD_C3000.json` | `d557d96c174675fcd25cea3e0f531c3e11607f1c01d7fec4472f823b00d18e81` |
| `work/data/local_only/round07c_ecos/manifest.json` | `dc32056e5d38715231dd7ef892f312da6b3171ffa09d96f7d651031f9b3c0e5c` |
| `work/data/local_only/round07_bsi/verified_sample.json` | `d8586d29f587946135496d4f571827064abe4e3fdf2b407cf31d4630f30962d9` |
| `work/data/local_only/round07_bsi/bok_bsi_2026-09.pdf` | `0b093114dbd5023150fa0587082e74dd0de7ce4826719ded864b6398e11aa5cb` |
| `work/data/local_only/round07_bsi/bok_bsi_2026-10_vF.pdf` | `8d632025e0ebe92b2f405600f258de7046a71c6da7bec03bd2710a21cbdbee44` |
| `work/data/local_only/round07_bsi/manifest.json` | `3f9aa4c1f8d6f3e0067e5e08575d1446352f2dcf349cdaebc56ac8ad3fe416c6` |
| `work/research/ROUND_10_PLAN.md` | `a54ea641cf99d50f49cae87147c6410b944d8ecaee90708ddb88f0a3242bf67a` |
| `work/research/analyze_round08.py` | `4f292163903b8c624a75863ac720df945b2403f08a6ffb7cb28d7803550398c6` |
| `work/research/analyze_round09.py` | `73bf8d9da629f121c2712566806c32fbf54dc722b639fccb79a5ebd08ecc46cf` |
| `work/research/experiment_round08b_hindsight.py` | `f6c10f05fe59c153bfb2844d8612e4816d2bcad6596ea2e500b34bdbd7531a98` |
| `work/research/round10_lock_forecasts.py` | `dbb067783fe78d4dfd32fe41d151d6c581c194d3bd3a0018d41a2bf338a60f9e` |
| `work/research/test_round10.py` | `29dccd2b2ece7b1988a38c6c03cf217fb31b5b2733e0d1091022d60656ed5243` |

## 6. 향후 평가

2026-10·11의 최초 공식 생산 실적이 발표되면, 이 공개 SHA를 먼저 대조하고 **고정된 12개 예측만** 평가한다. 최초 발표 자료·발표 시각·해시와 해당 판본의 타깃/전년동월 지수 또는 공식 YoY를 보관한다. 분자·분모의 판본이 다르면 섞어 계산하지 않는다. 후속 잠정/확정 수정값은 별도 판본으로 나란히 채점하며 예측을 재학습·교체하지 않는다. 동일 목표월의 다른 재계산은 comparison_only로 분리해야 하며 이번에는 만들지 않았다.

현재는 정답이 없으므로 MAE·예측 개선율이나 승자 모델을 보고하지 않는다. 2개월×2업종의 향후 평가도 연구용 예비 점검이며 통계적 성능·실무 효과 입증이 아니다. 생산지수는 고객별 PC/ABS 투입량이나 롯데 주문량이 아니다. 기존 ROUND 08-B의 소급 탐색과 엄격 과거판본 게이트 `NO_VERIFIED_BACKTEST`도 그대로 보존한다.

GitHub 공유 대상은 새 코드·합성 테스트·이 보고서다. 인증키·원본·정규화 값·개별 예측은 로컬 제외 경로에만 보관한다. 보고서의 시각·해시·행 수·설정은 봉인 증거이고 성능 결과가 아니다.
