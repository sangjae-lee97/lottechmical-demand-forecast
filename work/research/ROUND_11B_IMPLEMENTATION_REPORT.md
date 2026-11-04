# ROUND 11-B — 기준선 결측 차단과 인간 승인 v2 레지스트리

확인일: 2026-11-04 KST / Codex. 계획 커밋 `8047daf`을 반영하고 구현·합성 검증·실제 v2 후보 dry-run을 수행했다. **R11-02 신규 경로 차단 완료, 테스트 총 29개 PASS. 실제 승인 0건, current 포인터 미생성, 실제 레지스트리 폴더도 미생성이다.**

## 1. R11-02 수정과 과거 재현성

새 `validate_dataset()`는 업종별 월 형식·조사월 대응·중복·중간 결측·코드·수치를 검사하고, 두 업종의 월 목록이 완전히 같은지 확인한다. 승인 후보는 v2 고정소수점 문자열까지 검사한다.

합성 기준선이 2026-09·11이고 새 조회가 09~11월 연속일 때, 과거 분류 함수는 10월을 신규로 표시했다. **새 compare_strict() 경로는 BASELINE_INTERNAL_GAP으로 비교 전에 중단**한다. 새 수집 경로도 기준선을 먼저 검증하므로 이 경우 API 호출 없이 실패·격리 상태를 기록한다.

새 수집 manifest에 `validation_policy_version=2`를 기록한다. 과거 v1/v2 아카이브에 이 필드가 없으면 당시 정책 1로 원문·정규화·diff를 재연한다. normalization_version(숫자 문자열 형식)과 validation_policy_version(자료 품질/분류 규칙)은 서로 다른 개념이다. 기존 아카이브를 바꿔 통과시키지 않았다.

- 새 운영 비교는 기준선과 후보 모두 strict 검증을 통과해야 한다.
- 기준선 끝 뒤에 연속해서 추가된 월은 NEW_TARGET_MONTH다. 첫 월 이전 추가 이력은 HISTORICAL_EXTENSION으로 구분한다.
- 요청 창 밖 과거 월은 OUTSIDE_QUERY_WINDOW로 구분하며, 실제 창 내부 결측과 혼동하지 않는다.
- 과거 compare()/정책 1은 당시 기록 재현과 실패 진단을 위해 보존했다. 이것을 운영 승인 검증으로 쓰지 않는다.
- 합성 결측 기준선이 있는 과거 v2 아카이브도 정책 1 재연은 그대로 가능하지만, **새 승인 후보 검사에서는 BASELINE_INTERNAL_GAP으로 거절**함을 검증했다.

## 2. v2 승인 레지스트리 구현

새 모듈: `work/research/round11_baseline_registry.py`. 승인 대상은 **v2 성공 판본**이며, 파생 판본은 부모 manifest·원문·정규화 연결까지 기존 검증기로 확인한다. 실패·격리·누락·코드/범위 불일치·지수표기·변조·추적되지 않은 추가 파일·symlink가 있는 후보는 거절한다. v1은 승인 대상이 아니다.

승인 시 생성되는 구조는 다음과 같다. **이번 실제 경로에는 생성하지 않았다.**

```text
work/data/local_only/round11_registry/
  records/<sequence>_<id>/
    decision.json               # 사람이 제공한 승인 결정문 사본
    snapshot/<run_id>/...        # 검증된 전체 판본의 독립 바이트 사본
    record.json, record.sha256  # 이전 승인 ID/해시에 연결된 불변 레코드
  current.json                  # 검증 후 원자 교체하는 현재 포인터
```

승인 결정문은 schema_version, APPROVE 결정, reviewer_id, 시간대가 있는 approved_at, reason, `comparison_baseline_only` scope, 대상 run ID/manifest SHA, 이전 승인 SHA, evidence(URI/해시), remaining_limitations를 검증한다. 대상·이전 체인 해시가 다르거나, 증거/이유/제한이 없거나, 승인 시각이 후보 생성 전 또는 미래면 거절한다. 운영 승인 허가와 공식 최초 판본·고객 수요·모델 입력 승인을 분리한다.

레코드에는 원본 manifest SHA·normalized SHA·원문 응답 SHA·전체 판본 tree SHA·버전·승인 결정문 SHA·승인자/시각/이유·이전 승인 ID/레코드 SHA·실행 코드 SHA를 기록한다. 승인된 사본은 원 수집 폴더나 원 결정문이 나중에 바뀌어도 독립적으로 유지된다. `model_input_promoted=false`, `vintage_verification_granted=false`를 고정했다.

