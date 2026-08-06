# SPEC-AI-106 Plan

## A. 구현 전략

Tier S, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 spec.md §Goals 1-5에 근거한 배선(기존
판정 함수를 기존 스케줄러 잡에 호출)과 문서화(활성화 검토 절차)에 한정하며, SPEC-AI-100/101
소유의 판정·영속화 로직, `enabled`/`shadow_mode_enabled` 실제 값, 앙상블/게이팅/매매
실행 경로는 건드리지 않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **검토 절차(§C)의 내용 확정** — 가장 되돌리기 어려운 결정이다. 이 절차는 향후 실제
   `enabled=true` 전환 SPEC이 직접 참조할 판단 기준(관측 완료 확인 방법, 임계값 튜닝
   여부, 승인/롤백 경로)이므로, 부실하게 작성하면 그 후속 SPEC이 다시 처음부터 판단
   기준을 세워야 한다. TASK-002에서 SPEC-AI-105 §C 패턴을 계승해 먼저 확정한다.
2. **로그 통합 지점과 필드 스키마**(spec.md REQ-AI106-001) — 배포 이후 바꾸려면
   journalctl 검색 패턴이 달라지므로 중간 가역성. TASK-001에서
   `_run_surge_verify_predictions`의 기존 격리 블록 패턴(SPEC-AI-086
   `diagnose_non_scannable_causes`)을 그대로 따르는 형태로 확정한다.
3. **fail-open 격리 방식**(spec.md REQ-AI106-004) — 기존 잡의 다른 격리 블록과 동일한
   `try/except` 패턴을 재사용하므로 사실상 기계적 결정.
4. **테스트 파일 구성** — 가장 가역성이 높다(테스트 추가/조정은 언제든 반복 가능).

### A.1 PRESERVE 목록(수정 금지)

| 대상 | 사유 |
|------|------|
| `check_horizon_transition_readiness()` 함수 본체(`surge_horizon_readiness_service.py`) | REQ-AI106-003 — 호출만 하며 내부 판정 로직(3요건 임계값 상수 포함)은 절대 수정하지 않는다 |
| `run_horizon_shadow_comparison()`, `compute_horizon_signature()`, `select_effective_threshold()` | SPEC-AI-100 소유 — 판정 로직 무변경 |
| `SurgeHorizonShadowObservation` 모델 스키마 | SPEC-AI-101 소유 — 신규 컬럼/테이블 추가 금지(REQ-AI106-006) |
| `ensemble.horizon_aware_thresholds.enabled` (실제 값 `false`) | REQ-AI106-002 — 이 SPEC 배포 후에도 `false` 유지 |
| `ensemble.horizon_aware_thresholds.shadow_mode_enabled` (실제 값 `true`) | REQ-AI106-002 — 이 SPEC 배포 후에도 `true` 유지 |
| `ensemble.horizon_aware_thresholds.thresholds` 블록의 수치 | §Decisions D4 — per-horizon 임계값 튜닝은 범위 밖 |
| `evaluate_surge_predictions()`의 predicted_set/actual_set/legacy_recall/scannable_recall 산출 로직 | REQ-AI106-001 구현은 이 함수 이후 시점에 격리 블록만 추가 — 평가 로직 자체 무변경 |
| `_run_surge_verify_predictions`의 기존 격리 블록들(`diagnose_non_scannable_causes`, FN/TP 분석) | 신규 블록을 추가만 하며 기존 블록 순서·내용은 무수정 |

## B. 작업 분해

### TASK-001: 일일 평가 잡에 readiness 로그 통합

- 대상: `backend/app/services/scheduler.py` `_run_surge_verify_predictions()`
  (verified 2026-08-06 기준 `evaluation` 커밋 직후, 970번대 `diagnose_non_scannable_causes`
  격리 블록 인근 — 정확한 삽입 지점은 그 블록 바로 다음).
- 구현: `check_horizon_transition_readiness` import 후, 기존
  `diagnose_non_scannable_causes` 블록과 동일한 형태의 신규 `try/except` 블록을
  추가한다:
  ```
  try:
      from app.services.surge_horizon_readiness_service import (
          check_horizon_transition_readiness,
      )
      readiness = check_horizon_transition_readiness(db)
      logger.info(
          "[지평임계값전환게이트] observed_trading_days=%d regimes=%s "
          "max_change_pct=%.2f all_criteria_met=%s",
          readiness["observed_trading_days"],
          sorted(readiness["regimes_observed"]),
          readiness["max_change_pct"],
          readiness["all_criteria_met"],
      )
  except Exception as _hre:
      logger.warning("[지평임계값전환게이트] readiness 조회 실패 (무시): %s", _hre)
  ```
- 이 블록은 `db.commit()`(핵심 평가 결과 저장) 이후에 위치해야 한다 — 이 블록의 실패가
  핵심 평가 결과 저장에 영향을 주지 않도록 하기 위함(REQ-AI106-004).
- 추적 REQ/AC: REQ-AI106-001, REQ-AI106-004 / AC-106-001, AC-106-002, AC-106-003

### TASK-002: 활성화 검토 절차 문서화(§C, 본 문서 하단)

- 대상: 본 plan.md §C(아래).
- SPEC-AI-105 §C 패턴(관측 기간 확보 → 판단 기준 문서화 → 실제 전환은 별도 SPEC)을
  재사용해, 3요건 판정 확인 방법 + per-horizon 임계값 튜닝 판단 기준 + 승인/롤백
  경로를 명문화한다.
- 추적 REQ/AC: REQ-AI106-005 / AC-106-007

