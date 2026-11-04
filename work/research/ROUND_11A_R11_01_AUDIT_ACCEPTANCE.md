# ROUND 11-A — Claude R11-01 독립 재감사 수용

수용일: 2026-11-04 KST
**판정: PASS 수용. ROUND 11-B 구현 착수 가능.**

사용자가 전달한 Claude 독립 재감사 요약을 근거로 수용했다. 로컬 감사 보고서 `work/reviews/ROUND_11A_R11_01_CLAUDE_REAUDIT.md`와 재현 스크립트 `ROUND_11A_R11_01_reaudit_check.py`는 **로컬 전용이며 GitHub 공유 대상이 아니다.** Orchestrator가 해당 로컬 원본의 바이트를 직접 독립 재계산한 것으로 표현하지 않는다.

### 수용 근거

- 기존 v1 아카이브의 지수표기 문자열 **3건 유지**; 신규 v2 정규화·diff의 지수표기 **0건**.
- 원 API 응답 5개 및 기존 기준선 사본은 v1/v2에서 바이트와 SHA-256 일치. 원본 72개 수치 = v1 72개 = v2 72개, 문자 표기 변경은 3행.
- v1/v2 normalized.json·diff.json **바이트 재연 PASS**, 오프라인 검증 PASS. 잘못된 해시 또는 저장영역/버전 불일치는 거부.
- v1 manifest `5f189a02ecbbd3bb24fea924ef8a0ca895a3018db8a19e015c7df2a0c40d33c6`, v2 파생 manifest `cb6ad8f6b0c4a02ccd496a741cbbcabf4e498bd45f7c9608a8431e404ce53f39`.
- v1 전체 13파일 해시 트리 `4ccf4aedcdd2d09a4b369b2329ee2537a91367ddc02a8dbfaf16b38f2d6c96b0` 변동 없음.
- 원 응답 `observed_at` 불변, 신규 `processed_at` 별개. API 재호출·재처리 명령 실행 없이 감사 진행.
- Round 10 봉인 22개 파일 해시 불변: forecast `a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7`, tree `f667fd1a5226e546b5867225ff68c9b3dac2c6b041a0e6b4d7e9e92d3ad14e3a`.
- 합성 테스트 기존 9 + 신규 7 = **16 PASS**, 경계값 추가 점검. 새 필수 결함 없음.

### 후속 쟁점

1. **R11-02 필수 선행:** 기준선 내부에 월이 비었을 때, 재수집 월을 `NEW_TARGET_MONTH`로 잘못 표시하는 거짓 양성 차단. 정규화/새 기준선 승인 전 fail-closed.
2. **v2 전용 승인 기준선:** v1은 과거 재현·감사 전용. 기존 Round 07-C 기준선은 역사적 프로젝트 기준점이며, 자동으로 '사람이 승인한 v2'로 명명하지 않는다. v2 파생 스냅샷도 아직 운영 기준선으로 인간 승인되지 않음.
3. **R11-06 선택 개선:** v2 재처리 manifest가 v1의 `runtime`을 상속함. `source_runtime`과 `reprocessing_runtime`을 구분하면 출처가 명확해진다. 과거 판본 수정 없이 향후 스키마에서 개선 가능.
4. 수집 코드·문서 감사의 PASS는 미래 예측력, 원 공표 판본 검증, 고객별 PC/ABS 소비 정확성의 증거가 아니다.

판정: **ROUND 11-A 필수 결함 종료 / ROUND 11-B 착수 승인**.
