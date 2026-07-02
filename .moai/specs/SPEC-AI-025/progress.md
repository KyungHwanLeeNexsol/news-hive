# SPEC-AI-025 진행 기록 — DDD 버그픽스 (2026-07-02)

## 배경

`detect_theme_group_carry_forward()`는 이미 구현되어 파이프라인에 연결되어 있었으나, spec.md
요구사항과 실제 코드 사이에 정밀 대조 결과 2건의 불일치가 발견되어 DDD
(ANALYZE-PRESERVE-IMPROVE) 사이클로 수정했다.

## 수정 항목

### 1. `surge_metadata` 키명 불일치 (`theme_group_id` 완전 누락 포함)

- **재현 테스트**: `test_bugfix_ai025_surge_metadata_uses_spec_key_names`
- **수정 전**: `{"surge_basis": [...], "anchor_stock_id": ..., "anchor_change_rate": ...,
  "theme_group": ..., "surge_probability_score": ...}`
- **수정 후**: `{"surge_basis": [...], "anchor_stock_code": anchor_stock.stock_code,
  "anchor_change_pct": round(change_rate, 2), "theme_group_id": group.id,
  "theme_group_name": group.name, "surge_probability_score": ...}`
- `theme_group_id`는 SPEC이 요구했으나 기존 구현에 아예 없던 키. 다운스트림 소비자(백테스트,
  리포트 등)를 `grep -rn "anchor_stock_id\|anchor_change_rate"` 로 확인한 결과 테스트 파일
  외 참조가 없어 하위호환 키 병기 없이 전면 교체.

### 2. 완료 로그 포맷 불일치

- **재현 테스트**: `test_bugfix_ai025_log_format_matches_spec`
- **수정 전**: `logger.info("[theme_group_carry] 시그널 %d건 생성", len(signals))` (조건부:
  `if signals:` 블록 내부에서만 로깅)
- **수정 후**: `groups_evaluated` 카운터를 앵커 종목 조회 성공 시점마다 증가시키고,
  `logger.info("[테마그룹강세] 평가 %d개 그룹, 시그널 %d건 생성", groups_evaluated,
  len(signals))`를 함수 종료 시점에 항상(시그널 0건이어도) 실행하도록 변경. SPEC 요구사항
  ("본 단계가 완료될 때... 로깅한다")과 일치.

## 변경하지 않은 항목

- confidence 공식(`round(anchor_change_rate / 30.0 * 0.4, 4)`), `max_signals_per_group`
  상한, anchor 자신 제외, 크로스 그룹 중복 방지(`emitted_codes`)는 이미 SPEC과 일치하여
  건드리지 않음.
- `fund_manager._run_coverage_expansion()`의 통합 지점 wrapper 로그
  (`"[theme_group_carry] 완료 — %d건"`)는 사용자가 제시한 버그 목록에 없어 스코프 밖으로
  판단, 변경하지 않음.

## 테스트 결과

- `backend/tests/test_theme_group_carry.py`: 7 passed (기존 5 + 신규 2)
- 전체 회귀: 1791 passed, 4 skipped, 3 xpassed (0 failed)
- `ruff check .`: All checks passed
