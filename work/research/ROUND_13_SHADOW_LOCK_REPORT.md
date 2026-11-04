# ROUND 13 — 별도 Shadow Forecast Lock 완료 보고

상태: **8개 예측 봉인 완료 / 성과 채점 미수행 / 기존 Round 10과 분리**

## 1. 공개 고정 정보

| 항목 | 결과 |
|---|---|
| 실제 실행 원점 KST | `2026-11-04T12:21:29.586844+09:00` |
| 실제 실행 원점 UTC | `2026-11-04T03:21:29.586844+00:00` |
| JSON 생성 시각 KST | `2026-11-04T12:21:29.991727+09:00` |
| 실행 소스 커밋 (코드·테스트 먼저 Commit/Push) | `44ad097d6607211a074253d61cafae5af08179d7` |
| 사전 계획 등록 커밋 | `a3c2821b02fd4879fee5207352e7eb15e1b931e1` |
| 소스 커밋의 계획 Git blob | `129453d73851d1d26eb74f98b8c36fccc85a34b6` |
| 계획 파일 SHA-256 | `f88170094bffeb0eb9626ae8ab4e55459100c7fb3572bf9b5ea433c3bc3a3641` |
| canonical 예측 JSON SHA-256 | **`bbf4e8defefa4a2d13199908db829ab3162b479696ecd5730788ad0cfc299c74`** |
| 예측 개수 | **8개**: C222/C303 × 2026-10/11 × 최근6/12개월 평균 |
| 봉인 위치 | `work/data/local_only/round13_shadow_lock/` (로컬 전용) |
| 파일 수 | 입력 사본 12개 + 출력/메타데이터 4개 = 16개 |
| 재검증 상태 | `SHADOW_LOCK_HASH_INPUTS_AND_REPLAY_VERIFIED` |
| 채점 | **`NOT_PERFORMED_NO_ACTUALS`** |
| 과거 시점 검증 | `NO_VERIFIED_BACKTEST` |

코드·합성 테스트 2개 파일을 소스 커밋으로 먼저 GitHub에 Push하고 origin/main과 HEAD가 같은지 검사한 뒤 실제 봉인을 한 번 실행했다. 본 보고서는 이후의 별도 커밋으로 공개한다. 예측값·canonical JSON·원본·입력 사본은 GitHub에 올리지 않는다. 보고서 커밋은 실행 소스 커밋과 구별하며 최종 완료 메시지로 전달한다.

## 2. 목표와 학습 창

목표는 전국 KOSIS `101 / DT_1F02001 / A=00 / T10`의 C222 플라스틱 제품·C303 자동차 신품 부품 생산 원지수(2020=100)에서 계산하는 YoY `100×(P_t/P_(t−12)−1)`다. 고객별 PC/ABS 소비톤·롯데케미칼 주문톤이 아니다.

모델은 `rolling_yoy_mean_6`, `rolling_yoy_mean_12` 두 개뿐이다. 각 타깃 t에서 t−2 이하의 공통 학습 가능 월(2023-12 이후)을 만들고 최근 6/12개 연속 YoY의 산술평균을 사용한다.

| 목표월 | 학습 상한 | 공통 학습 행 | 최근6 학습월 | 최근12 학습월 |
|---|---|---:|---|---|
| 2026-10 | 2026-08 | 33 | 2026-03~08 | 2025-09~2026-08 |
| 2026-11 | 2026-09 | 34 | 2026-04~09 | 2025-10~2026-09 |

- 두 업종에 같은 규칙을 적용했다. 10월 예측은 9월 실적을 사용하지 않으며, 11월 예측은 t−2인 9월 실적을 사용한다.
- BSI 입력·추가 회귀·혼합·하이퍼파라미터 탐색·튜닝은 없다. Round 12-B 최근 평균 정의(statistics.mean)를 유지하고 독립적으로 `(P_t−P_(t−12))/P_(t−12)×100`의 합/개수 계산과 8건 모두 대조했다(상대/절대 허용오차 1e−10).
- 목표월 실측 Y를 계산하거나 입력하는 경로가 없다. 원 XML의 모든 관측 월을 수치 파싱 전에 검사해 2026-10 이후 관측이 있으면 중단한다. 코드·산업·월·행 수·중복·결측·비유한·양수 분모·잠정 플래그·원본 해시도 검사했다.

## 3. 실제 사용 입력과 전향성의 한계

