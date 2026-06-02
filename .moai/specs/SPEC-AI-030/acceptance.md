# SPEC-AI-030 Acceptance Criteria

거래량콤보 탐지기 추격매수 방지 게이트의 수용 기준.

## Acceptance Criteria Table

| ID | 기준 | 검증 방법 (pytest) |
|---|---|---|
| AC-SURGE-030-001 | change_rate >= overheat_change_pct(+5.0)인 combo 후보는 탐지기 출력에서 제외 | z-score·뉴스 통과 + change_rate=+9.0 fixture → results 미포함 |
| AC-SURGE-030-002 | change_rate < overheat_change_pct이면 과열 게이트 통과 | change_rate=+2.0 fixture → 과열 게이트 통과 (다른 게이트 통과 시 포함) |
| AC-SURGE-030-003 | 가격 조회 None + exclude_on_price_unavailable=true → 보수적 제외 | `_price_change_provider`가 None 반환 fixture → results 미포함 |
| AC-SURGE-030-004 | 가격 조회 None + exclude_on_price_unavailable=false → 과열/분산 게이트 미적용 | None 반환 + 설정 false → 과열·분산 게이트로 제외되지 않음 |
| AC-SURGE-030-005 | freshness ratio(volumes[-1]/volumes[-2]) < min_freshness_ratio(1.5)면 제외 | volumes 끝 두 값 비율 0.6 fixture → results 미포함 |
| AC-SURGE-030-006 | freshness ratio >= min_freshness_ratio면 신선도 게이트 통과 | 비율 2.0 fixture → 신선도 게이트 통과 |
| AC-SURGE-030-007 | volumes 2개 미만이면 신선도 검증 불가 → 보수적 제외 | volumes 길이 1 fixture → results 미포함 |
| AC-SURGE-030-008 | previous_day_vol=0이고 current_vol>0이면 신선도 통과 | volumes[-2]=0, volumes[-1]=100000 fixture → 신선도 게이트 통과 |
| AC-SURGE-030-009 | change_rate < distribution_change_pct(0.0)이면 분산으로 매수 신호 미생성 | change_rate=-2.0 fixture → results 미포함 |
| AC-SURGE-030-010 | change_rate == 0.0은 분산 아님(flat) → 분산 게이트 통과 | change_rate=0.0 fixture → 분산 게이트로 제외되지 않음 |
| AC-SURGE-030-011 | combo_score>0이고 theme/immediate/pattern 모두 0인 후보는 buy-pool 제외 | gather_surge_candidates에서 combo 단독 후보 → 최종 후보 미포함 |
| AC-SURGE-030-012 | combo_score>0 + theme_cluster_score>0 동반이면 combo 단독 게이트 미적용 | combo=0.4, theme=0.5 fixture → 후보 포함 |
| AC-SURGE-030-013 | combo_score>0 + immediate_disclosure_score>0 동반이면 게이트 미적용 | combo=0.4, immediate=0.6 fixture → 후보 포함 |
| AC-SURGE-030-014 | require_companion_detector=false면 combo 단독 차단 비활성 | 설정 false + combo 단독 fixture → 후보 포함 |
| AC-SURGE-030-015 | combo_chase_guard.enabled=false면 4개 게이트 전부 비활성, 기존 combo 동작 복원 | enabled=false + 과열/분산/단독 fixture → 기존 동작대로 포함 |
| AC-SURGE-030-016 | combo_chase_guard 섹션이 YAML에 없어도 문서화 기본값으로 로드 | 섹션 제거 config 로드 → 기본값 적용, get_surge_config() 정상 |
| AC-SURGE-030-017 | 앙상블 가중치 검증 및 컨센서스 배율 불변 | get_surge_config() 로드 시 validate_ensemble_weights 통과, weights/multiplier 값 변경 없음 |
| AC-SURGE-030-018 | 체결 시점 상수(INTRADAY_*, ENTRY_GAPUP_LIMIT) 불변 | surge_trading_service 상수값 grep 검증: -3.0/15.0/0.05 유지 |
| AC-SURGE-030-019 | 다른 탐지기(theme/disclosure/immediate) 동작 불변 | 기존 SPEC-AI-012/018 탐지기 테스트 전체 통과 |
| AC-SURGE-030-020 | 기존 회귀 테스트 전체 통과 | `cd backend && uv run pytest tests/ -m "not slow"` 100% 통과 |

