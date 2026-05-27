# SPEC-AI-018 인수 기준

EARS 및 Given-When-Then 형식의 인수 시나리오. 모든 기준은 관측 가능
(테스트 출력/점수 값)해야 한다.

---

## EARS 인수 기준

- **AC-01**: WHEN 후보의 `price_5d_trend` 가 20%를 초과하면 THE SYSTEM SHALL
  앙상블 점수에 0.60 배율을 적용한다. (REQ-AI018-005)
- **AC-02**: WHEN 후보의 `price_5d_trend` 가 12% 초과 20% 이하이면 THE SYSTEM
  SHALL 앙상블 점수에 0.80 배율을 적용한다. (REQ-AI018-005)
- **AC-03**: WHEN `price_5d_trend` 가 None 또는 누락이면 THE SYSTEM SHALL 페널티를
  적용하지 않고 후보를 그대로 유지한다. (REQ-AI018-005)
- **AC-04**: WHEN `immediate_disclosure_score` 가 0.85 미만이면 THE SYSTEM SHALL
  즉각 공시 우회 경로로 앙상블 임계값을 우회하지 않는다. (REQ-AI018-001)
- **AC-05**: WHEN theme_cluster 또는 combo_score 가 0.85 미만이면 THE SYSTEM
  SHALL 강한 단일 신호 우회 경로를 활성화하지 않는다. (REQ-AI018-002)
- **AC-06**: WHEN per > 500 또는 pbr > 30 이고 해당 데이터가 존재하면 THE SYSTEM
  SHALL 해당 후보를 자격 목록에서 제외한다. (REQ-AI018-007)
- **AC-07**: WHEN per 또는 pbr 데이터가 None 또는 0 이면 THE SYSTEM SHALL 해당
  후보를 부적격 처리하지 않는다. (REQ-AI018-008)
- **AC-08**: WHEN theme_cluster 와 combo_score 가 모두 활성이지만 disclosure 와
  legacy 가 비활성이면 THE SYSTEM SHALL 컨센서스 1.00 배율을 적용한다. (REQ-AI018-009)
- **AC-09**: WHEN news 그룹, disclosure 그룹, technical 그룹이 모두 활성이면
  THE SYSTEM SHALL 컨센서스 1.55 배율을 적용한다. (REQ-AI018-009)
- **AC-10**: THE SYSTEM SHALL 앙상블 가중치 4개 합계를 항상 1.00 으로 유지한다
  (theme_cluster 0.28 + volume_news_combo 0.35 + disclosure_pattern 0.20 +
  legacy_detectors 0.17). (REQ-AI018-004)
- **AC-11**: THE SYSTEM SHALL `min_news_sentiment` 기본값을 0.5 로 적용한다. (REQ-AI018-003)

---

## Given-When-Then 시나리오

### 시나리오 1 — 최근 급등 종목 강한 페널티 (AC-01)

- Given: 종목 A의 앙상블 점수가 0.60, `price_5d_trend` 가 25.0%
- When: `gather_surge_candidates()` 가 종목 A를 자격 판정
- Then: 적용 점수는 0.60 * 0.6 = 0.36 으로 페널티 반영
- And: 세 경로(앙상블/즉각 공시 우회/강한 단일 신호 우회) 어디서든 동일 배율 적용

### 시나리오 2 — 중간 급등 종목 약한 페널티 (AC-02)

- Given: 종목 B의 앙상블 점수 0.50, `price_5d_trend` 15.0%
- When: 자격 판정
- Then: 적용 점수 0.50 * 0.8 = 0.40

### 시나리오 3 — 5일 추세 데이터 없음 (AC-03)

- Given: 종목 C의 앙상블 점수 0.50, `price_5d_trend` 가 None
- When: 자격 판정
- Then: 점수 0.50 유지(페널티 없음), 후보 자격 박탈 없음

### 시나리오 4 — 즉각 공시 우회 차단 (AC-04)

