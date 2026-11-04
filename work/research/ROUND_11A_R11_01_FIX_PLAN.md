# ROUND 11-A — R11-01 정규화 결함 필수 보정 지시서

작성: 2026-11-04 KST / ChatGPT Orchestrator
상태: **Claude 독립 감사 CONDITIONAL PASS 수용. 수정·검증 전 Round 11-B 구현 보류.**

## 1. 감사 판정과 증거

- 감사 보고서(로컬 전용): `work/reviews/ROUND_11A_CLAUDE_AUDIT.md`
- 재현용 독립 감사 스크립트(로컬 전용): `work/reviews/ROUND_11A_audit_check.py`
- 검토 원본 run: `20261104T090724027444_cd96f70034a7`
- 공개 manifest SHA-256: `5f189a02ecbbd3bb24fea924ef8a0ca895a3018db8a19e015c7df2a0c40d33c6`
- Round 10 봉인 forecast SHA-256: `a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7`
- Claude 보고: 실제 72건 모두 UNCHANGED, 신규·과거값 변경·누락 0건, 해시/페이지/코드/판본 분리/키 비노출/append-only/봉인 불변 PASS.
- 필수 결함 `R11-01`: `number()`의 `str(Decimal(...).normalize())`가 지수표기를 만든다. `100 -> "1E+2"`, `90 -> "9E+1"`, `110 -> "1.1E+2"`. 실제 로컬 정규화 72행 중 **3행**이 이 형식이다. Decimal 수치 비교엔 영향 없지만 안정적인 텍스트 인터페이스에 부적합.
- Claude 판정 **CONDITIONAL PASS**. PASS 전환에는 고정 형식 보정, 버전 관리, 과거 run 보존/재검증과 동일 원문 재처리가 필요.

## 2. Codex 수정 범위 — 필수

1. 신규 `number()`는 유효한 Decimal을 **고정소수점 문자열**로 직렬화하며 지수표기를 내보내지 않는다. 예: `format(result.normalize(), 'f')` (0/-0의 정규화 정책도 일관되게). `100, 100.0, 1e2`는 모두 `"100"`; `90`은 `"90"`; `110`은 `"110"`. 범위 0~200/NaN·Inf 차단 유지. 원 API 원문 바이트 보존.
2. 새 실행의 `normalization_version=2`를 기록하고, 버전별 정규화 규칙을 **명시적으로 선택**한다. 서식 변화만으로 과거 '수치 변경'을 탐지하지 않도록 `Decimal` 수치 비교 유지.
3. **매우 중요:** 기존 run의 `--validate-run`은 `normalization_version=1` 규칙으로 원문부터 재연해야 기존 `normalized.json`·`diff.json`과 일치한다. 신규 v2 run은 v2 규칙으로 검증. 과거 폴더를 수정해 통과시키거나 과거 조회 실행을 다시 만들어 덮어쓰지 않는다. `baseline_rows()`, `normalize()`, `compare()`의 저장 문자열 변화를 포함해 양쪽 재연 전체를 점검.
4. 이미 확보한 11-A의 **동일 API 원문 응답 5개**를 네트워크 호출 없이 별도 신규 `work/data/local_only/round11_reprocessed/<new_id>/` 폴더에서 v2로 재정규화·비교한다. 원본 run ID/manifest SHA/원본 응답 SHA와 **새로 생성한 시각**을 연결하는 파생 manifest를 생성한다. 기존 관측 시간에 재수집한 듯 작성하지 않는다. 이 로컬 파생물은 비승격 상태 `NOT_PROMOTED`로 저장.
5. v2 재처리 결과의 행 수 72, 업종 36+36, 지수표기 0건, 기존 run의 지수표기 3건, Decimal 기준 변경 없음 72·신규/변경/누락 0건을 **독립 검증**. 해당 수치가 실제로 달라지면 멈추고 보고한다.
6. R11-A 원 run 파일 11개·원문 5개·공개 manifest SHA·Round 10 봉인 22개 파일·기존 V1~Round 10 산출물·지원서 3종 **모두 변경 금지**. 기존 감사 로컬 파일도 변경/커밋 금지.
7. 기존 pipeline `--collect`의 정상·격리·키 비노출·append-only·observed_at/publication_date 분리·모델 승격 차단을 유지. 자동학습/예측/채점 금지, KOSIS 확장·R11-B 개발 금지.

## 3. 필수 합성 테스트/회귀 테스트

- Decimal 입력 `"100"`, `"100.0"`, `"1E+2"`, `"90"`, `"110"`, `"0"`, `"200"`, `"12.3400"` 등의 v2 문자열 결과.
- `-0` 및 `0.0`의 일관성, `NaN/Infinity`와 범위 밖 수치 거부.
- v1 archived fixtures: 원본 100/90/110 → 과거 지수표기 보존, v1 manifest의 offline `--validate-run` PASS.
- v2 fixtures: 같은 원본 → 고정소수점, v2 offline 재검증 PASS.
- 숫자 표기만 달라졌을 때 `UNCHANGED`, 실제 수치가 달라졌을 때 `HISTORICAL_VALUE_CHANGED`.
- manifest SHA·원본 API 응답 SHA 변경 불변, 신규 파생물 별도 생성, API 0회 호출.
- 이전 Round 11-A 합성 테스트 9개 PASS 및 신규 보완 테스트 PASS.
- 원본·봉인/해시 검증 전후 변화 0건. 키·URL 노출 검사 PASS.

## 4. 별도 선택 개선 (이번 필수 판정에 섞지 않음)

- 기준선 내부 누락월을 `NEW_TARGET_MONTH`로 오분류할 수 있음: Round 11-B의 승인 기준선 레지스트리 도입 전 연속성 검사를 우선 과제로 관리. 단, 현재 정상 36개월/업종 판정에는 영향 없음.
- 실제 값 변경 감지 시 `exit_code=0`: 정상 수집·검토 필요를 구별할 CLI 상태 정책 선택.
- 코드 작업 트리 clean/dirty와 실행 소스 해시 기록.
- manifest 없이 남는 부분 실행 폴더를 INCOMPLETE로 식별.
- 이 네 항목은 **선택 개선**으로 분류하며 `R11-01` 수정을 불필요하게 확대하지 않는다.

## 5. 완료·Push

- 코드 수정: `work/research/round11_ecos_snapshot_pipeline.py` (필요한 최소 변경).
- 테스트: `work/research/test_round11_pipeline.py` 및 v1/v2 검증 합성 테스트.
- 요약: `work/research/ROUND_11A_R11_01_FIX_REPORT.md`에 수정 전후 출력형식, 실제 72행의 정규화 차이 3건, 변경 분류 불변 72건, 원본 run/봉인 해시 불변, 오프라인 재연 상태와 새 파생 SHA 기재. **개별 관측값 및 인증키는 보고/Push 금지**.
- GitHub에는 코드·테스트·요약 보고서만 commit/Push. `work/data/local_only/` 내 수치/원본·감사 로컬 원문은 공유 금지.
- 최종 Codex 요약에 커밋 SHA, v1 run `--validate-run` PASS, v2 오프라인 72행 PASS, 합성 테스트 수, 봉인 해시 불변을 포함.
- **Claude 독립 재감사 후 PASS일 때만** `ROUND_11B_PLAN.md` 구현 착수.
