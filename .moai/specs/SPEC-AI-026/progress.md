# SPEC-AI-026 진행 기록 — DDD 버그픽스 (2026-07-02)

## 배경

`detect_forum_mention_surge()`는 이미 구현되어 파이프라인에 연결되어 있었으나, spec.md
요구사항과 실제 코드 사이에 정밀 대조 결과 1건의 불일치가 발견되어 DDD
(ANALYZE-PRESERVE-IMPROVE) 사이클로 수정했다.

## 수정 항목

### 1. `surge_metadata` 키명 불일치

- **재현 테스트**: `test_bugfix_ai026_surge_metadata_uses_spec_key_names`
- **수정 전**: `{"surge_basis": [...], "recent_count": ..., "baseline_avg": ..., "ratio": ...,
  "surge_probability_score": ...}`
- **수정 후**: `{"surge_basis": [...], "mentions_recent": ..., "baseline_avg_daily": ...,
  "mention_ratio": ..., "surge_probability_score": ...}`
- 다운스트림 소비자를 `grep -rn "mentions_recent\|recent_count"` 로 확인한 결과 테스트 파일
  외 참조가 없어 하위호환 키 병기 없이 전면 교체.

## 판단이 필요했던 애매한 항목 (수정하지 않음)

### 중복 방지 범위: spec(3개 signal_type) vs 코드(오늘 발행된 모든 signal_type)

**판단: 유지 (코드의 넓은 범위가 더 안전한 설계)**

SPEC-AI-023에 적용한 것과 동일한 판단 기준. spec.md는 surge_candidate/theme_propagation/
volume_anomaly 3종만 중복 방지 대상으로 명시하지만, `existing_ids`는 `FundSignal.stock_id`
전체(signal_type 무관, `created_at >= today_kst_start` 조건만)를 수집한다.
`_run_coverage_expansion()`에는 본 SPEC 이후에도 SPEC-AI-027(그룹cascade),
SPEC-AI-050(주말갭업) 등이 추가로 연결되어 있어, 3종으로 범위를 좁히면 이들 신규
signal_type과의 교차 중복 발행 위험이 재도입된다. 넓은 범위가 더 안전한 설계로 판단하여
유지했다.

## 변경하지 않은 항목

- config 필드/기본값(`mention_multiplier=5.0`, `min_absolute_mentions=10`,
  `baseline_days=7`, `mention_window_hours=24`, `max_confidence=0.35`)은 이미 SPEC과 일치.
- confidence 공식(`round(min(recent_count/baseline_avg/20.0, max_confidence), 4)`)은
  `ratio/20.0`과 수학적으로 동일하여 이미 일치.
- baseline_avg=0 스킵(division-by-zero 가드) 로직은 이미 일치.

## 테스트 결과

- `backend/tests/test_forum_mention_surge.py`: 7 passed (기존 6 + 신규 1)
- 전체 회귀: 1791 passed, 4 skipped, 3 xpassed (0 failed)
- `ruff check .`: All checks passed