승인 이력/사본 파일은 배타적 새 파일로만 쓴다. 단일 writer lock 아래 후보·결정문·현재 체인을 다시 확인하고, 새 레코드·사본의 검증을 끝낸 후 fsync한 같은 폴더의 임시 포인터를 **os.replace**로 current에 원자 교체한다. 이전 승인 레코드는 덮어쓰거나 삭제하지 않는다. 오래된 승인 결정문으로 다른 현재 체인에 덧붙이는 것도 거절한다.

미완료 레코드·남은 writer lock·포인터 임시 파일·이력 끝과 맞지 않는 current는 **REGISTRY_INCOMPLETE 계열 오류**로 중단한다. 포인터 교체 실패 시험에서는 이전 current 바이트가 유지되고, 새 레코드는 남으며, 후속 검증·승인은 거절됐다. 자동으로 과거 기록을 지우거나 current를 새 이력 끝으로 승격시키지 않는다.

## 3. 명시적 기준선 선택과 합성 승인 전후 비교

비교 CLI는 `--baseline-id <승인ID>` 또는 `--registry-current` 중 하나를 명시해야 한다. 없으면 실패하며, 승인 전 판본을 자동 기준선으로 선택하지 않는다. 기존 수집기의 Round 07-C 기준점은 역사적 프로젝트 기준점으로 유지되며 인간 승인 v2로 바꾸어 부르지 않는다.

두 업종의 기간 일치 정책 때문에 신규 달 1개는 **업종별 1건, 합계 2행**이다. 합성 검증에서 다음을 확인했다.

| 순서 | 합성 결과 |
|---|---|
| 09~11월 판본을 합성 결정문으로 승인 | 승인 1, current=첫 승인 |
| 12월이 추가된 판본과 첫 승인 비교 | 기존 6행 UNCHANGED, 신규 달 1개/2행 NEW_TARGET_MONTH |
| 12월 포함 판본을 다음 합성 결정문으로 승인 | 승인 2, 이전 승인 파일 불변 |
| 같은 판본을 current와 비교 | 8행 UNCHANGED, 신규 0행 |
| 명시적으로 첫 승인 ID 선택 | 최초 비교의 events·counts·comparison SHA 재현 |

비교 결과에는 선택한 승인 ID·레코드 SHA·기준선/후보 manifest SHA·정책 버전·실행 코드 SHA·레지스트리 tip을 기록한다. 비교 SHA는 선택한 판본과 비교 내용에 대해 결정적이며 실행 시각/current tip 같은 변동 정보와 분리한다. 원문 관측값은 콘솔에 출력하지 않는다. 과거 수치가 달라져도 공식 정정으로 단정하지 않는다.

## 4. 실제 v2 후보 점검 — 승인 아님

읽기 전용 검증 완료 시각: **2026-11-04T11:09:28.524590+09:00**.

| 항목 | 실제 결과 |
|---|---|
| 후보 run | `20261104T101726512529_3228efd3efd1` |
| 후보 manifest SHA | `cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39` |
| 신규 정책 2 적격성 | PASS, v2 고정소수점·연속성·부모/원문/해시 검사 |
| 행·기간 | 72행, 업종별 36개월, 2023-12~2026-11 |
| 실제 결과 상태 | `ELIGIBLE_V2_PENDING_EXPLICIT_HUMAN_DECISION` |
| 실제 승인 기록 | **0개** |
| 실제 current | **null / 파일 미생성** |
| 실제 레지스트리 디렉터리 | **없음**, dry-run 후에도 미생성 |
| 공식 API/키 로더 호출 | 차단한 상태로 검증, **각 0회** |

실제 승인 결정문을 만들지 않았고 `--approve --execute-human-approval`을 실제 통계판본에 실행하지 않았다. 승인 기능의 쓰기·원자 교체 검증은 **SYNTHETIC_REVIEWER_NOT_USER** 등 합성 문서와 임시 디렉터리에서만 수행했다. 후보의 검증 성공을 사용자의 운영 승인으로 간주하지 않는다.

재현 가능한 실제 dry-run 명령:

```powershell
python -X utf8 work/research/round11_baseline_registry.py --check-candidate --dry-run --snapshot-kind reprocessed --run-id 20261104T101726512529_3228efd3efd1 --expected-manifest-sha256 cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39
python -X utf8 work/research/round11_baseline_registry.py --verify-registry
```

향후 사용자가 특정 판본을 승인하면 실제 결정문을 제공해야 한다. CLI `--approve`는 결정문과 함께 `--dry-run` 또는 명시적 `--execute-human-approval` 중 하나를 요구한다. 후자가 실제 쓰기를 수행하므로 지금은 실행하지 않는다.

