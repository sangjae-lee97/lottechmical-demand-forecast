# ROUND 11-B — R11-02 우선 수정 및 인간 승인 기반 v2 기준선 레지스트리

상태: **구현 착수 승인** (2026-11-04 KST). Claude의 Round 11-A R11-01 재감사 PASS를 수용했다.
선행 근거: `ROUND_11A_R11_01_FIX_REPORT.md`, `ROUND_11A_R11_01_AUDIT_ACCEPTANCE.md`.
기본 원칙: 수집 성공 ≠ 사람 승인 ≠ 공식 최초 공표 판본 검증 ≠ 모델 입력 승인.

## 1. 목표 및 입력

실측 ECOS `StatisticSearch / 512Y008 / M / BD`의 자동차 `C3000`·제조업 `C0000` BSI 조회 스냅샷을 데이터 품질과 판본에 따라 검증한 뒤, **사람이 명시적으로 승인한 v2 스냅샷만** 후속 비교의 기준선으로 채택할 수 있는 로컬 레지스트리를 만든다. 모든 입력은 로컬 기록이며 이번 단계에서 ECOS/API 재호출은 불필요하다.

- 레거시 원 수집: `round11_snapshots/20261104T090724027444_cd96f70034a7`, `normalization_version=1`, 공개 manifest SHA `5f189a02ecbbd3bb24fea924ef8a0ca895a3018db8a19e015c7df2a0c40d33c6`. **재현·감사만**, 승인 기준선으로 직접 채택 금지.
- v2 파생 수집: `round11_reprocessed/20261104T101726512529_3228efd3efd1`, `normalization_version=2`, 공개 manifest SHA `cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39`. **검증된 후보이지만 승인 전**.
- 별도 Round 07-C 최초 `normalized_snapshot.json`은 역사적 프로젝트 비교 기준점으로 보존. 이것을 인간이 승인한 v2 판본이라고 조용히 명명하거나 교체하지 않는다.
- Round 10 봉인 JSON SHA `a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7` 및 22파일 전체 트리 SHA `f667fd1a5226e546b5867225ff68c9b3dac2c6b041a0e6b4d7e9e92d3ad14e3a`는 불변.

## 2. P0 — R11-02 기준선 내부 중간 월 누락 방지 (먼저 구현·검증)

- **승인 후보, 승인된 기준선, 비교 입력 모두** 업종별 기대 월 목록이 `첫 월~끝 월` **중간 공백 없이 연속**되는지 검사한다. 월 파싱, 중복, 동일 업종 코드, BSI 전망 대상월·조사월 매핑도 검사. 자동차와 제조업의 월 범위가 같아야 한다는 기존 정책을 지킨다.
- **기간 내 누락은 INVALID_OR_UNVERIFIED / BASELINE_INTERNAL_GAP 등의 검증 오류로 격리.** 새 조회가 빠진 과거 월을 채웠다고 하더라도 `NEW_TARGET_MONTH`로 정상 처리하거나 승인하지 않는다. 누락이 있는 데이터셋은 검토 대상으로만 관리하고 정상 baseline/승인 후보로 승격하지 않는다.
- 진짜 신규 월은 **승인된 기준선의 마지막 대상월 다음 연속 월**이어야 한다. 기준선 첫 월 이전 추가 이력은 신규 도착 데이터로 별도 `HISTORICAL_EXTENSION` 또는 검토 필요 상태로 구분하고, 임의 신규 월처럼 섞지 않는다. 최초 관측기간이 바뀐 경우 이전 판본과 비교 정의를 명시한다.
- **레거시 아카이브 재현성 보존**: 이미 보관된 v1·v2 원 run의 `--validate-run` / `--validate-reprocessed` 결과와 normalized/diff **바이트 단위 재연을 변경하지 않는다**. 새 검증 규칙은 신규 승인 후보 검증 및 신규 비교 경로에 적용하고, 과거 버전 재연에는 명시적으로 호환 정책을 둔다. 기존 archive manifest를 다시 쓰지 않는다.
- 합성 테스트 최소: 기준선 `2026-09, 2026-11`에서 10월 결측 + 신규판 9~11월 연속 → **승격 차단**; 정상 9~11월 + 12월 신규 → NEW_TARGET_MONTH 1건; 새 후보 중간 결측/중복/업종간 월 범위 차이 → 격리; 연도 전환 12월→1월 정상.
- P0 완료 전에는 승인 레지스트리 기능을 실제 기준선으로 활성화하지 않는다.

## 3. P1 — 로컬 append-only v2 승인 레지스트리