- Given: 종목 D의 `immediate_disclosure_score` 0.82, 다른 탐지기 모두 비활성,
  앙상블 점수가 유효 임계값 미만
- When: 즉각 공시 우회 경로 판정 (`immediate_disclosure_bypass_threshold = 0.85`)
- Then: 0.82 < 0.85 이므로 우회되지 않음, 종목 D는 자격 목록에서 제외

### 시나리오 5 — 즉각 공시 우회 허용 (AC-04 경계)

- Given: 종목 E의 `immediate_disclosure_score` 0.90 (자사주 소각 등)
- When: 즉각 공시 우회 경로 판정
- Then: 0.90 >= 0.85 이므로 우회 허용, 종목 E는 자격 목록 포함

### 시나리오 6 — 고 PER 부적격 (AC-06)

- Given: 종목 F의 per 620, pbr 5.0 (데이터 존재)
- When: `_gather_leading_candidates()` 에서 재무 부착 후 부적격 판정
- Then: per 620 > 500 이므로 종목 F 제외

### 시나리오 7 — 고 PBR 부적격 (AC-06)

- Given: 종목 G의 per 30, pbr 45.0 (데이터 존재)
- When: 부적격 판정
- Then: pbr 45.0 > 30 이므로 종목 G 제외

### 시나리오 8 — 밸류에이션 데이터 누락 보존 (AC-07)

- Given: 종목 H의 per None, pbr 0
- When: 부적격 판정
- Then: 데이터 미수집이므로 제외하지 않음(missing data != overvalued)

### 시나리오 9 — 상관 탐지기 단일 그룹 (AC-08)

- Given: 종목 I의 theme_cluster_score 0.6, combo_score 0.5 (둘 다 활성),
  disclosure/legacy 모두 0
- When: `compute_ensemble_score()` 컨센서스 그룹 카운트
- Then: news 그룹 1개만 활성 → 컨센서스 배율 1.00 (1.30 아님)

### 시나리오 10 — 3개 독립 그룹 (AC-09)

- Given: 종목 J의 theme_cluster 0.5(news), best_disclosure 0.6(disclosure),
  legacy 0.4(technical) 활성
- When: 컨센서스 그룹 카운트
- Then: 3개 그룹 활성 → 컨센서스 배율 1.55

---

## 엣지 케이스

- `price_5d_trend` 가 정확히 20.0% (경계): > 20.0 조건이 거짓이므로 0.8x 적용
- `price_5d_trend` 가 정확히 12.0% (경계): > 12.0 조건이 거짓이므로 페널티 없음
- `price_5d_trend` 가 음수(하락): 페널티 없음(상승 추세에만 적용)
- per 가 정확히 500: > 500 거짓이므로 부적격 아님 (pbr 정확히 30도 동일)
- 페널티 적용 후 점수가 유효 임계값 미만으로 떨어진 경우: 자격 박탈
  (페널티는 자격 판정 전 적용되므로 자연 반영)
- 모든 탐지기 비활성(앙상블 점수 0): 컨센서스 그룹 0개 → 1.00x

---

## 품질 게이트 / Definition of Done

- [ ] REQ-AI018-001 ~ REQ-AI018-009 모두 구현 및 테스트 커버
- [ ] AC-01 ~ AC-11 단위 테스트 통과
- [ ] 가중치 합계 1.00 불변식 테스트 통과 (AC-10)
- [ ] 세 자격 경로 모두에서 페널티 일관 적용 테스트 통과 (AC-01/02/03)
- [ ] 컨센서스 그룹화 회귀 테스트 통과 (AC-08/09)
- [ ] `surge_detector.py:783` 스테일 컨센서스 주석 갱신
- [ ] `uv run pytest tests/ --tb=short -q -m "not slow"` 통과
- [ ] `uv run ruff check .` 및 `uv run mypy app/` 무오류
- [ ] REQ-AI018-010(공매도 연동) SPEC-AI-019로 분리 기록
- [ ] 신규 설정 키가 `surge_settings.py` Pydantic 모델에 반영