## 5. 테스트·과거 판본·봉인 보존

**총 29개 PASS = 기존 Round 11-A 16개 + 신규 13개**. 명령:

```powershell
python -X utf8 -m unittest discover -s work/research -p 'test_round11*.py' -v
```

신규 검증 범위는 결측 오분류 차단/API 전 중단, 코드·월/조사월·중복·업종 기간·고정소수점, 연도 경계/과거 이력 확장, dry-run 무기록, 승인 전후 비교·과거 ID 재현, v1/실패/변조 거부, 승인문서의 범위·대상·이전 해시·시간·증거 검증, 승인/결정문/current/tip 변조 거부, 원자 포인터 교체 순서, 포인터 실패 시 과거 포인터 보존·미완료 중단, 승인 사본 보존·writer lock 차단이다. 레거시 결측 아카이브의 과거 판정 재연과 신규 승인 거부도 별도로 확인했다.

실제 v1/v2 파일은 읽기 전용으로 재검증했고 **normalized.json·diff.json의 바이트까지 원본과 일치**했다.

| 보호 대상 | 실제 확인 결과 |
|---|---|
| v1 manifest | `5f189a02ecbbd3bb24fea924ef8a0ca895a3018db8a19e015c7df2a0c40d33c6` 유지 |
| v1 13개 파일 tree SHA | `4ccf4aedcdd2d09a4b369b2329ee2537a91367ddc02a8dbfaf16b38f2d6c96b0` 유지 |
| v2 manifest | `cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39` 유지 |
| v2 15개 파일 tree SHA | `eea4dd83cfeb9d75ac0514e2f4fd334d846989cf1725e9ffeccfd0901d4e575d` 유지 |
| Round 10 canonical forecast | `a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7` 유지 |
| Round 10 22개 파일 tree SHA | `f667fd1a5226e546b5867225ff68c9b3dac2c6b041a0e6b4d7e9e92d3ad14e3a` 유지 |

검증한 실제 소스 바이트 SHA: registry `79bcfd969b9ea0eca9573862f19ffb786c36d146ffd27ee4fbb7cc4d7ed0589a`, pipeline `55dd1e2a85e04f1d5d4279ea5ed9231b4c096900de9a07ad109a934a8d1f419c`.

## 6. 남은 한계와 독립 리뷰 자료

- 승인자 ID·결정문·명시적 실행 플래그는 로컬 승인 절차다. 로그인·전자서명·신원 인증을 구현한 것은 아니며 승인 문서와 쓰기 권한은 사람이 관리해야 한다.
- 해시 체인은 변경 탐지용이며 WORM 저장소가 아니다. 모든 파일과 current를 함께 재작성할 수 있는 공격자에 대해서는 **외부에 보관한 승인 tip SHA**가 필요하다. `--expected-tip-sha256`으로 검증/비교 시 이를 대조할 수 있다. 로컬 해시만으로 인간 승인 진위를 공증하지 않는다.
- 원자 교체는 같은 로컬 파일시스템의 os.replace에 근거한다. 정전·저장장치 장애·분산 파일시스템의 내구성까지 입증하지 않았다.
- INCOMPLETE 상태의 자동 복구 기능은 없다. 파일을 보존한 채 결정문·판본·체인·외부 tip과 이전 current를 사람이 대조해야 하며, 복구 실행은 별도 명시적 절차가 필요하다. 불완전 레코드를 임의 삭제하거나 자동 승격하지 않는다.
- R11-06의 재처리 runtime 분리 기록은 선택 개선으로 남겼다. 기존 manifest는 수정하지 않았다. 공식 공표판/당시 이용 가능 시점·고객 소재 소비·예측 성능 검증은 승인 레지스트리의 권한 범위가 아니다.

새 API 수집·재처리·자동 예측·학습·실적 채점·KOSIS 수집·LLM/자율 Agent는 실행/추가하지 않았다. V1~Round 10 결과·지원서·기존 감사 파일도 보존했다. 이번 GitHub 공유 대상은 pipeline의 최소 확장, 새 registry 코드·합성 테스트·이 보고서다. 원본·개별 수치·승인 결정문·Claude 감사 원문은 공개하지 않는다.

Claude는 P0 정책 1/2 분리와 결측 차단, 후보·사람 승인 분리, append-only 사본/승인 체인, 원자 current의 실패 경계, 명시적 과거 기준선 비교, 실제 current 미생성 및 남은 신뢰 경계를 독립 검토할 수 있다. 최종 Commit/Push SHA는 완료 메시지로 전달한다.