### TASK-003: characterization 테스트 + 회귀 검증

- 신규: `test_spec_ai_106.py` — TASK-001 로그 통합(정상 호출 시 로그 필드 4개 포함
  확인, 예외 주입 시 evaluation 커밋 보존 확인), `enabled`/`shadow_mode_enabled` 값
  불변 확인, `check_horizon_transition_readiness` 호출 카운트가 잡 사이클당 1회임을
  확인.
- 회귀: `uv run pytest tests/test_spec_ai_100.py tests/test_spec_ai_101.py -q` 전체
  통과 확인(SPEC-AI-100/101 판정 로직 diff 0 검증).
- 추적 REQ/AC: REQ-AI106-002, REQ-AI106-003, REQ-AI106-006 / AC-106-004, AC-106-005,
  AC-106-006, AC-106-008

## C. 활성화 검토 절차 (REQ-AI106-005 산출물)

본 절차는 향후 `horizon_aware_thresholds.enabled`를 `true`로 전환하는 결정을 실제로
내리는 세션이 따라야 할 체크리스트다. 본 SPEC은 이 절차를 문서화만 하며 실행하지
않는다(§Non-Goals).

1. **관측 완료 확인**: TASK-001 배포 이후 journalctl에서
   `[지평임계값전환게이트]` 태그로 로그를 검색해(예:
   `journalctl -u newshive | grep '지평임계값전환게이트'`) 가장 최근 로그의
   `all_criteria_met=True` 여부를 확인한다. `False`이면 아직 전환을 검토할 시점이
   아니다 — 관측을 계속한다. 대안으로 `check_horizon_transition_readiness(db)`를
   직접 호출하는 임시 스크립트로도 동일 정보를 확인할 수 있다(로그가 유실됐거나
   더 정밀한 조회가 필요한 경우).
2. **per-horizon 임계값 재검토**: `all_criteria_met=True`가 확인되면, 현재
   `surge_detection.yaml`의 `thresholds` 블록이 여전히 `regime_thresholds`와 동일한
   placeholder 값인지 확인한다(§Decisions D4). placeholder 그대로 전환할지, 관측
   기간의 qualified 집합 변화 패턴(added/removed 종목 코드, 어떤 지평 시그니처에서
   변화가 집중됐는지)을 근거로 지평별 값을 조정할지 판단한다. 조정 방법론(규칙 기반
   수동 조정 vs 통계적 접근)은 이 시점에 확정한다(spec.md Open Question 3).
3. **판단 기준(문서화만, 실제 실행은 범위 밖)**:
   - 구조 요건(REQ-AI100-009 3요건, `all_criteria_met=True`)은 필요조건이지 충분조건이
     아니다 — 변화폭이 ±30% 이내라는 것은 "급변하지 않았다"는 안전 신호일 뿐, "지평
     인식 임계값이 기존보다 더 나은 예측을 만든다"는 증거는 아니다.
   - 관측 기간 중 `qualified` 집합의 added/removed 종목이 실제로 급등했는지(사후
     정밀도)를 `SurgeActualOutcome`과 교차 확인하는 것을 권장한다 — 단, 이 교차 분석
     함수는 본 SPEC이 신설하지 않는다. 필요 시 이 확인 자체가 별도 후속 SPEC의
     범위가 될 수 있다.
   - 2026-07-28 `theme_news_carry` 자기강화 피드백 루프 사고 재발 방지를 위해, 전환
     직후 첫 며칠간은 섀도우 로그와 실제 전환 후 로그를 나란히 비교 관찰하는 것을
     권장한다(자동화된 비교는 본 SPEC 범위 밖).
4. **전환 실행**: 위 검토를 거쳐 전환하기로 결정되면, `surge_detection.yaml`의
   `ensemble.horizon_aware_thresholds.enabled: false → true` 단일 값 변경으로
   충분하다(SPEC-AI-100 D5가 이미 이 방식을 설계했다). 이 전환은 **별도 SPEC 또는
   운영 판단**으로 상정한다 — 본 SPEC의 배포 산출물이 아니다.
5. **롤백 경로**: 전환 후 이상 징후(qualified 집합 급변, precision 급락)가 관측되면
   `enabled`를 즉시 `false`로 되돌린다(단일 값 변경, 데이터 손실 없음 — 섀도우 관측
   테이블 행은 그대로 보존된다).

## D. 위험

| 위험 | 완화 |
|------|------|
| 로그 통합만으로는 사람이 실제로 주기적으로 로그를 확인하지 않아 "죽은 관측 경로"가 재발할 가능성 | journalctl 검색 명령을 §C 절차 1항에 구체적으로 명시 — 향후 필요 시 저빈도 요약 잡으로 확장 가능(spec.md Open Question 2, 본 SPEC 범위 밖) |
| readiness 조회가 매 사이클마다 반복 호출돼 불필요한 쿼리 부하가 발생할 가능성 | REQ-AI106-001 필수 조건으로 하루 1회(18:30 KST 잡 사이클당) 호출만 허용 — TASK-003 테스트로 호출 카운트 검증 |
| readiness 조회 예외가 핵심 평가 결과 커밋에 영향을 줄 가능성 | REQ-AI106-004 — `db.commit()`(핵심 결과 저장) 이후 위치한 격리된 `try/except` 블록으로 구현, TASK-003에서 예외 주입 테스트로 검증 |
| 향후 세션이 §C 절차를 건너뛰고 구조 요건(3요건)만으로 즉시 전환할 위험 | §C 3항에 "구조 요건은 필요조건이지 충분조건이 아니다"를 명시적으로 기록 |