- 기존 로컬 `round09_industry/industry_generic.xml`, `industry_dsd.xml`와 보존 `summary.json` 매니페스트만 자료 입력으로 읽었다. SDMX/DSD의 SHA를 기존 매니페스트와 대조하고 해당 바이트를 파싱했다. 새 API·새 생산자료·외부 실적 조회는 없다.
- 생산 실측은 **업종별 57개월, 2022-01~2026-09**다. **2026-10·11 실적은 입력에 없다.** 관측값의 업종/기간 일치, 결측/중복/비유한 0건을 확인했다.
- 2026-08·09는 기존 KOSIS p) 표기 근거의 잠정 입력으로 보존했다. 10월 창에는 8월, 11월 창에는 8·9월이 포함되며 판본·잠정 여부와 원문 해시를 봉인했다. 현재 입력 판본의 변동 위험은 남는다.
- **외부 공식 미공표 여부 확인 미완료**: `external_release_check=NOT_VERIFIED_NO_NEW_DATA_QUERY`. 로컬 입력의 실적 부재는 확인했지만 공식 최신 공표 일정·외부 모든 자료의 미공표를 독립적으로 증명하지 않았다. 미래 정답을 새로 조회하지 않는 조건을 지켰으며 prospective 지위를 과장하지 않는다.
- 실행 원점은 실제 로컬 시스템 시각이다. 공인 타임스탬프 서버의 시각 증명이 아니다. 10월은 지난달 활동에 대한 **nowcast 후보**, 11월은 **월중 예측**이며 월초/1개월 전 사전 예측으로 표현하지 않는다.

## 4. 별도 봉인·보존 검증

- 디렉터리와 파일은 배타적 새 생성으로만 쓴다. 원래 폴더가 있으면 중단하고 overwrite/force/resume/relock 옵션은 없다. 부분 실패 시에도 원 폴더를 삭제·재생성하지 않는다.
- canonical JSON은 UTF-8, 키 정렬, compact separators, NaN/Infinity 금지 규칙을 사용한다. JSON 해시가 입력 매니페스트·모델 정의·원점·소스·학습월·예측값에 결합된다. 개별 입력 사본도 각각 SHA·크기를 검사한다.
- 봉인 직후와 별도 읽기 전용 `--verify`에서 공개 SHA·canonical 형식·입력 12개·메타데이터·전체 파일 목록을 확인했다. 봉인된 생산 원본만으로 8개 예측·학습월을 다시 계산해 저장 결과와 일치했다. 이 재연은 기존 숫자를 읽기 전용으로 대조한 것으로 재봉인·갱신이 아니다.
- 원본·과거 로컬 아카이브·감사 파일·지원서·V1 산출물 **167개**의 파일 목록/SHA를 봉인 전후 대조했고 불변이다. 보호 목록은 로컬 evidence 사본에만 보관한다.
- **Round 10의 22개 파일 전부 불변**. canonical SHA `a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7`, 기존 트리 SHA `f667fd1a5226e546b5867225ff68c9b3dac2c6b041a0e6b4d7e9e92d3ad14e3a` 모두 일치했다. 기존 12개 예측을 재생성·교체·채점하지 않았다.
- Round 12-A/B 및 Round 11 보관 자료·운영 코드도 변경하지 않았다. Agent·자동 수집·승인 레지스트리·LLM 작업은 진행하지 않았다.

### 공개 가능한 출력 파일 SHA-256

| 로컬 출력 | SHA-256 |
|---|---|
| `forecasts.canonical.json` | `bbf4e8defefa4a2d13199908db829ab3162b479696ecd5730788ad0cfc299c74` |
| `forecasts.sha256` | `e18c9becdda763d5d7a0d1bdeb09e16a63031d95b932971afce029c49a60c39e` |
| `input_manifest.json` | `b048212dc7c9982518686ad4677281fa0f450295dffddcbd7a7ee3368759359c` |
| `model_params.json` | `2045e5c90e5d387f56a03e9b9b9494d46c2704efb63b6f986fdcb7b281221e5e` |

`forecasts.sha256` 행은 해시 문자열 파일 자체의 해시이므로 canonical JSON 해시와 다르다. 향후 검증 기준은 위의 **canonical 예측 JSON SHA-256**이다.

### 봉인된 입력 사본 SHA-256

