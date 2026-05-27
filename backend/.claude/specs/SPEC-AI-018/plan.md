# SPEC-AI-018 구현 계획

급등예측 신호 품질 개선의 구현 계획. 본 문서는 **무엇을 어떤 순서로** 작업할지를
정의한다. 코드 자체는 Run 단계에서 작성한다.

---

## 기술 접근

신호 생성 파이프라인의 두 진입점을 다룬다.

- `surge_detector.py` — 앙상블 스코어링, 우회 경로, 컨센서스 배율
- `fund_manager.py` — 레거시 탐지기, 재무/밸류에이션 데이터 수집
- 설정: `surge_detection.yaml` (값), `surge_settings.py` (Pydantic 모델)

변경은 위험도 오름차순으로 5개 마일스톤(Phase 1→4, Phase 5는 분리)으로 진행한다.
설정 변경(저위험)을 먼저 적용하여 빠른 검증 루프를 확보하고, 구조적 변경
(컨센서스 그룹화)을 마지막에 배치한다.

---

## 마일스톤 (우선순위 기반, 시간 추정 없음)

### Milestone 1 — 설정 조정 (Priority: High)

- REQ-AI018-002: `strong_single_bypass_threshold` 0.72 → 0.85 (YAML)
- REQ-AI018-003: `min_news_sentiment` 0.3 → 0.5 (YAML)
- REQ-AI018-004: 가중치 조정 theme_cluster 0.35→0.28, legacy_detectors 0.10→0.17 (YAML)
- REQ-AI018-001: `immediate_disclosure_bypass_threshold` 신규 키 추가(기본 0.85),
  `surge_settings.py` Pydantic 모델에 필드 추가, `surge_detector.py:939` 하드코딩
  제거 후 `config.ensemble.immediate_disclosure_bypass_threshold` 참조
- 대상 파일: `surge_detection.yaml`, `surge_settings.py`, `surge_detector.py`
- 완료 기준: 가중치 합계 1.00 검증 테스트 통과, 즉각 공시 우회가 설정값 참조

### Milestone 2 — 최근 급등 페널티 (Priority: High)

- REQ-AI018-005: `gather_surge_candidates()` 의 3개 자격 경로(앙상블/즉각 공시 우회/
  강한 단일 신호 우회)에서 `price_5d_trend` 기반 페널티 적용
  - 레거시 후보 dict에서 종목 코드 기준 `price_5d_trend` 매핑 헬퍼 구성
  - > 20% → 0.6x, > 12% → 0.8x, None/누락 → 페널티 없음
- 대상 파일: `surge_detector.py`
- 완료 기준: 세 경로 모두에서 페널티가 일관 적용됨을 단위 테스트로 검증

### Milestone 3 — 밸류에이션 부적격 필터 (Priority: Medium)

- REQ-AI018-006: `valuation_disqualifiers` 키 + Pydantic 모델 필드(max_per=500, max_pbr=30)
- REQ-AI018-007: `_gather_leading_candidates()` 에서 재무 부착 이후 per>500 OR pbr>30 제외
- REQ-AI018-008: per/pbr None 또는 0 이면 제외하지 않음
- 대상 파일: `surge_detection.yaml`, `surge_settings.py`, `fund_manager.py`
- 완료 기준: 고평가 종목 제외 + 데이터 누락 종목 보존 테스트 통과

### Milestone 4 — 컨센서스 독립성 교정 (Priority: Medium)

- REQ-AI018-009: `compute_ensemble_score()` 활성 카운트를 그룹 단위로 변경
  - news 그룹(theme_cluster + combo), disclosure 그룹(best_disclosure), technical 그룹(legacy)
  - 그룹 내 임의 점수 > 0 이면 활성, 최대 3그룹 → 1.55x
  - `surge_detector.py:783` 스테일 `@MX:NOTE` 주석 갱신
- 대상 파일: `surge_detector.py`
- 완료 기준: 뉴스 단일 그룹만 활성 시 1.00x 적용 회귀 테스트 통과

### Milestone 5 — 후속 SPEC 분리 (Priority: Low)

- REQ-AI018-010: SPEC-AI-019(공매도/대차잔고 연동) 추적 항목 기록. 본 SPEC 범위 외.

---

## 의존성 / 순서

- Milestone 1 (설정 + Pydantic 모델)은 다른 모든 마일스톤의 선행. 신규 설정 키가
  Milestone 2/3에서 참조됨.
- Milestone 2, 3, 4는 서로 독립적이나, 파일 충돌 방지를 위해 순차 진행 권장
  (Milestone 2/4는 `surge_detector.py`, Milestone 3은 `fund_manager.py`).
- Milestone 4(컨센서스 그룹화)는 점수 분포를 바꾸므로 마지막에 배치하여
  앞선 변경의 회귀 영향과 분리.

---

## 리스크

- **신호 수 급감**: REQ-002(우회 0.72→0.85), REQ-005(페널티), REQ-009(그룹 컨센서스)가
  중첩되면 일일 신호 수가 과도하게 줄 수 있다. 각 마일스톤 후 신호 수 변화를 관측.
- **가중치 합 오류**: REQ-004 적용 시 합계가 1.00이 아니면 점수 스케일이 왜곡된다.
  명시적 합계 검증 테스트 필수.
- **데이터 매핑 누락**: `price_5d_trend`가 `SurgeCandidate`에 없고 레거시 dict에만
  존재하므로, 매핑 누락 시 페널티가 전혀 적용되지 않는 silent failure 가능.
- **밸류에이션 데이터 신뢰도**: per/pbr 수집 소스(KIS, 스크래퍼)의 결측/0 처리가
  일관되지 않으면 정상 종목이 잘못 제외될 수 있다. REQ-008의 보호 로직이 핵심.

---

## 검증

- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
- 전체: `cd backend && uv run pytest tests/ --tb=short -q`
- 린트: `cd backend && uv run ruff check . && uv run mypy app/`
