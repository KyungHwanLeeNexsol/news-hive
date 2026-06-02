# SPEC-AI-030 Implementation Plan

거래량콤보 탐지기 추격매수 방지 — 신호 생성 시점 게이트 추가.

## Technical Approach

본 SPEC은 신규 탐지기·모델·마이그레이션·엔드포인트를 만들지 않는다. 기존
`detect_volume_surge_news_combo`와 `gather_surge_candidates`에 게이트를 삽입하고,
설정 모델 1개를 추가하는 **순수 로직 보강**이다. 모든 외부 데이터는 탐지기가 이미
조회 중인 값(`_fetch_price_change_sync` 결과, `_get_volume_history` 일봉)을 재사용한다.

### REQ별 기술 접근

- **REQ-AI030-001 (당일 과열 필터)**: combo 후보가 z-score·뉴스 조건을 통과한 직후,
  이미 호출 중인 `_fetch_price_change_sync` 결과의 `change_rate`를 읽어
  `>= overheat_change_pct`(기본 +5.0)면 `results.append` 전에 `continue`로 제외.
  가격 `None`이면 `exclude_on_price_unavailable`에 따라 보수적 제외.
- **REQ-AI030-002 (신선도 검증)**: `_get_volume_history`가 반환한 `volumes` 리스트에서
  `volumes[-1] / volumes[-2]` 비율을 계산하여 `< min_freshness_ratio`(기본 1.5)면 제외.
  `len(volumes) < 2`이면 보수적 제외, `volumes[-2] == 0`이면 `volumes[-1] > 0`일 때만
  통과. 기존 z-score 계산 블록(라인 513~528) 직후에 삽입.
- **REQ-AI030-003 (분산 거부)**: REQ-001과 동일한 `change_rate`를 재사용,
  `< distribution_change_pct`(기본 0.0)면 제외. `change_rate == 0.0`은 통과(flat).
  REQ-001과 같은 가격 조회 결과를 공유하므로 추가 조회 없음.
- **REQ-AI030-004 (combo 단독 차단)**: `gather_surge_candidates`의 병합 완료 후, 최종
  후보 필터링 단계에서 `require_companion_detector`가 true이고 후보가
  `combo_score > 0` && `theme_cluster_score == 0` && `immediate_disclosure_score == 0`
  && `pattern_score == 0`이면 buy-pool에서 제외. 앙상블 점수 계산 자체는 불변.
- **REQ-AI030-005 (설정)**: `surge_settings.py`에 `ComboChaseGuardConfig` 추가,
  `SurgeDetectionConfig.combo_chase_guard = Field(default_factory=ComboChaseGuardConfig)`.
  `surge_detection.yaml`에 동명 섹션 추가. 섹션 부재 시 기본값(default_factory) 적용.

## Milestones (priority-based)

- **M1 (High)**: `ComboChaseGuardConfig` 설정 모델 + YAML 섹션 추가, 기본값 로드 검증
  (REQ-AI030-005). 이후 게이트가 참조할 설정 기반 마련.
- **M2 (High)**: `detect_volume_surge_news_combo`에 과열 필터·분산 거부 추가
  (REQ-AI030-001, REQ-AI030-003) — 가장 직접적인 손실 원인 차단.
- **M3 (High)**: 신선도 검증 추가 (REQ-AI030-002) — stale 급증 후보 제거.
- **M4 (Medium)**: `gather_surge_candidates`에 combo-단독 제외 게이트 추가
  (REQ-AI030-004) — 거짓 양성 추가 차단.
- **M5 (High)**: 회귀 테스트 전체 통과 확인, enabled=false 폴백·설정 부재 기본값 검증.

순서: M1 완료 → M2/M3(combo 탐지기 동일 함수, 순차) → M4 → M5.

## Risks

- **R1 — 가격 조회 실패 빈도**: `_fetch_price_change_sync`가 `None`을 자주 반환하면
  보수적 제외(REQ-001/003)로 combo 후보가 과도하게 줄 수 있다. 완화:
  `exclude_on_price_unavailable`를 설정으로 노출하여 운영 중 조정 가능.
- **R2 — 신선도 비율의 일봉 해상도 한계**: `volumes[-1]`이 장중 미마감 거래량이면
  비율이 왜곡될 수 있다. 완화: Run 단계에서 `_get_volume_history`가 반환하는
  마지막 값의 의미(전일 마감 vs 당일 진행)를 확인하고, 당일 진행값이면 신선도 기준을
  보정하거나 전일/전전일 비율로 대체 검토.
- **R3 — combo 단독 차단의 부작용**: 드물게 combo 단독이 정상 신호일 가능성. 완화:
  `require_companion_detector`를 설정으로 노출, 2026-06-02 증거(combo 단독 6건 전부
  실패)가 기본값 true를 정당화.
- **R4 — 기존 테스트 회귀**: combo 탐지기 동작 변경이 SPEC-AI-012/018 테스트에 영향
  가능. 완화: enabled=false 폴백으로 기존 동작 보존, 기존 테스트는 게이트 비활성 또는
  통과형 fixture로 유지.

## Verification Commands

```bash
cd backend && uv run pytest tests/test_surge_ai030.py --tb=short -q
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
cd backend && uv run ruff check app/services/surge_detector.py app/surge_config/surge_settings.py
```