| 로컬 입력 (sealed_inputs 아래) | 바이트 | SHA-256 |
|---|---:|---|
| `evidence/protected_files_before.json` | 22907 | `d14b05e92339f640badb287431e88d8aac8852be585bf46f876ce7aa3fd29804` |
| `evidence/round10_integrity.json` | 195 | `3c3deccbb3bbcad07be693be751d4cb91ead56edaab4772a564264052b9090c4` |
| `work/data/local_only/round09_industry/industry_dsd.xml` | 7193 | `f8683f8fa5123a78a33a660da3bfde604fd900f443693bdc5f3ea51f7d7a06cf` |
| `work/data/local_only/round09_industry/industry_generic.xml` | 16067 | `316582069d7109a8c494e342fbe1b9dbc902fd5cc03abd3ecb90597ee21d6fc6` |
| `work/data/local_only/round09_industry/summary.json` | 7997 | `3854631ce8c55ad2f8e30cb2db23a9c3cd1048608efc999071ae058b7cb8cc80` |
| `work/research/ROUND_13_SHADOW_PROSPECTIVE_PLAN.md` | 8078 | `f88170094bffeb0eb9626ae8ab4e55459100c7fb3572bf9b5ea433c3bc3a3641` |
| `work/research/analyze_round08.py` | 10968 | `4f292163903b8c624a75863ac720df945b2403f08a6ffb7cb28d7803550398c6` |
| `work/research/analyze_round09.py` | 9291 | `73bf8d9da629f121c2712566806c32fbf54dc722b639fccb79a5ebd08ecc46cf` |
| `work/research/experiment_round12b_recent_bias.py` | 10643 | `2a9d88b210460292c8581c4fcba8b6603a6922caec064af1823f63016591e6c8` |
| `work/research/round13_shadow_forecast_lock.py` | 14659 | `590e8be3bebf60f46582c2860612af808ad1c89357cd779b70fb665bca791f27` |
| `work/research/test_round09.py` | 5124 | `2e3e87ca875ac66e2ccfd40155a2936cc38e243494afeb6cb290e292ab2ae66f` |
| `work/research/test_round13_shadow_forecast_lock.py` | 9745 | `6b0c36ad4f56921e6f2321d19042b0a846e8f91584ed88ee26590b535a90375e` |

입력 사본에는 원본 3개, 고정 코드·테스트·계획/모델 정의 7개, 무결성 근거 2개가 포함된다. 근거 파일은 보호 파일 해시 목록과 Round10 상태이며 원문 감사 내용은 복사하지 않았다. 이 표는 해시·크기만 공개한다.

## 5. 테스트·실행 방법

**신규 합성 테스트 11개 PASS**. 실제 봉인 전 커밋한 코드에서 테스트를 통과했으며, 실제 데이터의 독립 산술 8건과 저장본 재연도 PASS다. 정확도·MAE·RMSE·개선율은 계산하지 않았다.

테스트 범위: 8개 유일 조합/정확한 창/33·34행 공통 학습, 별도 합산 검산, 10월에서 9월 입력 불참조, 미래 실측을 수치 전에 거절, 원본 변조·중복·자료 부족·0/비유한·잘못된 코드/월·잠정 플래그 거부, 불법 원점·원점 override 거부, Push/clean 소스 요구, canonical/외부 SHA·입력 사본/메타데이터/추가 파일/예측 변조 검출, 덮어쓰기/경로 이탈 차단, 기존 Round10 잘못된 트리 거부. 실제 봉인 불변은 별도의 전후 해시 검사로 확인했다.

```powershell
python -X utf8 -m unittest discover -s work/research -p test_round13_shadow_forecast_lock.py -v
python -X utf8 work/research/round13_shadow_forecast_lock.py --verify --expected-sha256 bbf4e8defefa4a2d13199908db829ab3162b479696ecd5730788ad0cfc299c74
```

실제 실행한 봉인 명령은 아래와 같다. **이미 실행 완료했으므로 재실행하지 않는다**(코드도 기존 폴더를 거부한다).

```powershell
python -X utf8 work/research/round13_shadow_forecast_lock.py --lock --expected-source-commit 44ad097d6607211a074253d61cafae5af08179d7
```

원점 override와 임의 출력 경로 옵션은 없다. 이번 소스는 2026-11-04 KST 실행 프로토콜로 제한되며 추후 날짜로 재생성할 수 없다. `--verify`는 저장된 원점을 사용해 읽기 전용으로 동작한다.

## 6. 향후 평가 및 독립 리뷰

- 두 월의 첫 공식 실적이 공표된 뒤 별도 승인된 실행에서 분자 P_t·전년동월 분모 P_(t−12)를 **같은 공식 판본**으로 보존하고 고정된 숫자만 채점한다. 수정 판본 평가는 별도 표로 둔다. 공표 날짜를 임의로 단정하지 않는다.
- Round10과 Round13은 원점이 다르므로 엄격한 동일시점 대결로 해석하지 않는다. 두 연구의 고정 예측을 유지하고 특정 월/모델만 선택해 우승을 주장하지 않는다.
- 업종별 각 모델의 평가월은 2개에 불과하다. 결과가 좋아도 과거 탐색 개선의 미래 재현·통계적 우월성·PC/ABS 고객 소비 성능을 증명하지 못한다.
- 독립 검토 자료: 공개 계획/소스 커밋, 합성 테스트, 이 보고서의 원점·SHA·학습 창·보호 결과. 로컬 원본과 봉인 숫자는 공개 저장소에 없으며 Claude 자동 호출은 하지 않았다.
