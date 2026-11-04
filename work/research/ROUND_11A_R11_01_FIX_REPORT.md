# ROUND 11-A R11-01 — 고정소수점 정규화와 버전별 오프라인 재연

실행일: 2026-11-04 KST / Codex. 계획 커밋 `f678315`을 반영했다. **필수 결함 수정·검증 완료: 지수표기 3건→0건, 원 API 수치 72개 동일, 기존 UNCHANGED 72건 유지.** Claude의 독립 재감사 판정은 아직 받지 않았으며 Round 11-B는 착수하지 않았다.

## 1. 수정 내용과 호환성

기존 `str(Decimal(...).normalize())`는 유효한 정수를 지수표기 문자열로 만들 수 있었다. 앞으로의 기본 정규화 버전은 **2**이며, `format(result, 'f')` 후 소수 부분의 불필요한 끝자리 0만 제거한다. 정수의 자리수 0을 지우지 않고 양·음의 0은 `"0"`으로 통일한다. 범위 0~200, NaN/Infinity·잘못된 형식 차단은 유지했다. 입력의 긴 소수도 Decimal 문맥 정밀도로 불필요하게 반올림하지 않는다.

다음은 **공식 관측값을 인용한 것이 아닌 합성 회귀 테스트 예시**다.

| 합성 입력 | 버전 1 | 버전 2 |
|---|---|---|
| `100`, `100.0`, `1E+2` | `"1E+2"` | `"100"` |
| `90` | `"9E+1"` | `"90"` |
| `110` | `"1.1E+2"` | `"110"` |
| `-0` | `"-0"` | `"0"` |
| `12.3400` | `"12.34"` | `"12.34"` |

버전 1 분기를 그대로 유지하고 `normalize()`뿐 아니라 **baseline_rows()와 diff.json 재연까지** 아카이브 manifest의 normalization_version을 명시적으로 전달한다. 버전이 없거나 지원하지 않는 값이면 추정하지 않고 실패한다. 새 `--collect`는 버전 2를 기록한다. Decimal 수치 비교는 유지해 서식 변화가 HISTORICAL_VALUE_CHANGED로 바뀌지 않는다.

## 2. 실제 버전 1·2 결과

| 항목 | 원 실행 v1 | 새 파생 실행 v2 |
|---|---|---|
| 저장 영역 | `round11_snapshots/` | `round11_reprocessed/` |
| run ID | `20261104T090724027444_cd96f70034a7` | `20261104T101726512529_3228efd3efd1` |
| 버전 | 1 | 2 |
| 관측 행 | 72 (36+36) | 72 (36+36) |
| 지수표기 문자열 | **3건** | **0건** |
| 수치 판정 | UNCHANGED 72 | **UNCHANGED 72** |
| 신규/기존 값 변경/누락/검증 오류 | 모두 0 | **모두 0** |
| 오프라인 원문 재연 | **PASS**, 종료 코드 0 | **PASS**, 종료 코드 0 |

독립 확인에서 보존된 StatisticSearch 원문과 두 정규화 파일을 업종·목표월로 연결해 **원 API 값 = v1 값 = v2 값**의 Decimal 동일성을 72행 모두 검산했다. 값 문자열은 정확히 3행만 달라졌고 나머지 69행은 같다. 새 run_id는 파생 처리의 새 신원을 나타내므로, 모든 행의 전체 바이트가 예전 파일과 같다는 의미는 아니다. 각 아카이브는 자기 버전·run_id로 재연해 normalized.json과 diff.json이 일치하는지 검사한다.

새 결과는 `REPROCESSED_NOT_PROMOTED`다. 기존 분류를 공식 정정이나 모델 입력 승인으로 해석하지 않는다. **이번 ECOS API 호출은 0회**이며, 수집 키를 읽지 않는 오프라인 재처리 경로만 사용했다.

## 3. 조회 시각과 새 처리 시각

- 원 API 조회 시작: `2026-11-04T09:07:24.027444+09:00`.
- 원 자동차 수신 완료: `2026-11-04T09:07:25.939928+09:00`.
- 원 제조업 수신 완료: `2026-11-04T09:07:26.671765+09:00`.
- 새 처리 시작/processed_at: **`2026-11-04T10:17:26.512529+09:00`**.
- 새 처리 완료: `2026-11-04T10:17:26.549622+09:00`.
- 실제 재처리 소스 커밋: **`73812cd97f86f21d6fcf4f151280801fd76926e1`**.

72행의 observed_at과 요청 5개의 원 조회 기록은 그대로 보존했다. 새 처리 시각을 새 조회·공표 시각으로 쓰지 않았다. 파생 manifest의 `execution_mode=OFFLINE_REPROCESSED`, `network_calls_this_run=0`과 requests_meaning이 이를 구분한다. 공표일·이용 가능일 null, vintage_verified=false, 2026-11 표본개편 플래그도 유지했다.

## 4. 판본·원문·봉인 보존

새 로컬 전용 폴더는 `work/data/local_only/round11_reprocessed/20261104T101726512529_3228efd3efd1/`다. 원 API 응답 5개와 기준선 사본, parent/manifest.json·parent/normalized.json, 신규 normalized/diff, 실행 소스 사본과 신규 manifest를 보관했다. 기존 원문은 재직렬화하지 않고 **바이트 그대로 복사**했다. 파생 판본은 15개 파일이며, 원 폴더에 쓰거나 옮기거나 재생성하지 않았다.