## Given-When-Then Scenarios

### 시나리오 1: 추격매수 차단 (과열 + 분산)

```
Given combo 후보 종목 A가 거래량 z-score=3.0, 긍정 뉴스 조건을 통과했고
  And A의 당일 change_rate가 +9.0% (이미 추격성 급등 상태)
When detect_volume_surge_news_combo가 A를 평가한다
Then A는 REQ-AI030-001 과열 필터로 탐지기 출력에서 제외된다
  And surge_metadata에 A에 대한 combo 신호가 기록되지 않는다
```

### 시나리오 2: stale 급증 거부 (신선도)

```
Given combo 후보 종목 B의 z-score가 baseline 잔류로 높게 계산되었고
  And volumes[-1]/volumes[-2] = 0.6 (오늘 거래량이 어제보다 적음 = stale)
When detect_volume_surge_news_combo가 B를 평가한다
Then B는 REQ-AI030-002 신선도 게이트로 제외된다
  And 한 박자 늦은 진입이 방지된다
```

### 시나리오 3: combo 보조 신호로 정상 동작 (동반 탐지기 존재)

```
Given 종목 C가 combo_score=0.4 (신선·비과열·비분산 모두 통과)이고
  And theme_cluster_score=0.5로 theme_cluster 탐지기도 동반 발동했다
When gather_surge_candidates가 후보를 병합·필터링한다
Then C는 REQ-AI030-004 단독 차단 게이트에 걸리지 않고 buy-pool에 포함된다
  And combo가 독립 신호(theme)의 확인용 보조 역할을 수행한다
```

### 시나리오 4: combo 단독 신호 차단

```
Given 종목 D가 combo_score=0.5이지만 theme/immediate/pattern 점수가 모두 0이다
  And require_companion_detector=true (기본값)
When gather_surge_candidates가 후보를 병합·필터링한다
Then D는 REQ-AI030-004로 buy-pool에서 제외된다
  And combo 단독 거짓 양성(2026-06-02 6건 전부 실패 패턴)이 차단된다
```

### 시나리오 5: 비활성화 폴백 (하위 호환)

```
Given combo_chase_guard.enabled = false 설정
  And 과열·stale·분산·단독 후보들이 혼재
When 신호 생성 파이프라인이 실행된다
Then 본 SPEC의 4개 게이트가 모두 비활성화되고 SPEC-AI-012 기존 combo 동작이 복원된다
  And 기존 회귀 테스트가 영향 없이 통과한다
```

## Edge Cases

- 가격 조회 `None`: `exclude_on_price_unavailable` 설정에 따라 보수적 제외 또는
  게이트 스킵 (AC-003/004).
- `volumes` 길이 < 2: 신선도 검증 불가 → 보수적 제외 (AC-007).
- `previous_day_vol == 0`: zero-baseline 급증은 신선으로 간주 (AC-008).
- `change_rate == 0.0`: flat은 분산 아님 (AC-010).
- combo + 복수 동반 탐지기: 단독 게이트 미적용 (AC-012/013).

## Definition of Done

- [ ] REQ-AI030-001~005 전부 구현
- [ ] AC-SURGE-030-001 ~ AC-SURGE-030-020 전부 통과
- [ ] 신규 테스트 `backend/tests/test_surge_ai030.py` 작성 및 통과
- [ ] `combo_chase_guard` 섹션이 `surge_detection.yaml`에 추가되고 기본값으로 로드
- [ ] `enabled=false` 폴백으로 기존 combo 동작 보존 확인
- [ ] 다른 탐지기·앙상블 가중치·체결 시점 상수 불변 확인
- [ ] `cd backend && uv run pytest tests/ -m "not slow"` 100% 통과
- [ ] `cd backend && uv run ruff check .` 통과
- [ ] 신규/수정 함수에 @MX 태그 적용 (combo 게이트 진입점 @MX:NOTE, SPEC 참조)
```