- 로컬 경로 `work/data/local_only/round11_registry/`. 승인 이력은 **append-only 파일/연쇄 해시**로 보존하고, 현재 활성 `current` 포인터만 원자 교체. 이전 승인 기록/스냅샷 데이터를 수정·삭제하지 않는다. 중간 크래시·부분 쓰기 시 fail-closed하고 INCOMPLETE 표시 또는 안전한 복구 경로 명시.
- 최초 부트스트랩은 "historical_project_reference"로 Round 07-C 원본 SHA를 등록 가능하지만, 이는 **human_approved_v2가 아님**. 사람 승인 전 current approved pointer를 만들지 않는다.
- 승인 후보는 `v2` 성공/검증 판본만 허용하고 `normalization_version == 2` 확인. `OFFLINE_REPROCESSED`는 원 부모의 조회 기록과 정규화 체인까지 검증. `v1`·실패/격리·변조·중간 월 누락·지수표기·키/코드/업종 불일치 판본 승인 불가.
- 명시적 로컬 승인 결정 문서(리뷰어 ID/시각/승인 사유/승인 범위/근거 URI 또는 해시/남은 한계)를 사전에 검증하고 **사용자의 실제 승인 없이 dry-run만 수행**. `--approve` 명령이 있다고 해서 자율 Codex 실행으로 실제 데이터를 승격하지 않는다. 허위 인간 승인 생성 금지.
- `approval`은 운영상의 '비교 기준선 사용' 허가이며 `vintage_verified_for_origin`/공표일/해당 고객 수요의 검증을 자동으로 참으로 바꾸지 않는다.
- 승인 레코드에 참조할 불변 스냅샷 경로/원본 manifest SHA/normalized SHA/버전/승인결정문 해시/이전 승인 ID/승인 체인 해시, 모델 승격 여부 false 등을 기록. 해시·이력 검증 실패 시 current 포인터 갱신 불가.

## 4. P2 — 명시적 승인 기준선과 비교

- `--baseline-id <id>` 또는 `--registry-current` 같이 **명시적 선택 인자**를 제공. 사용자가 승인하기 전에는 기존 Round 07-C 기준과 비교하는 레거시 경로를 유지하되, 이 기준을 **human approved**로 표기 금지.
- v2 승인된 기준선과 v2 조회/파생 스냅샷 비교는 월·업종·항목코드·Decimal 수치 기준. 정상 `UNCHANGED`, `NEW_TARGET_MONTH`, `HISTORICAL_VALUE_CHANGED` 외에 중간 결측 오류 및 window 축소를 구분. 새 값 변경을 공식 정정이라고 자동 단정 금지.
- 진짜 신규 월을 v2 후보로 승인한 후, **같은 후보를 다시 비교하면 신규 월이 UNCHANGED**로 재분류돼야 함을 합성 픽스처로 증명.
- 비교 대상 선택/포인터/승인 ID의 원본 SHA와 실행 코드를 결과에 기록. 새 판본이 생겨도 승인없이 포인터 자동 갱신 금지.
- 코드/테스트를 위해 기존 `round11_ecos_snapshot_pipeline.py`를 최소 확장하거나 별도 `round11_baseline_registry.py` 작성 가능. v1/v2 과거 아카이브 검증 CLI를 파괴하지 않는다.

## 5. 범위와 보안

- 공식 API **추가 호출 없이** 로컬 기존 아카이브를 읽고 합성 데이터로 구현/테스트. 신규 실제 BSI 발표일·공표판 확인을 했다고 단정하지 않는다.
- 원본·정규화·관측별 값·키/키 포함 URL·사람 승인 결정 문서·Claude 감사 원문은 GitHub 업로드 금지. `work/data/local_only/` 또는 `work/reviews/` 로컬 보관. 공개 repo에는 코드·합성 테스트·변경 건수/해시·설계/결과 보고서만.
- Round 10 봉인 재생성/수정/채점 금지; V1·Round 07~10 결과와 지원서 파일 수정 금지. 새 모델 학습, KOSIS 자동 수집, 스케줄러·웹 UI·LLM Agent는 범위 외.
- **R11-06**: v2 재처리 manifest가 v1 런타임 문자열을 상속하는 점은 선택 개선으로 분류. 향후 `source_runtime`/`reprocessing_runtime` 메타데이터를 별도로 기록할 수 있으나 P0/P1/P2 범위를 지연하지 않는다. 기존 manifest 수정 금지.
- 다른 개선: 단순 변경 발견 시 exit_code=0 정책, dirty worktree 기록, 미완료 아카이브 표시 등은 발견/권고만. 필수 기능을 복잡하게 만드는 대규모 재설계 금지.

## 6. 산출물/완료 기준

- 규칙형 CLI/승인 레코드 스키마/구현 코드와 합성 테스트, `work/research/ROUND_11B_IMPLEMENTATION_REPORT.md`.
- **1차 증거:** R11-02 결측 오분류 재현 및 수정, 신규 경로에서 fail-closed, v1/v2 과거 오프라인 재연 PASS.
- **2차 증거:** 승인 레지스트리의 append-only/원자 포인터 갱신/실패·변조 거부, 수동 승인 dry-run. 실제 v2 스냅샷은 후보 검증만 하고 **인간 승인 상태로 변경하지 않음**.
- **3차 증거:** 합성 자료로 승인 전/후 NEW_TARGET_MONTH→UNCHANGED, 과거 승인 ID 비교 재현 가능.
- Round11-A 기존 9+7 테스트 재실행, 신규 합성 테스트, Round10 22개 파일 해시 불변, 키/원본 공개 없음.
- 코드·테스트·집계 보고서만 commit/Push, 명시적 commit SHA 및 사용자 보고.
- Claude 후속 독립 리뷰는 P0 결측/분류 거짓 양성, 승인 기록 위변조, 원자적 포인터, 자율 승인 여부, v1/v2 재현성, 봉인 보존을 점검.

## 7. Codex 권한 경계

Codex는 위 기능을 **개발하고 합성 시나리오를 검증**할 수 있다. 그러나 사용자가 명시적으로 특정 v2 run과 근거를 승인하기 전에는 실제 운영 `current` 포인터를 생성/변경하거나 실제 통계판본을 human-approved로 기록할 수 없다. 구현 완료와 운영 데이터 승인 결정을 엄격히 분리한다.
