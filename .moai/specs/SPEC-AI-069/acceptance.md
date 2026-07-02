# SPEC-AI-069 인수 조건 (acceptance.md)

## Definition of Done

- [ ] REQ-001~005 전부 구현, 각 REQ에 대응하는 테스트 존재
- [ ] backtest가 스케줄러 정기 잡으로 실행되고 pass/fail 판정이 영속화됨(REQ-001)
- [ ] 자동개선 잡 비활성 + `surge_detection.auto.yaml`이 base 기본값(min_score=0.38, legacy 복원)으로 리셋(REQ-002)
- [ ] 자동개선 재활성 경로가 backtest 가드 + Scannable Recall 목표를 요구(REQ-003)
- [ ] z-score flag 기본 DISABLED, 기본 실행이 절대채점으로 폴백(REQ-004)
- [ ] calibrator 부재/무효 상태 표면화 + 학습연결/명시적 제거 반영(REQ-005)
- [ ] 테스트 85%+, `ruff`/`mypy` 무경고, 전체 급등 스위트 회귀 없음, 매수 로직 diff 0

---

## Scenario 1: 자동개선 전면 중단 + 기본값 리셋 (REQ-002, D4)

**Given** 배포 전 `surge_detection.auto.yaml`에 auto-improver가 드리프트시킨 값
(예: `min_score_for_signal=0.44`, 일부 탐지기 가중치 0)이 들어 있을 때,
**When** SPEC-AI-069가 배포되면(Phase 1),
**Then** 자동개선 스케줄러 잡이 실행되지 않고(`auto_improve_enabled=false` 또는 미등록),
`surge_detection.auto.yaml`이 base `surge_detection.yaml` 기본값으로 리셋되어
`min_score_for_signal=0.38`, `legacy_detectors` 가중치가 base 값으로 복원된다.
**And** `reload_surge_config()` 이후 활성 config가 리셋값을 반영한다.

## Scenario 2: z-score 회귀가 flag로 격리되어 기본 절대채점으로 동작 (REQ-004, D3)

**Given** `relative_scoring.zscore_enabled`의 기본값이 `false`일 때,
**When** 신호 생성 채점이 실행되면,
**Then** `zscore_to_score`(sigmoid) 정규화 경로를 우회하고 AI-065 이전의 절대 점수 기반으로
채점한다.
**And** flag를 `true`로 바꾸려면 backtest(REQ-001)가 z-score 기준 임계값·가중치를 재도출·통과한
증거가 있어야 한다(그 전에는 재활성 금지).

## Scenario 3: backtest 미통과 제안은 자동개선에서 거부된다 (REQ-001/003)

**Given** 자동개선이 (REQ-002 이후) 재활성된 상태이고, 제안된 가중치 변경이 backtest canary에서
**fail** 판정을 받았을 때,
**When** `analyze_and_improve`가 해당 제안을 반영하려 하면,
**Then** 시스템은 `_write_auto_yaml`을 호출하지 않고 현재 config를 그대로 유지한다(가드 작동).
**And** 자동개선의 최적화 목표는 혼재된 recall이 아니라 Scannable Recall(SPEC-AI-068)이다.

---

## Edge Cases

- **EC-1 (base yaml에 legacy 기본값 모호)**: 리셋 대상 수치는 코드 상수가 아니라 커밋된 base
  `surge_detection.yaml`에서 읽어 적용한다(stale 하드코딩 금지). base에 없으면 리셋 항목에서 제외+로그.
- **EC-2 (backtest 데이터 부족)**: 평가 이력이 부족해 backtest 판정 불가 시 verdict=`insufficient`로
  저장하고, 자동개선 가드는 이를 "미통과"로 취급(보수적)한다.
- **EC-3 (068 미완 상태에서 REQ-003)**: Scannable Recall 미가용 시 자동개선 재활성을 차단한다
  (M1/M2만 배포 가능, M3는 068 완료 전 착수 금지).
- **EC-4 (calibrator 데이터 부족)**: 학습 샘플 부족으로 (a) 학습 불가 시 (b) 명시적 제거 경로를
  택하되, 무효 상태를 리포트에 반드시 표기한다.
- **EC-5 (스케줄러 잡 충돌)**: backtest 잡 KST 시각이 기존 잡(18:30 평가 등)과 겹치지 않도록
  distinct id + 비충돌 슬롯으로 등록(replace_existing 클로버 방지).
- **EC-6 (배포 중 신호 생성)**: Deploy Guard 15:15~15:45 KST 창을 준수, 신호 생성 중 배포 금지.

## 품질 게이트 (Quality Gates)

- Phase 1 배포 후 활성 config 스냅샷이 base 기본값과 일치함을 로그로 증빙.
- backtest 잡 실행 로그 + 판정 레코드 생성 증빙.
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과.
- 예측기록 모드 확인: 매수/포트폴리오 파일 diff 0.
