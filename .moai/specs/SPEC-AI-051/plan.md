# SPEC-AI-051 구현 계획 (Implementation Plan)

id: SPEC-AI-051 | version: 1.0.0 | status: draft | priority: high

본 계획은 3개 독립 기능(볼린저 스퀴즈 / 공시 키워드 Tier / 14:30 런너 파이프라인)을 8개 TASK로 분해한다. 시간 추정은 사용하지 않으며 우선순위·의존 순서로 진행한다.

---

## 기술 접근 (Technical Approach)

### Feature 1 — 볼린저 밴드 스퀴즈

- `_bollinger_bands(prices, period=20)`는 입력 앞부분 20개 가격만 사용하므로, 60일 윈도우에서 각 영업일 BandWidth를 얻으려면 **일봉 리스트를 영업일별로 슬라이싱**하여 반복 호출한다(최신순 정렬 유지).
- BandWidth = (upper − lower) / middle. 당일 BandWidth와 직전 60거래일 BandWidth 집합의 최저값을 비교한다.
- `squeeze_score`는 "당일 밴드폭이 60일 최저에 얼마나 근접/하회했는가"를 0.0~1.0으로 정규화. 정확한 산식은 설정 키로 노출(하드코딩 금지).
- `fetch_stock_price_history_sync`는 기본 `pages=3`(≈30일)이므로 **`pages=6` 이상**으로 호출. TTL 캐시·5초 타임아웃에 의존.

### Feature 2 — 공시 키워드 Tier

- `score_disclosure_impact()`의 **base 점수 산정 직후, 100 캡 직전**에 Tier 배수를 적용한다.
- 루틴 거버넌스 조기 반환(line 154, `return 5.0`)은 배수 적용 전에 발생하므로 자연히 면제된다 — 이 순서를 보존한다.
- 매칭은 `report_name` + `ai_summary` 텍스트 대상. Tier 1 → Tier 2 → Tier 3 순으로 검사하여 **최초 매칭 Tier의 배수만** 사용(최고 Tier 우선, 누적 금지).

### Feature 3 — 14:30 런너 파이프라인

- `detect_near_limit_up_carries()`(`surge_detector.py:1811-1918`)의 FundSignal 생성·중복방지·예외격리 패턴을 그대로 차용한다.
- 리더 조회: 당일 생성 FundSignal에서 `signal_type IN (...)` + `confidence >= 0.75`.
- 섹터 피어: `Stock.sector_id` 동일 + `market_cap` 내림차순 → 2/3등. `get_open_position()`로 미체결 포지션 제외.
- **09:05 소비자 통합이 핵심 리스크**: `early_entry_check()`가 `preday_disclosure`만 필터하므로(`preday_signal_service.py:366`), `gap_up_runners`를 포함하도록 필터를 확장하거나 전용 소비자를 추가해야 한다. 자동 픽업은 동작하지 않는다.

---

## TASK 분해

| TASK | 설명 | 대상 파일 | REQ |
|---|---|---|---|
| **TASK-001** | `SurgeCandidate` dataclass에 `squeeze_score: float = 0.0` 필드 추가 | `surge_detector.py:58-81` | REQ-AI051-001 |
| **TASK-002** | `technical_indicators.py`에 `calculate_bollinger_bandwidth_squeeze()` 헬퍼 추가 — 60일 윈도우 BandWidth 계산 + 당일 vs 60일 최저 비교 + squeeze_score 정규화. 기존 `_bollinger_bands()` 재사용 | `technical_indicators.py` | REQ-AI051-002 |
| **TASK-003** | `surge_detector.py`에 `detect_bollinger_squeeze_signals(db, config)` 추가 — 활성 종목 순회 → `fetch_stock_price_history_sync(pages≥6)` → TASK-002 헬퍼 호출 → 스퀴즈 후보를 `SurgeCandidate(squeeze_score=...)`로 반환. 데이터 부족 종목 스킵 | `surge_detector.py` | REQ-AI051-002 |
| **TASK-004** | `disclosure_impact_scorer.py`에 Tier 1/2/3 키워드 사전 상수 추가 및 `score_disclosure_impact()` 수정 — base 점수 산정 후 최고 Tier 배수 적용, 100 캡, 루틴 거버넌스 면제 | `disclosure_impact_scorer.py:138-182` | REQ-AI051-004~006 |
| **TASK-005** | `surge_detector.py`에 `detect_gap_up_runners(db, config)` 추가 — 리더 조회 → 섹터 2/3등 선정 → `get_open_position` 중복 제외 → 현재가 주입 → `gap_up_runners` FundSignal 생성. `near_limit_up_carries` 패턴 차용 | `surge_detector.py` | REQ-AI051-007~009 |
| **TASK-006** | `scheduler.py`에 신규 잡 2개 추가 — 15:10 KST `surge_squeeze_scan`(Feature 1), 14:30 KST `surge_gap_up_runners`(Feature 3). 고유 id, mon-fri, Asia/Seoul. **+ `preday_signal_service.early_entry_check()` signal_type 필터를 `gap_up_runners` 포함하도록 확장** | `scheduler.py`, `preday_signal_service.py` | REQ-AI051-003, REQ-AI051-010 |
| **TASK-007** | 앙상블 스코어링에 `squeeze_score` 통합 — **가산(additive)만**. 기존 `EnsembleWeightsConfig` 4개 가중치(`theme_cluster`/`volume_news_combo`/`disclosure_pattern`/`legacy_detectors`) 변경 금지 | `surge_detector.py` / `surge_config/` | REQ-AI051-001 |
| **TASK-008** | 단위 테스트 작성 — 스퀴즈 탐지/비탐지, Tier 1/2/3 배수, 런너 선정, 중복 런너 제외. acceptance.md의 6개 시나리오 커버 | `backend/tests/` | 전체 |