| 무결성 증거 | SHA-256 또는 확인 결과 |
|---|---|
| 원 v1 manifest | `5f189a02ecbbd3bb24fea924ef8a0ca895a3018db8a19e015c7df2a0c40d33c6` **유지** |
| 새 v2 manifest | **`cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39`** |
| 새 v2 normalized.json | `e292b24a2bf884e0143a70690ac83d4bc55b6b5d39066804abbccad8be1de715` |
| 새 v2 diff.json | `9d333bfd09e60d962c39ee95667eaf90323570ecfcc361e59c899e3d1360dd2d` |
| 실제 파이프라인 소스 바이트 | `b0f3f222a047f13969da845d128cac390db712c7d549dfdf83c2946f38101029` |
| 원 API 응답 5개 | 원본·파생본 바이트 및 SHA **5/5 일치** |
| 원 run 전체 13개 파일 tree SHA | 전후 모두 `4ccf4aedcdd2d09a4b369b2329ee2537a91367ddc02a8dbfaf16b38f2d6c96b0` |
| Round 10 전체 22개 파일 tree SHA | 전후 모두 `f667fd1a5226e546b5867225ff68c9b3dac2c6b041a0e6b4d7e9e92d3ad14e3a` |
| Round 10 예측 canonical SHA | `a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7` **유지** |

v2 검증은 자기 파일 해시뿐 아니라 부모 manifest의 공개 SHA, 부모와 동일한 요청 기록, 재사용 원문/기준선의 해시와 부모 정규화 파일 해시도 확인한다. 해시는 내용 동일성의 증거이며 공인 시각 증명은 아니다. 원본·개별 정규화 값은 공개하지 않는다.

## 5. 테스트와 실행 방법

**기존 9개 + 신규 회귀 7개 = 총 16개 PASS.** 기존 test_round11_pipeline.py는 수정하지 않고 그대로 재실행했다. 신규 테스트는 다음을 확인한다.

1. 고정소수점·과학표기 입력·정수 자리수·소수 끝자리 0·음의 0·긴 소수 정책.
2. NaN/Infinity·범위 밖·잘못된 타입·지원하지 않는 버전 거부.
3. 과거 지수표기를 보존한 v1 fixture의 normalized/diff 전체 재연.
4. 신규 수집 경로의 v2 기록과 v2 오프라인 재연(합성 HTTP만 사용).
5. 서식만 바뀌면 UNCHANGED, 실제 수치 변경이면 HISTORICAL_VALUE_CHANGED.
6. HTTP/키 로더 호출을 막은 v1→v2 재처리, 원문·시각·원 폴더·봉인·이전 파생물 불변.
7. 아카이브 버전이 잘못됐을 때 실패하며 임의로 버전을 추정하지 않음.

실제 두 아카이브도 HTTP와 키 로더를 차단한 읽기 전용 검증을 통과했다. 별도 감사 코드에서 72개 원 수치, 정규화 문자열의 고정소수점 패턴, 표기 변경 3건, 원 응답 5개의 바이트와 원 run/Round 10 전체 해시를 확인했다. 두 버전 모두 재연 결과를 직렬화한 **normalized.json·diff.json 바이트까지 각 저장 파일과 일치**했다. 재검증은 파일을 쓰지 않는다.

```powershell
# 기존 v1 재검증
python -X utf8 work/research/round11_ecos_snapshot_pipeline.py --validate-run 20261104T090724027444_cd96f70034a7 --expected-manifest-sha256 5f189a02ecbbd3bb24fea924ef8a0ca895a3018db8a19e015c7df2a0c40d33c6
# 이번 v2 파생물 재검증
python -X utf8 work/research/round11_ecos_snapshot_pipeline.py --validate-reprocessed 20261104T101726512529_3228efd3efd1 --expected-manifest-sha256 cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39
# 합성 회귀 테스트 16개
python -X utf8 -m unittest discover -s work/research -p 'test_round11*.py' -v
```

필요할 때 `--reprocess-run <원run ID> --expected-manifest-sha256 <원manifest SHA>`는 네트워크 없이 별도 신규 파생 폴더를 만든다. 기존 판본 확인에는 위 validate 명령을 쓰며 다시 처리할 필요가 없다. `--collect`는 다음에 실제로 새 수집이 필요할 때만 사용하며, 이번 수정 검증에서는 실행하지 않았다.

## 6. 범위 보존과 재감사 요청

이번 변경 파일은 기존 파이프라인 코드, 새 버전 회귀 테스트, 이 보고서다. 기존 run·Round 10 봉인·V1~Round 10 결과·지원서·감사 로컬 파일은 보존했다. 개별 관측값·인증키·로컬 파생 파일은 GitHub에 올리지 않는다.

기준선 중간 결측의 오분류 가능성은 **Round 11-B 승인 기준선 레지스트리 도입 전 우선 개선 과제**로 남겼다. 값 변경 시 종료 코드 정책, 작업 트리 clean/dirty 기록, 부분 폴더 INCOMPLETE 식별도 이번에는 변경하지 않았다. 네 가지 선택 개선을 필수 결함 수정과 섞지 않았다.

Claude는 버전별 formatter와 baseline/diff 재연, v1 공개 manifest 해시, v2 부모/원문 연결, 72행 수치 불변·표기 3→0, 원 조회 시각 보존, 기존 run·봉인 불변을 독립 재감사할 수 있다. **Claude PASS 재판정 전 Round 11-B 구현은 계속 보류**한다. 최종 Push 커밋 SHA는 완료 메시지로 전달한다.