---

## 의존 그래프 (Dependencies)

```
TASK-001 ──► TASK-003 ──► TASK-007
              ▲
TASK-002 ─────┘

TASK-004  (독립 — Feature 2, 다른 TASK와 무관)

TASK-005 ──► TASK-006

TASK-008  (최종 — 모든 구현 TASK 완료 후)
```

- **Feature 1 체인**: TASK-001 → TASK-003 → TASK-007, 그리고 TASK-002 → TASK-003
- **Feature 2**: TASK-004 (완전 독립, 병렬 진행 가능)
- **Feature 3 체인**: TASK-005 → TASK-006 (스케줄러 잡 + 소비자 필터 확장)
- **TASK-008**: 마지막. 모든 구현 완료 후 테스트.

권장 진행: (TASK-001, TASK-002, TASK-004) 병렬 시작 → TASK-003 → TASK-005 → (TASK-006, TASK-007) → TASK-008.

---

## 리스크 분석 (Risk Analysis)

| 리스크 | 영향 | 완화책 |
|---|---|---|
| **Naver 일봉 스크레이프 부하** (Priority High) | 60+ 종목 × `pages≥6` = 종목당 6 HTTP 요청 → 수백 요청 발생. rate limiting / 차단 위험 | `max_stocks_to_check` 상한, TTL 캐시 의존, 5초 타임아웃 유지, 실패 종목 스킵(전체 실패 금지). 15:10 단일 실행으로 빈도 최소화 |
| **09:05 소비자 미연동** (Priority High) | `early_entry_check`가 `gap_up_runners`를 필터링하지 않으면 14:30 시그널이 익일 무시됨 | TASK-006에서 signal_type 필터 확장 명시. acceptance.md 시나리오로 검증 |
| **밴드폭 정렬 오류** (Priority Medium) | `_bollinger_bands`가 입력 앞 20개만 사용 → 정렬 가정 위반 시 잘못된 BandWidth | 일봉 최신순 정렬 명시 관리, 윈도우 슬라이싱 단위 테스트 |
| **Tier 배수 누적 오적용** (Priority Medium) | 여러 Tier 키워드 동시 매칭 시 배수 중첩 → 점수 폭증 | 최고 Tier 1개만 적용 + 100 캡. 다중 키워드 테스트 |
| **루틴 거버넌스 배수 오발** (Priority Low) | 루틴 공시(5.0 캡)에 배수 적용 시 섹터 파급 오발 | 조기 반환 순서 보존, REQ-006 + 전용 테스트 |
| **예측 기록 모드 정합성** (Priority Low) | SPEC-AI-043으로 실거래 비활성 — 런너 시그널이 평가만 됨 | 의도된 동작. 실거래가 아닌 익일 예측 기록으로 평가 |

---

## 회귀 안전 (Regression Safety)

- 기존 탐지기·가중치 무변경(스퀴즈 가산만, 키워드 배수는 공시 점수에만).
- DB 마이그레이션 없음 → 스키마 회귀 위험 없음.
- 14:30/15:10 신규 잡은 고유 id 사용 → 기존 잡 충돌 없음.
- 검증: `cd backend && uv run pytest tests/ -m "not slow"`
