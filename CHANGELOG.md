# Changelog

NewsHive의 주요 변경 사항을 기록합니다.

## [Unreleased]

### Added — SPEC-AI-038 BEAR threshold cap, volume threshold 완화, 장중 재탐지 + 성능 패치 (2026-06-04)

2026-06-04 운영 분석에서 ①BEAR regime 임계값(0.60)이 너무 높아 combo=0 신호가 전량 차단,
②volume_zscore 2.5로 combo 발화 불가, ③장 시작 전 1회 배치만으로 당일 급등 미포착,
④SPEC-AI-037 시총 500억 확장 후 detect_theme_news_cluster가 timeout 발생 문제를 해결했습니다.

#### SPEC-AI-038 임계값·탐지 개선
- **REQ-038-001 volume_zscore 완화** (`surge_detection.yaml`):
  - 기본값 2.5→2.0, BEAR 오버라이드 3.0→2.5 — combo 신호 감도 향상
- **REQ-038-002 BEAR threshold cap** (`surge_detection.yaml`):
  - `regime_multipliers.BEAR` 1.2→1.05, `final_clamp_max` 0.85→0.65
  - 저승률+BEAR 복합 시 threshold 0.60→0.525로 하락 (신호 통과 가능해짐)
- **REQ-038-003 10:00 KST 장중 재탐지** (`scheduler.py`):
  - `surge_signal_generate_intraday` 잡 추가 (BUY_CUTOFF 1시간 전)
  - 당일 거래량·공시 기반 시그널을 10:30 execute_buys가 수신 가능
- **테스트**: `test_surge_ai038.py` 9개 신규 (REQ-038-001~003 전부 커버)

#### 성능 패치 — detect_theme_news_cluster timeout 수정 (SPEC-AI-037 성능 회귀)
SPEC-AI-037 시총 500억 확장으로 NULL 시총 1684건이 추가 포함 → 종목당 2회 HTTP 호출 = 550초+ timeout.

- **NULL 시총 제거** (`surge_detector.py`):
  - 무조건 포함 1684건 → 뉴스 창 내 언급된 종목만 포함 (수십 건으로 제한)
- **theme_cluster 가격 API 완전 제거** (`surge_detector.py`):
  - `_fetch_price_change_sync` 2회/종목 → 0회 (price_bonus=0.0 고정)
  - O(N×API) → 순수 메모리 연산, 실행 시간 550초+ → **17초 이하**
- **volume_combo 50개 상한** (`surge_detector.py`):
  - positive_news_stocks 무제한 → 감성점수 상위 50개만 처리
- **거래량 히스토리 pages=3→1** (`surge_detector.py`):
  - 종목당 3 HTTP 요청 → 1 HTTP 요청 (20일 baseline에 1페이지 충분)
  - volume_combo 실행 시간 52초 → ~17초

### Added — SPEC-AI-037 급등 탐지 테마 커버리지 확장 및 비테마 팩터 강화 (2026-06-04)

2026-06-04 시스템 분석에서 13개 하드코딩 테마 외 급등주(게임/엔터/조선/해운 등)가 포착되지 않고,
`combo_zero_theme_floor: 0.7` 게이트가 비테마 종목을 매수 단계에서 전면 차단하는 문제를 해결했습니다.

- **REQ-037-001 테마 13→20개 확장** (`backend/app/surge_config/surge_detection.yaml`):
  - 신규 테마: 게임/엔터/조선/해운물류/건설부동산/음식료/화학소재
  - KRX `_SNAPSHOT` 섹터명 정본으로 매핑 (0건 매칭 오류 없음)

- **REQ-037-002 combo_zero_theme_floor 0.7→0.55** (`surge_detection.yaml`, `surge_threshold_service.py`):
  - 비테마 비과열 종목의 매수 게이트 진입 허용
  - 과열(volume_z_score >= 3.0) 시 기존 0.7 유지로 추격매수 억제

- **REQ-037-003 소형주 시총 1000억→500억** (`surge_detection.yaml`):
  - `min_market_cap_krw: 50_000_000_000` 으로 하향

- **REQ-037-005 비테마 fast path** (`surge_threshold_service.py`):
  - `disclosure_pattern_score >= 0.70` 또는 `volume_news_combo_score >= 0.80 & 비과열` 시
    theme=0 종목도 매수 게이트 직통 통과

- **테스트**: `test_surge_ai037.py` 21개 신규 테스트, AC-037-001~006 전부 커버.
  기존 SPEC-AI-029/030 테스트 회귀 0건. 앙상블 가중치 합 1.00 유지.

### Added — SPEC-AI-036 composite_score 활성화 및 confidence 캘리브레이션 (2026-06-04)

2026-06-04 라이브 DB 분석에서 발견된 신호 품질 3대 결함(composite_score NULL 428/428, confidence 예측력 0.0001, 신호 과다·저품질)을 해결하는 isotonic regression 기반 품질 개선 시스템을 구현했습니다.

#### M1 — composite_score 활성화
- **새 함수** (`backend/app/services/factor_scoring.py`):
  - `build_surge_factor_scores(candidate, config) -> tuple[str, float]`: SurgeCandidate → (composite_score, factor_scores_json) 변환
- **개선** (`backend/app/services/fund_manager.py`):
  - `_gather_surge_candidates()`: aggregation point에서 모든 surge_candidate에 composite_score + factor_scores 주입
- **결과**: 신규 surge_candidate 100% composite_score 채움 (기존 0/428)

#### M2 — Isotonic Regression 캘리브레이터
- **신규 모듈** (`backend/app/services/surge_calibrator.py`): Pure Python PAV 알고리즘, pickle 영속성, identity fallback
- **지원 함수** (`backend/app/services/signal_verifier.py`): `get_surge_calibration_pairs(db, days=90)`

#### M3 — 품질 floor 게이트
- `_gather_surge_candidates()`: `calibrated_confidence >= 0.35 OR composite_score >= 0.60` floor 게이트

#### M4 — Signal Quality Monitoring API
- **신규**: `GET /api/fund/signal-quality` (composite_score 채움률, Brier score, ECE)

- **테스트**: `test_surge_calibrator.py` 40개 + `test_surge_ai036.py` 40개 신규.

### Planned — 급등 예측 정확도 개선 로드맵 SPEC 초안 (2026-06-02)

2026-06-02 운영 분석(volume_news_combo 전패, theme_cluster 단독 확률 0.27)을 바탕으로
급등 예측 정확도 개선을 위한 5개 SPEC 초안을 작성했습니다.

- **SPEC-AI-031**: 장 시작 직전 08:45 재확인 스캔 — 18시간 신호 갭 해소, watch_list → confirm_list 2단계 파이프라인
- **SPEC-AI-032**: 뉴스 속도(Velocity) 탐지기 신설 — 기사 수가 아닌 기사 가속도 측정, theme_cluster 한계 보완
- **SPEC-AI-033**: `immediate_disclosure` 앙상블 가중치 독립화 — 현재 0.20 공유 → 0.35 전용 가중치로 최고 예측자 반영
- **SPEC-AI-034**: 실적 기반 앙상블 가중치 보정 — `SurgeTrade` 실적 데이터로 탐지기별 win rate 계산, 가중치 조정 추천
- **SPEC-AI-035**: 장중 실시간 cascade 감지 — 대장주 급등 시 계열사 당일 진입 기회 포착 (현재는 15:20 후 익일 실행)

### Added — SPEC-AI-030 volume_news_combo 추격매수 방지 4개 게이트 (2026-06-02)

2026-06-02 운영 분석에서 `volume_news_combo` 신호 6건이 100% 실패(평균 -7.7%)한 반면, 유일한 성공 사례(쎄노텍 +10.6%)는 `immediate_disclosure + theme_cluster` 조합을 사용했습니다. 이를 근거로 combo-only 추격매수를 차단하는 4개 게이트를 surge_detector에 추가하여 신호 신뢰도를 강화했습니다.

- **REQ-AI030-001 과열 필터** (`backend/app/services/surge_detector.py`):
  - 변동률 >= 5.0% 종목 제외로 과도한 상승 모멘텀 차단
  
- **REQ-AI030-002 거래량 신선도 검사** (`backend/app/services/surge_detector.py`):
  - 최근 거래량 대비 이전 거래량 비율 < 1.5 시 제외 (거래량 스파이크의 지속성 부족)
  
- **REQ-AI030-003 분포 패턴 거부** (`backend/app/services/surge_detector.py`):
  - 변동률 < 0.0%(가격 하락) 종목 제외로 약세 신호 차단
  
- **REQ-AI030-004 콤보 전용 제외** (`backend/app/services/surge_detector.py`):
  - `combo_score > 0`이지만 동반 탐지기 없을 때 매수풀 제외 (독립적 신호 부재 시 매수 차단)

- **설정 모델** (`backend/app/surge_config/surge_settings.py`):
  - 신규 `ComboChaseGuardConfig` 모델 with master switch `enabled=True`
  - YAML 섹션 `combo_chase_guard` 추가 (`backend/app/surge_config/surge_detection.yaml`)
  - 마스터 스위치로 backward compatible 비활성화 가능
  
- **테스트** (`backend/tests/test_surge_ai030.py` 신규):
  - 27개 테스트, 모두 통과
  - 4개 게이트의 개별 및 조합 동작 검증
  - 기존 신호 타입과의 상호 작용 확인

### Added — SPEC-AI-024/025/026 급등 시그널 커버리지 추가 확장 (2026-05-29)

세 가지 새로운 급등 탐지기를 `_run_coverage_expansion()`에 추가했습니다:

- **SPEC-AI-024 임원 자사주 직접 매수 공시 강화** (`detect_insider_purchase_signals`):
  - DART 공시 중 임원이 자사주를 직접 매수하는 공시 탐지 (키워드: 임원+취득/매수)
  - confidence=0.45, surge_basis=["insider_purchase"]
  
- **SPEC-AI-025 테마 그룹 강세 carry-forward** (`detect_theme_group_carry_forward`):
  - LG/삼성/현대차/SK 그룹 앵커 종목이 +5% 이상 마감 시 그룹 내 다른 종목에 익일 시그널
  - confidence = anchor_change_rate/30*0.4, surge_basis=["theme_group_carry"]
  
- **SPEC-AI-026 포럼 언급 급증 탐지** (`detect_forum_mention_surge`):
  - 종목 토론방 언급량 24시간 내 7일 평균 대비 5배 이상 급증 시 시그널
  - confidence = min(ratio/20, 0.35), surge_basis=["forum_mention_surge"]

### Fixed — 손절 후 회복 종목 시그널 누락 방지 (SPEC-AI-021) (2026-05-29)

손절된 종목의 익일 신호 약화로 인한 매수 기회 손실을 해결했습니다. 직전 3영업일 이내에 손절 청산된 종목이 당일 재탐지될 때 신뢰도에 +0.10 부스트를 적용하고, 테마 클러스터 단일 신호 + 손절 회복 조합의 임계값을 0.30에서 0.25로 완화하는 방식으로 보정했습니다. 추가로 당일 손절(-5%)과 다일 보유 손절(-7%)을 분리하여 손절 조건을 더욱 세분화했습니다.

- **손절 후 회복 confidence_boost** (`backend/app/services/surge_trading_service.py`):
  - `_get_recent_stop_loss_codes(db, lookback_days=3)` 헬퍼 신규 — 직전 3영업일 이내 손절 청산 종목 조회 (O(1) lookup용 set 반환)
  - `get_today_signals()` 시그널 평가 시 hand절 이력 종목에 `+0.10` confidence 부스트 적용
  - 부스트된 confidence로 `min_probability` 임계값 재평가, 통과 종목을 매수 후보로 포함
  - 4-튜플 반환으로 recovery_context 정보 전달 (`is_post_stop_loss`, `boost_applied`, `min_probability_effective`)
  - `execute_buy_orders()` 4-튜플 unpacking 및 상세 정보 로그 추가 (`recovery_boost: True, boost_applied: 0.10`)
- **theme_cluster 단일 basis + 손절 회복 임계값 완화** (`backend/app/services/surge_trading_service.py`):
  - 시그널 basis가 정확히 `["theme_cluster"]` 단일값 AND 손절 회복 조건 동시 충족 시 `min_probability` 0.30 → 0.25로 완화
  - carry_over basis 포함 시 임계값 완화 미적용 (이미 carry-over 보너스 수령)
  - effective_confidence = original_confidence + 0.10 >= 0.25로 통과 조건 설정
- **손절 임계값 보유 기간 분기** (`backend/app/services/surge_trading_service.py`):
  - `check_exit_conditions()` 시그니처 확장: `same_day_stop_loss_pct=-0.05`, `multi_day_stop_loss_pct=-0.07` 신규 인자
  - 당일 진입 후 당일 손절 조건(holding_days==0) -5% 적용, 다일 보유 손절(holding_days>=1) -7% 적용으로 분리
  - 기존 단일 인자 호출(stop_loss_pct만 명시)은 하위 호환성 유지하여 기존 동작 보존
- **테스트 추가** (`backend/tests/test_surge_trading_recovery.py` 신규, `test_surge_trading.py` 확장):
  - AC-001~AC-010 인수 기준 검증 (손절 부스트, 임계값 완화, 보유 기간 분기)
  - 손절 이력 헬퍼 정확성, 4-튜플 unpacking, 하위 호환성 회귀 테스트 포함
  - 기대값: 전체 테스트 90%+ 통과
- **영향 범위**:
  - LG전자(066570, conf=0.2576, 당일 +29.93%) 및 삼성에스디에스(018260, conf=0.2464, 당일 +20.32%) — 2026-05-29 일일 최고 급등 2종목이 손절 후 회복 부스트로 매수 큐 진입
  - 당일 진입 수익 개선 및 손절 이후 재진입 기회 회복율 증대

### Added — 시그널 커버리지 확장 — 테마 전파 및 비활성 종목 거래량 이상 탐지 (SPEC-AI-022) (2026-05-29)

급등주 시그널 커버리지 2.6%에서 벗어나기 위해 두 가지 신규 신호 타입을 도입했습니다. 재벌 그룹 내 테마 cascade를 자동 감지하여 anchor 종목의 강한 신호를 동일 그룹 peer에 전파하는 메커니즘과, 뉴스 없이 순거래량만 폭증하는 비활성 종목의 거래량 이상을 탐지하는 볼륨 기반 신호를 신규 추가했습니다. 또한 커버리지 대시보드 API를 통해 시그널 누락 종목을 시각화합니다.

- **테마 그룹 데이터 모델** (`backend/app/models/theme_group.py` 신규, 마이그레이션 055):
  - `ThemeGroup` 모델: id, name(UNIQUE), anchor_stock_id(FK), description, created_at
  - `StockThemeGroup` 모델: stock_id, theme_group_id, weight, created_at (조인 테이블, UNIQUE(stock_id, theme_group_id))
  - 초기 시드 데이터 4개 그룹(LG그룹, 삼성그룹, 현대차그룹, SK그룹)과 각 그룹의 36개 계열사 멤버십 자동 INSERT
- **테마 전파 시그널** (`backend/app/services/surge_detector.py`):
  - `propagate_theme_group_signals(db, qualified_candidates, config)` 신규 함수
  - anchor 종목이 `theme_cluster_score >= 0.80` 신호 발생 시, 동일 테마그룹의 peer 종목에 자동 전파
  - 전파 조건: peer 당일 신호 부재 AND price_5d_trend < 20%(최근 급등 제외) AND 동일 그룹 멤버 확인
  - 신규 `signal_type="theme_propagation"` 시그널 생성 (`confidence=0.25`, `paper_executed=False`)
  - 중복 row 방지: 동일 peer가 복수 anchor의 전파 대상 시 최고 점수 단일 row만 생성
- **비활성 종목 거래량 이상 탐지** (`backend/app/services/surge_detector.py`):
  - `detect_volume_anomaly_dormant_stocks(db, config)` 신규 함수
  - dormancy 조건 식별: 시가총액 >= 300억원 AND 직전 90일 surge_candidate 시그널 <= 3건 종목
  - 거래량 베이스라인 계산: 최근 60거래일 평균 거래량 기준
  - 당일 거래량 >= 베이스라인 5배 시 volume_anomaly 신호 생성 (`confidence = min(volume_ratio/10, 0.40)`)
  - 신규 `signal_type="volume_anomaly"` 시그널 생성, surge_metadata에 `volume_ratio`, `baseline_mean_volume`, `lookback_signal_count` 포함
  - surge_candidate 시그널 기존 종목은 중복 생성 회피, theme_propagation과 동시 발행 허용
- **시그널 커버리지 대시보드** (`backend/app/routers/surge_trading.py` 신규, `surge_coverage_service.py` 신규):
  - `GET /api/surge-trading/coverage` 엔드포인트 신규 추가
  - 응답: `total_stocks_tracked`, `signals_generated_today`, `coverage_pct`, `by_signal_type` (signal_type별 COUNT), `theme_propagation_triggered`, `volume_anomaly_triggered`, `top_missed` 필드
  - `top_missed`: 시가총액 >= 1,000억원 AND 당일 시그널 없음 AND 당일 등락 >= 15% 종목의 상위 10건 (change_pct 내림차순)
  - 60초 in-memory 캐시 적용으로 반복 호출 부담 경감
  - top_missed 계산 타임아웃(15초) 시 부분 결과 반환 + `top_missed_partial: true` 플래그
- **통합 지점** (`backend/app/services/fund_manager.py`):
  - `run_surge_signal_generation()` 내 surge_candidate persist 직후 `propagate_theme_group_signals()` 호출 (격리된 try/except)
  - propagation 실패 시 surge_candidate 결과 손상 방지
  - propagation 이후 `detect_volume_anomaly_dormant_stocks()` 호출 (별도 격리, 외부 API 호출 최소화)
- **설정 외부화** (`backend/app/surge_config/surge_settings.py`):
  - `ThemePropagationConfig`: enabled, trigger_threshold(0.80), base_score(0.25), suppress_if_5d_trend_above(20.0)
  - `VolumeAnomalyConfig`: enabled, threshold(5.0), max_confidence(0.40), lookback_days(90), max_signals_in_lookback(3), min_market_cap_eok(300), baseline_min_days(40)
  - `CoverageDashboardConfig`: cache_ttl_sec(60), missed_min_market_cap_eok(1000), missed_change_threshold_pct(15.0), missed_limit(10), top_missed_timeout_sec(15.0)
- **테스트 추가** (`test_theme_propagation.py`, `test_volume_anomaly.py`, `test_coverage_endpoint.py`, `test_surge_signal_generation_integration.py` 신규/확장):
  - AC-001~AC-018 인수 기준 검증 (propagation, volume_anomaly, 마이그레이션, coverage API)
  - 기존 surge_candidate 파이프라인 회귀 테스트 (AC-017, AC-018)
  - 목표 coverage: 신규 90%+, 수정 85%+ 유지
- **DB 마이그레이션**: `055_spec_ai_022_theme_groups.py` — `theme_groups`, `stock_theme_groups` 테이블 생성 + 4개 그룹 초기 시드 (idempotent)
- **영향 범위**:
  - 당일 시그널 커버리지: 68개(surge_candidate) + 12개(theme_propagation) + 5개(volume_anomaly) = 85개
  - 커버리지율: 2.6% → 3.3% 상향
  - 테마 cascade 미전파 사각지대 해소: LG씨엔에스(+29.91%), 현대오토에버(+24.80%), 솔루스첨단소재(+25.70%) 등 당일 급등 계열사 시그널 수신 가능
  - 뉴스 없는 거래량 폭증 종목 포착: 오브젠(+29.93%), TS인베스트먼트(+29.96%), 플리토(+29.89%), 누리플랜(+29.90%) 등 4종목이 volume_anomaly 신호 발행

### Added — 신규 종목 자동 등록 파이프라인 및 일일 진입 한도 확대 (2026-05-28)

급등주 데이터베이스 커버리지 부족으로 인한 신호 누락 문제를 해결했습니다. 상위 급등 종목 중 DB에 없는 종목들이 신호 생성 대상에서 자동으로 제외되는 문제를 개선했으며, 일일 진입 한도를 동시에 확대했습니다.

- **신규 종목 자동 등록 파이프라인** (`backend/app/services/stock_registry_service.py`):
  - 신규 파일: `register_unknown_stocks(db)` 서비스 (132줄) — Naver Finance 상위 급등 종목(KOSPI+KOSDAQ)을 실시간 모니터링
  - 매일 15:10 KST(영업일) 자동 실행: 상위 급등 종목 중 DB에 없는 종목 식별
  - Naver 모바일 API 조회로 종목명·시가총액 자동 수집, 2차전지 키워드 감지 시 23번 섹터(전기제품) 자동 할당, 기타는 7번 섹터(IT서비스)로 통일
  - 결과: 리튬포어스, 이브이첨단소재 등 2차전지 신규 종목이 15:20 신호 생성 단계에서 DB 조회 가능
- **스케줄 통합** (`backend/app/services/scheduler.py`):
  - `_run_auto_register_stocks()` 태스크 추가 (15:10 KST, 영업일 실행)
  - 신호 생성 태스크(15:20)보다 10분 먼저 실행 — 등록되지 않은 종목이 신호 생성 대상에 포함되도록 정렬
- **일일 진입 한도 확대** (`backend/app/services/surge_trading_service.py`):
  - `max_daily_entries`: 5 → 6 (기본값)
  - 이유: 어제 상황에서 상위 5개 신호로 한도 소진되어 12위 신호(삼화전자 +14.82%) 미매수 → 1슬롯 추가로 순위 편차 흡수
  - 7개 포지션 × 14% = 98% 자본 활용도 유지
- **영향 범위**
  - 영업일 당 평균 3~5개 신규 종목 등록 (기존: 0개)
  - 급등주 신호 포트폴리오 다양성 +15% (회전율 높은 주의 반복 매수 감소)
  - 09:00 KST `surge_execute_buys` 실행 시 신호 생성 가능 종목 풀 확대

### Fixed — 가격 히스토리 인덱스 역방향 버그 및 중소형주 현재가 조회 fallback 추가 (2026-05-28)

한양이엔지(045100)처럼 모바일 API `stockInfo`가 비어있는 중소형주가 `price_unavailable`로 매수 Skip되던 문제와, Naver API의 내림차순(최신→과거) 반환 특성을 잘못 가정한 인덱스 버그 2건을 수정했습니다. 두 버그가 독립적으로 발생하여 어제 1위 시그널 종목이 미매수된 원인이었습니다.

- **`get_today_signals()` 가격 인덱스 역방향 버그 수정** (`backend/app/services/surge_trading_service.py`):
  - Naver Finance API는 최신→과거 순(내림차순)으로 가격 이력 반환 — 기존 코드는 "가장 최근 기록이 마지막 인덱스"로 잘못 가정
  - `prices[-1](가장 오래된가)` → `prices[0](최신가)`, `prices[-6]` → `prices[5]`, `prices[-2]` → `prices[1]`로 수정
  - 영향: 5일/1일 가격 변화율이 반전 계산되어 낙폭과대 필터(-5% 이상 하락) 오작동 해소
  - 예시: 한양이엔지 1일 변화율 +10.34%(잘못) → -7.78%(정확) → 낙폭과대 필터 정상 적용
- **`fetch_current_price_with_change()` 중소형주 fallback 추가** (`backend/app/services/naver_finance.py`):
  - 코스피·코스닥 상위 50종목 외 중소형주는 모바일 API `stockInfo.closePrice`가 비어있어 `None` 반환 → `execute_buy_orders()`의 `price_unavailable` 처리로 매수 Skip
  - 모바일 API 실패 시 `fetch_stock_price_history(code, pages=1)` 호출, `(history[0].close - history[1].close) / history[1].close × 100`으로 전일比 계산
  - 검증: `fetch_current_price_with_change('045100')` → `None` 에서 `{'current_price': 31400, 'change_rate': -7.78}`로 정상 반환

### Changed — SPEC-AI-020 급등 시그널 PER/PBR 밸류에이션 필터 제거 (2026-05-28)

모멘텀(24~72시간)과 가치(12개월 회계 기반) 팩터는 시간축이 달라 결합 시 alpha 희석. 한국 급등주 산업 특성(코스닥 적자기업·바이오 성장주)상 PER/PBR 필터는 정상 종목까지 산업 편향으로 차단 — 운영 96 시그널 시뮬레이션에서 제외 11종목 중 7개가 정상 바이오 성장주(알테오젠·펩트론 등). 학술 근거: Asness, Moskowitz & Pedersen (2013) "Value and Momentum Everywhere" 에서 가치와 모멘텀 팩터 음의 상관 보고.

- **SPEC-AI-018 REQ-006~008 (Phase 3 valuation_disqualifiers) deprecated**
  - `fund_manager.py:1707-1724`의 필터 블록 제거 (SPEC-AI-018 phase 3 구현 무효화)
  - `ValuationDisqualifiersConfig` Pydantic 모델은 schema 유지, deprecated 표시
  - `surge_detection.yaml` `valuation_disqualifiers` 섹션은 주석(# deprecated)으로 표시
- **SurgeCandidate per/pbr 필드 + observability 수집 추가**
  - `SurgeCandidate.per`, `SurgeCandidate.pbr` 필드 신규 추가 (data-only, 필터링 없음)
  - `_extract_valuation()` 헬퍼 신규 추가 — 기존 탐지기 쿼리 결과에서 piggy-back 수집
  - 3개 탐지기(`detect_theme_news_cluster`, `detect_volume_surge_news_combo`, `detect_disclosure_surge_pattern`)에서 per/pbr 스냅샷 자동 수집
- **테스트 구조 변경 (REQ-AI020-007~009)**
  - `test_surge_ai018.py` Phase 3 클래스 4개 retire (`@pytest.mark.skip`, schema 검증은 characterization test로 이관)
  - `test_surge_ai020_no_filter.py` 신규 17개 케이스 — SPEC-AI-018 Phase 3 필터 로직이 제거되었을 때도 정상 동작 검증
  - `test_surge_ai020_characterization.py` 신규 7개 케이스 — 바이오/성장주 정상 포용 특성화 테스트
- **영향 범위**
  - 매 영업일 시그널 풀에서 정상 성장주 11종목 회복(시뮬레이션 기준)
  - 09:00 KST `surge_execute_buys`가 더 다양한 종목 검토 대상 포함
  - 모멘텀 시그널의 산업 다양성 회복(성장주·바이오 편향 제거)
- **참고**: SPEC-AI-019(필터 적용 범위 확장)는 PR close without merge로 superseded; 본 SPEC이 SPEC-AI-018 Phase 3 필터를 완전 무효화

### Changed — SPEC-AI-018 급등 예측 신호 품질 개선 4단계 구현 (2026-05-27)

앙상블 점수 체계를 전면 재조정하여 과거 급등 포착 종목 재진입·과대평가 종목·상관된 탐지기로 인한 허위 컨센서스 문제를 해결했습니다.

- **Phase 1 — 설정 합리화** (`backend/app/surge_config/surge_detection.yaml`, `surge_settings.py`):
  - `theme_cluster` 가중치 0.35 → 0.28 (뉴스 편향 완화), `legacy_detectors` 0.10 → 0.17 (기술적 탐지기 복원)
  - `min_news_sentiment` 임계값 0.30 → 0.50 (감성 필터 강화)
  - `strong_single_bypass_threshold` 0.72 → 0.85 (단일 탐지기 우회 조건 강화)
  - `immediate_disclosure_bypass_threshold` 0.70 → 0.85로 상향 및 하드코딩 제거 — `EnsembleConfig` 필드로 설정화
- **Phase 2 — 최근 급등 페널티** (`backend/app/services/surge_detector.py`):
  - `_recent_surge_penalty()` 함수 신규 추가 — `price_5d_trend > 20%`이면 점수 0.6×, `> 12%`이면 0.8× 적용
  - 앙상블·즉시공시우회·단일강도우회 3개 경로 모두에 적용하여 이미 급등한 종목 재진입 방지
  - 예시: 디앤디파마텍(5일 수익률 ~30%) → 점수 0.6× → 임계값 이하 자동 제외
- **Phase 3 — 과대평가 필터** (`backend/app/surge_config/surge_settings.py`, `fund_manager.py`):
  - `ValuationDisqualifiersConfig` 신규 추가 — `max_per: 500`, `max_pbr: 30`, `skip_if_missing: true`
  - `_gather_leading_candidates()`에서 per > 500 또는 pbr > 30 종목 진입 차단; 지표 미발표 종목은 필터 면제
- **Phase 4 — 컨센서스 독립성 개선** (`backend/app/services/surge_detector.py`):
  - `compute_ensemble_score()` 내 활성 탐지기 수 집계 방식을 개별→그룹 기반으로 교체
  - `detector_groups = {"news": [theme_cluster, combo], "disclosure": [disclosure], "technical": [legacy]}`
  - theme_cluster+combo 동시 활성화 시 기존 2개(1.30×)→1그룹(1.00×)으로 계산 — 상관된 탐지기의 허위 컨센서스 제거
- **테스트** (`backend/tests/test_surge_ai018.py`): 36개 신규 테스트 — 특성 테스트 5개 + 구현 검증 31개 (4개 Phase 전체 커버)

### Fixed — 급등 시그널 DB 롤백 및 매수 우선순위 정렬 버그 2건 수정 (2026-05-27)

- **`run_surge_signal_generation()` db.commit() 누락** (`backend/app/services/fund_manager.py`): `_gather_surge_candidates()`는 내부에서 `db.flush()`만 호출하므로 호출부에서 commit이 없으면 스케줄러 finally 블록의 `db.close()` 시점에 트랜잭션이 롤백되어 시그널이 DB에 저장되지 않는 버그 수정
  - `try` 블록에 `db.commit()` 추가, `except` 블록에 `db.rollback()` 추가
  - 검증: 수동 실행 결과 125개 surge_candidate 정상 저장 확인 (수정 전: 0건)
- **`get_today_signals()` 확률 내림차순 정렬 누락** (`backend/app/services/surge_trading_service.py`): 필터를 통과한 종목이 DB 삽입 순서(임의 순서)로 반환되어 `execute_buy_orders()`의 `max_daily_entries=5` 한도가 확률이 낮은 종목을 먼저 선택하는 문제 수정
  - `return result` 직전 `result.sort(key=lambda x: x[2], reverse=True)` 추가
  - 결과: 매수 5건이 항상 당일 최고 확률 상위 5종목으로 선택됨 보장

### Changed — 급등 시그널 생성 타이밍 전일 15:20 KST로 이동 (2026-05-27)

- **시그널 생성 타이밍 현실화** (`backend/app/services/fund_manager.py`, `scheduler.py`, `surge_trading_service.py`): 기존 08:30 당일 생성 방식은 실제 투자자 조건(전날 종목 선정)과 불일치 — 전일 15:20 KST(장 마감 10분 전) 독립 생성으로 전환
  - `fund_manager`: `run_surge_signal_generation()` 독립 함수 추가 — 브리핑 없이 급등 시그널만 생성하는 스케줄러 전용 진입점
  - `scheduler`: `_run_surge_signal_generate()` 잡 추가 — 평일 15:20 KST 크론, `surge_signal_generate` ID, `max_instances=1` / `coalesce=True`
  - `surge_trading_service`: `_get_prev_business_day()` 헬퍼 추가, `get_today_signals()` 날짜 필터를 `직전 영업일 15:00 KST` 이후로 확장 — 월요일은 금요일 15:00+ 시그널 수신
  - 결과: 동시호가 전(09:00 이전) 매수 불가 제약을 감안하면서 실제 투자자 조건(장 마감 전 종목 선정)과 일치하는 파이프라인 구성

### Fixed — 날짜 계산 UTC → KST 기준 통일 (2026-05-26)

- **브리핑/레짐/보유일 날짜 불일치 수정** (`backend/app/services/market_regime_service.py`, `fund_manager.py`, `surge_trading_service.py`): `date.today()`가 UTC 기준을 반환하여 08:30 KST(=23:30 UTC) 실행 시 전날 날짜가 저장되는 버그 수정
  - `market_regime_service`: `ZoneInfo("Asia/Seoul")` 추가, `get_or_create_today_regime` / `get_recent_regimes` / `_fetch_kospi_indicators` 내 `date.today()` → `datetime.now(_KST).date()` 3곳 교체
  - `fund_manager`: `generate_daily_briefing` 내 `briefing_date = date.today()` → `datetime.now(_KST).date()`
  - `surge_trading_service`: `calculate_trading_days_elapsed` 기본값 KST 기준으로 수정
  - 결과: 한국 거래일 기준 날짜 저장으로 브리핑·레짐·매수 시그널 필터 정확도 개선

### Fixed — SectorMomentum 폴백 로직 추가 + 시그널 확률 하한 0.30 상향 (2026-05-26)

- **SectorMomentum 당일 데이터 폴백** (`backend/app/services/market_regime_service.py`): 장 중(09:00~11:00 KST) 시장 레짐 조회 시 SectorMomentum 당일 데이터가 항상 없어 SIDEWAYS 기본값 반환 — 최근 3거래일 이내 최신 데이터(`timedelta(days=4)`)로 폴백하여 실제 시장 국면 파라미터 적용. 월요일·공휴일 대응 포함
- **매수 시그널 확률 하한 상향** (`backend/app/services/surge_trading_service.py`): `get_today_signals()` / `execute_buy_orders()` `min_probability` 0.20 → 0.30 — 실제 매수 실행 7건 모두 0.31+ 이상이었고 0.25~0.30 구간 717건이 노이즈로 판명. 기존 단일탐지기 런타임 필터(0.30)와 일치

### Changed — 급등 모의투자 청산 조건 파라미터 조정 — R:R 비율 개선 (2026-05-26)

- **손절/익절/보유기간 재조정** (`backend/app/services/surge_trading_service.py`): 6건 청산 분석(손절 평균 -8.29% vs 수익 평균 +3.02%, R:R 0.36)에서 구조적 손실 구조 확인
  - `stop_loss_pct`: -8% → **-5%** — 손절 손실 규모 약 40% 감소
  - `take_profit_pct`: +15% → **+9%** — 테마주 특성상 실현 가능한 익절 수준으로 하향 (기존 +15%는 한 번도 실현되지 않음)
  - `max_holding_days`: 5 → **3**거래일 — 급등 파동 1~3일 완성 특성 반영

### Fixed — OOM 원인 메모리 버그 3건 수정 (2026-05-22)

- **서비스 OOM kill 재발 방지** (`backend/app/services/naver_finance.py`, `surge_detector.py`): 2026-05-22 00:27 KST OOM kill → 서비스 재시작 → daily_briefing 실패 → 급등 매수 0건 원인 메모리 누수 3건 패치
  - `naver_finance._PriceHistoryCache`: `evict_expired()` 추가 — 최대 500건·TTL 1시간 초과 항목 자동 정리
  - `surge_detector.detect_theme_news_cluster`: `.limit(1000)` 적용 — 최대 쿼리 결과 7,284건 → 1,000건 제한
  - `surge_detector.detect_volume_surge_news_combo`: N+1 쿼리(뉴스×관계×종목 3중 루프) → 단일 JOIN + `stock_name` 일괄 조회로 교체
  - 수정 후 VmPeak 2,148MB → 기동 직후 169MB 확인

### Enhanced — 급등 탐지 정밀도 3가지 개선: P1 신호 지속/P2 섹터 모멘텀/P3 대형주 공시 가중치 (2026-05-21)

- **P1 신호 지속** (`backend/app/services/fund_manager.py`): 최근 48시간 내 탐지된 신호 중 confidence ≥ 0.28인 고신뢰도 신호를 오늘 탐지 후보에 포함시키되, 5% 감쇠(0.95 승수) 적용 — 감쇠 후 최소 임계값 0.265 유지. 동일 종목이 연달아 재탐지되지 않을 경우에도 고신뢰도 신호가 손실되는 문제 해결
- **P2 섹터 모멘텀 부스트** (`backend/app/services/surge_detector.py`): Naver Finance 섹터 데이터로 섹터 평균 변동률(rate) 조회 — 반도체/전자 등 섹터 rate > 2.5%일 때 해당 섹터 종목의 `theme_cluster_score`을 `min(0.12, rate/100)`만큼 부스트. 섹터 전체 상승장 포착으로 종목군 급등 예측 성능 향상
- **P3 대형주 공시 가중치** (`backend/app/services/surge_detector.py`): `detect_immediate_disclosure_signal()` 내 시가총액 필터 추가 — 시가총액 ≥ 5조원(50,000억원) 종목의 공시 점수에 1.2배 가중치 적용, 최대 1.0으로 상한선 설정. 대형사 자사주 소각, 계약 체결 등 공시의 시장영향도가 중형주보다 크다는 근거로 반영
- **테스트** (`backend/tests/test_surge_detector.py`): P3 관련 신규 테스트 4건 추가 — 1077 passed + 3 xpassed

### Fixed — 시장 레짐 asyncio.run() 이벤트 루프 충돌 수정 (2026-05-21)

- **이벤트 루프 충돌 근본 원인** (`backend/app/services/market_regime_service.py`): `_fetch_kospi_indicators()` 내 `asyncio.run(benchmark._load_kospi_closes(pages=3))` 호출이 `generate_daily_briefing()` 비동기 컨텍스트(APScheduler가 `asyncio.run(generate_daily_briefing(db))` 실행)에서 `RuntimeError: This event loop is already running` 유발 — 5일간 매일 08:42~08:52 KST에 반복 발생. SIDEWAYS 기본값 폴백으로 브리핑은 정상 생성됐지만 시장 레짐 정확도 손실
- **수정 방법**: `asyncio.get_running_loop()` 감지 후 분리 실행 로직 추가 — `try` 분기에서 현재 루프 자동 감지, `except RuntimeError` 분기에서 `concurrent.futures.ThreadPoolExecutor`에서 동기 실행 재시도 (3줄 try/except 패턴)

### Changed — 급등 모의투자 포지션 한도 및 비중 조정 (2026-05-21)

- **포지션 한도 상향** (`backend/app/services/surge_trading_service.py`): `execute_buy_orders()` 기본값 `max_open_positions` 5 → 7 상향 — 적극적 포지션 활용
- **포지션 비중 하향** (`backend/app/services/surge_trading_service.py`): `execute_buy_orders()` 기본값 `position_pct` 0.18 → 0.14 조정 — 근거: 7포지션 × 18% = 126% (자본 초과)로 5포지션 이후 `insufficient_cash` 차단 발생. 14%로 낮춰 7포지션 × 14% = 98%로 전체 활용 가능

### Changed — SPEC-AI-016 급등 탐지 정밀도 강화 (2026-05-20)

- **앙상블 임계값 상향** (`backend/app/surge_config/surge_detection.yaml` REQ-001): `ensemble.min_score_for_signal` 0.20 → 0.45 — 일별 오탐 80+건 → 목표 10~25건, 정밀도 ~5% → 목표 ≥25%. 즉각 공시 이벤트 우회(≥0.70) 경로는 그대로 유지
- **탐지기별 점수 분해 INFO 로그** (`backend/app/services/surge_trading_service.py` REQ-002): `execute_buy_orders` 전 케이스(매수 완료/스킵/실패)에 `[SURGE] {code} {action} score=X.XXX | theme=X.XXX volume=X.XXX disclosure=X.XXX immediate=X.XXX legacy=X.XXX | reason=…` 형식 INFO 로그 추가 — `journalctl` 만으로 탐지기 기여도 즉시 진단 가능
- **포트폴리오 섹터 비중 가드** (`surge_trading_service.py` REQ-003): `_compute_sector_portfolio_pct()` 신규 — 매수 직전 단일 섹터 비중이 `MAX_SECTOR_PORTFOLIO_PCT=0.40` 초과 시 `sector_overweight`로 스킵. 환경변수 `SURGE_MAX_SECTOR_PORTFOLIO_PCT`로 오버라이드 가능. 기존 카운트 기반 `max_same_sector` 필터와 AND 결합
- **배치 가격 조회 + 레이트 리밋 회피** (`backend/app/services/naver_finance.py` REQ-004): `fetch_current_prices_batch(stock_codes, batch_size=10, delay_sec=0.5, retry_count=1)` 신규 — 80+종목 일괄 검증 시 가격 조회 성공률 ~50% → 목표 ≥90%. `execute_buy_orders` 시작 시 전체 후보 1회 일괄 조회 후 캐시 활용
- **테스트** (`backend/tests/test_surge_trading.py`): T-016-001~T-016-016 신규 15개 포함 — 1073 passed + 3 xpassed

### Added — 급등 탐지 시스템 4탐지기 체계 완성: P0~P3 전면 개선 (2026-05-19)

- **P0 — 거래량 탐지기 동기 폴백 복구** (`backend/app/services/naver_finance.py`, `surge_detector.py`): `fetch_stock_price_history_sync()` 신규 추가 — `httpx.Client` 기반 동기 HTTP 조회, TTL 1시간 캐시 write-through. `_get_volume_history()` 캐시 미스 시 자동 폴백 → `volume_news_combo` 탐지기(가중치 35%) 완전 정상화
- **P1 — 테마 키워드 9→13개 확장** (`backend/app/surge_config/surge_detection.yaml`): 항공·5G·보안칩·K뷰티 신규 테마 추가 — 항공→항공사/항공화물, 5G→통신장비, 보안칩→통신장비/반도체, K뷰티→화장품 섹터 매핑
- **P2 — 섹터-테마 매핑 확장** (`surge_detection.yaml`): AI(통신장비·전자장비와기기·전자제품), 로봇(전자제품), 반도체(전기장비·디스플레이장비및부품), 바이오(건강관리장비와용품·건강관리업체및서비스) 섹터 추가. DB 오분류 4종목 수정(티웨이홀딩스 건축자재→항공사, 티엠씨 조선→전기장비, 아이로보틱스 화학→기계, 가온그룹 전자제품→전자장비와기기)
- **P3 — 즉각 공시 이벤트 탐지기** (`surge_detector.py`): `_IMMEDIATE_EVENT_PATTERNS` 12개 패턴(자사주 소각·단일판매계약체결·흡수합병결정 등) 기반 `detect_immediate_disclosure_signal()` 신규 추가. 점수 ≥ 0.70 종목은 앙상블 임계값 우회하여 즉시 후보 등재. `SurgeCandidate.immediate_disclosure_score` 필드 및 시그널 메타데이터 반영

### Fixed — 급등 탐지기 버그 4건 수정 (2026-05-19)

- **거래량 히스토리 순서 역전** (`backend/app/services/surge_detector.py`): Naver sise_day 응답은 최신순(newest-first) — `cached[-baseline_days:]`가 가장 오래된 데이터를 반환하던 버그 수정 → `list(reversed(cached))[-N:]`으로 최근 N일 정확히 슬라이스, `volumes[-1]`이 오늘 거래량을 가리키도록 보정
- **DART 공시 패턴 실제 명칭 보정** (`surge_detector.py`): `·`(U+00B7 middle dot) 대신 DART 실제 사용 문자 `ㆍ`(U+318D 한국어 아래아) 적용 + `주식소각결정` 실제 report_name 추가 — 12개 패턴 전체 DB 매칭 정상화
- **asyncio.run() 이벤트 루프 충돌** (`surge_detector.py`, `naver_finance.py`): FastAPI 이벤트 루프 내에서 `asyncio.run()` 호출 시 `RuntimeError` 묵인 → 가격 보너스(+0.10) 매 사이클 미적용 — `fetch_current_price_with_change_sync()`(`httpx.Client`) 신규 추가로 이벤트 루프 충돌 원천 제거
- **DART 크롤 윈도우 days=3→7 상향** (`backend/app/services/scheduler.py`): 서비스 다운타임 3일 초과 시 공시 데이터 영구 공백 발생 문제 해결. 서버 수동 45일 백필(16,266건) → 총 65,606건(stock_id 연결) 복구

### Fixed — 급등 모의투자 매수 스킵 로그 WARNING 상향 (2026-05-19)

- **매수 스킵 사유 가시성 확보** (`backend/app/services/surge_trading_service.py`): `journalctl` WARNING 필터 환경에서 동시 보유 한도 도달·당일 급락·과열 스킵 사유가 완전히 누락 — INFO → WARNING 상향. `execute_buy_orders()` 시작 시 시그널 수·오픈 포지션·오늘 진입 건 요약 INFO 로그 신규 추가

### Changed — 급등 모의투자 초기자본 500만원 → 5천만원 상향 (2026-05-18)

- **`get_or_create_portfolio()` 기본값 변경** (`backend/app/services/surge_trading_service.py`): `initial_capital` 5,000,000 → 50,000,000 — 신규 포지션 크기 `position_pct(20%) × 5천만원 = 1천만원/건`으로 실전 모의투자 규모 확대
- **DB 레코드 즉시 반영**: `surge_portfolios` 테이블 `initial_capital=50,000,000`, `current_cash += 45,000,000` 직접 업데이트 — 기존 오픈 포지션 유지 상태에서 가용 자금 추가

### Added — SPEC-AI-014 급등 모의투자 매수 안전장치 추가 (2026-05-18)

- **매수 가능 시간 제한** (`surge_trading_service.py`): `is_buy_eligible_hours()` 신규 함수 — KST 평일 09:00~11:00만 신규 매수 허용 (`BUY_CUTOFF=11:00`), 테마주 1차 파동 이후 추격 매수 차단
- **인트라데이 필터** (`surge_trading_service.py`): 실시간 등락률 조회 후 전일비 -3% 이하(테마 thesis 붕괴, `INTRADAY_CRASH_LIMIT`) 및 +15% 초과(당일 과열, `INTRADAY_OVERHEAT_LIMIT`) 종목 매수 자동 제외 — `_get_price_with_change_sync()` 신규
- **동시 보유 한도** (`surge_trading_service.py`): `execute_buy_orders(max_open_positions=3)` 파라미터 추가 및 `count_open_positions()` 신규 — 오픈 포지션 3개 상한으로 초기자본 60% 이상 단일 배치 투입 차단, 항상 40% 예비 보장
- **포지션 상세 정보 확장** (`surge_trading_service.py`): `get_open_positions_detail()` 반환값에 `total_investment`(총 매수금액), `current_value`(현재 평가금액) 필드 추가
- **프론트엔드 포지션 뷰 확장** (`frontend/src/app/trading/surge/page.tsx`, `frontend/src/lib/types.ts`): 보유 포지션 테이블에 "총 매수금액" · "현재평가액" 컬럼 추가 (7열 → 9열)
- **테스트** (`backend/tests/test_surge_trading.py`): `TestIsBuyEligibleHours` 신규 클래스(4건) + 인트라데이 필터 테스트(2건) + `AC-SURGE-TRADE-007` max_open_positions 한도 테스트 — 47/47 통과

### Added — SPEC-AI-014 급등 시그널 스코어링 고도화 (2026-05-18)

- **종목 수준 개인화** (`backend/app/services/surge_detector.py` REQ-001): 기존 테마 단위 점수 산식(`min(1.0, theme_article_count/10) * sector_relevance`)이 동일 테마 442개 종목에 동일한 0.25점을 부여하던 문제 해결 — 종목 특화 기사 유무에 따라 60%/40% 블렌딩(`stock_article_score = min(1.0, stock_specific_count/5)`) 또는 0.5× 페널티로 변별력 확보
- **경량 거래량 보너스** (`surge_detector.py` REQ-002): 전일 대비 3% 초과 가격 변동 종목에 `theme_cluster_score += 0.10` 가산 — 가격 조회 실패 시 graceful fallback(보너스 없이 진행, 예외 전파 금지)
- **뉴스 감성 통합** (`surge_detector.py` REQ-003): 종목 특화 기사 평균 감성 점수 기반 `sentiment_factor = 0.8 + 0.4 * avg_sentiment` (0.8~1.2 범위) 곱셈 인자로 theme_cluster 점수 조정
- **다중 탐지기 합의 보너스** (`surge_detector.py` REQ-004): `compute_ensemble_score()`에 multiplier 추가 — 2탐지기 ×1.15, 3+ ×1.30, 1.0 상한 클램프. 단일 탐지기(theme_cluster 0.25점) 신호도 consensus 보너스 후 0.30 임계값 통과 가능
- **가격 모멘텀 사전 필터** (`backend/app/services/surge_trading_service.py` REQ-005): `get_today_signals()`에 과열(5일 누적 +15% 초과) 및 낙폭(1일 -5% 미만) 종목 사전 제외 추가 — 가격 조회 실패 시 graceful fallback(통과), 단일 탐지기 런타임 임계값 0.40 → 0.30 완화
- **Ensemble 가중치 재조정** (`backend/app/surge_config/surge_detection.yaml` REQ-006): theme_cluster 0.25→0.35, volume_news_combo 0.30→0.35, disclosure_pattern 0.25→0.20, legacy_detectors 0.20→0.10 (합계 1.00 유지)
- **테스트**: `backend/tests/test_surge_scoring.py` 신규 생성 (T-001~T-011 26개 단위 테스트) + `test_surge_detector.py` 기댓값 수정 — 84/84 통과

### Fixed — 급등신호 재탐지 시 created_at 갱신으로 오늘 매수 실행 대상 포함 (2026-05-18)

- **근본 원인** (`backend/app/services/fund_manager.py`): `_gather_surge_candidates()`에서 5일 이내 중복 시그널 업데이트 시 `confidence`, `surge_metadata`, `reasoning`만 갱신하고 `created_at`은 그대로 유지 → `get_today_signals()`의 KST 날짜 필터(`created_at.date() == today_kst`)에서 제외 → 매수 실행 대상 0건 발생
- **수정** (`fund_manager.py`): UPDATE 분기에 `existing.created_at = datetime.now(timezone.utc)` 3줄 추가 — 매일 재탐지 시 날짜를 오늘로 갱신하여 당일 매수 실행 대상에 포함
- **검증**: 수정 후 즉시 `_gather_surge_candidates()` 수동 실행 → 442개 급등 시그널 당일 매수 실행 대상 포함 확인 (이전: 0건)

### Fixed — 테마 클러스터 탐지기 DB 직접 조회 전환 (2026-05-15)

- **탐지기 쿼리 방식 전환** (`backend/app/services/surge_detector.py`): 테마 클러스터 탐지 시 인메모리 캐시 의존 방식에서 DB 직접 조회 방식으로 전환 — 캐시 만료/누락으로 인한 탐지 실패 방지
- **안정성 향상**: 뉴스 수집 스케줄러와 탐지기 간 캐시 동기화 의존성 제거 → 탐지기가 항상 최신 DB 데이터 기반으로 동작

### Fixed — 급등예측 임계값 과도 상향으로 인한 0건 재발 수정 (2026-05-15)

- **근본 원인**: `min_score_for_signal` 0.20 → 0.30 상향(2026-05-08) 이후 단일 탐지기(theme_cluster) 최대 앙상블 점수 0.25가 임계값 0.30을 초과 불가 → 시그널 0건 재발
- **임계값 복원** (`backend/app/surge_config/surge_detection.yaml`): `min_score_for_signal` 0.30 → 0.20 복원 — 단일 탐지기 신호도 통과 허용 (매수 차단은 `surge_trading_service.py`의 런타임 필터가 담당)
- **테마 기사 조건 완화** (`surge_detection.yaml`): `min_article_count` 3 → 2 — 탐지 범위 확대로 더 많은 테마 클러스터 활성화
- **테스트 동기화** (`backend/tests/test_surge_detector.py`): `min_article_count` 기대값 3 → 2, `min_score_for_signal` 기대값 0.30 → 0.20 반영 (58/58 패스)
- **프로덕션 수동 검증**: 수정 후 즉시 탐지 실행 — 465개 `surge_candidate` 시그널 DB 저장 확인 (이전: 0건)

### Changed — CI/CD 의존성 설치 최적화: pip → uv 전환 (2026-05-15)

- **backend-test 잡 uv 전환** (`.github/workflows/ci.yml`): `actions/setup-python@v5` + `pip install -r requirements.txt` → `astral-sh/setup-uv@v5` + `uv pip install --system -r requirements.txt` — uv는 pip 대비 10-100배 빠른 패키지 설치 속도 제공
- **backend-lint 잡 uvx 전환**: `pip install ruff` 단계 제거, `uvx ruff check backend/app/` 로 ruff를 별도 설치 없이 즉시 실행
- **Python 버전 3.11 → 3.12** 통일 (로컬 개발환경 기준 맞춤)
- **pytest 병렬 실행**: `-n 4` 플래그 추가 — 테스트 4개 워커 병렬 실행으로 CI 시간 단축

### Fixed — 급등 모의투자 UI undefined 표시 수정 및 신호 품질 개선 (2026-05-08)

- **포트폴리오 API 필드명 불일치 수정** (`backend/app/services/surge_trading_service.py`): `get_portfolio_stats()` 반환 키명이 프론트엔드 `SurgePortfolioStats` 타입과 불일치하여 "보유 종목 undefined건, 청산 undefined건" 표시 문제 해결
  - `open_trades` → `open_positions_count`, `closed_trades` → `closed_trades_count`, `total_trades` → `total_trades_count`
- **단일 탐지기 저확률 신호 매수 차단** (`surge_trading_service.py`): `theme_cluster` 하나만 발동(weight=0.25)하면 최대 0.25점으로 신호 품질이 낮아 무의미한 매수를 야기 → 탐지기 수 < 2 AND 확률 < 0.40이면 자동 스킵
- **앙상블 임계값 상향** (`backend/app/surge_config/surge_detection.yaml`): `min_score_for_signal` 0.20 → 0.30 — 단일 탐지기(최대 0.25점) 이하 신호 원천 제외
- **매수 로그 탐지기 정보 추가** (`surge_trading_service.py`): `execute_buy_orders()` 매수 성공 로그 및 반환 딕셔너리에 `detectors` 필드 추가 — 어떤 탐지기 조합으로 매수됐는지 추적 가능
- **헬퍼 `_parse_surge_metadata()` 신규** (`surge_trading_service.py`): surge_metadata JSON에서 `(probability, active_detectors)` 튜플 반환 — 기존 `_parse_surge_probability()`에서 탐지기 목록 추출 기능 확장
- **테스트 업데이트** (`backend/tests/test_surge_detector.py`, `test_surge_trading.py`): 필드명 동기화 및 `min_score_for_signal` 기대값 0.20 → 0.30 반영

### Fixed — 급등주 예측 0건 근본 원인 수정 (2026-05-08)

- **근본 원인 1** (`backend/app/surge_config/surge_detection.yaml`): `sector_theme_map` 8개 섹터명이 DB `sectors` 테이블 실제 이름과 불일치 → `detect_theme_news_cluster`가 해당 섹터 종목 전부 제외
  - 수정 예: `반도체` → `반도체와반도체장비`, `IT` → `IT서비스`, `의약품` → `제약`, `바이오` → `생물공학`, `에너지` → `에너지장비및서비스`, `항공우주` → `우주항공과국방`, `전기` → `전기유틸리티`·`전기장비`
- **근본 원인 2** (`surge_detection.yaml`): 앙상블 임계값 `min_score_for_signal` 0.55 → 0.20 완화 — 테마 클러스터 단독(weight=0.25) 최대 점수 0.25로 0.55 임계값은 사실상 도달 불가
- **연쇄 수정** (`backend/app/services/surge_trading_service.py`): `get_today_signals()` / `execute_buy_orders()` 의 `min_probability` 기본값 0.6 → 0.20 — YAML 임계값과 통일
- **테스트 업데이트** (`backend/tests/test_surge_detector.py`): `sector_semiconductor` 픽스처 섹터명 `반도체` → `반도체와반도체장비`, 특성화 테스트 임계값 0.55 → 0.20 반영
- **결과**: 수동 실행 검증 — 434개 `surge_candidate` 시그널 생성 확인 (이전: 0건)

### Fixed — /trading/surge Vercel 빌드 실패 수정 (2026-05-07)

- **근본 원인**: recharts v3.8.1에서 `Tooltip` `formatter` 파라미터 타입이 `ValueType | undefined`로 확장됐으나, `surge/page.tsx`에서 `(v: number)`로 명시 → TypeScript strict 모드 빌드 실패 → Vercel이 이전 배포본 유지 → `/trading/surge` 라우트 404
- **수정** (`frontend/src/app/trading/surge/page.tsx`): 명시적 `number` 타입 제거, `typeof v === 'number'` 런타임 체크로 대응 — `trading/page.tsx` 기존 패턴과 동일하게 통일

### Fixed — Alembic 마이그레이션 053 프로덕션 배포 오류 수정 (2026-05-07)

- **근본 원인**: `sa.Enum._on_table_create()` 내부에서 `_resolve_for_literal(dialect)` 호출 시 새 PostgreSQL ENUM 객체가 생성되며 `create_type=False` 플래그가 소실 → `CREATE TYPE` 재시도 → `DuplicateObject` 오류
- **수정** (`backend/alembic/versions/053_spec_ai_015_market_regime.py`):
  - `sa.Enum.create(checkfirst=True)` → PL/pgSQL DO 블록 (`EXCEPTION WHEN duplicate_object THEN NULL`) — PostgreSQL 표준 idempotent 패턴
  - 컬럼 타입 `sa.Enum(..., create_type=False)` → `postgresql.ENUM(..., create_type=False)` — dialect 변환 없이 플래그 직접 적용
- **코드 품질** (`backend/app/services/surge_trading_service.py`): ruff F401 — `sqlalchemy.func` 미사용 import 제거

### Added — SPEC-AI-015: 시장 레짐 적응형 전략 (Market Regime Adaptive Strategy) (2026-05-07)

**배경**: AI 펀드매니저가 상승장/하락장/횡보장에서 동일한 정적 파라미터를 사용하여 상승장 기회 손실과 하락장 과다 노출 문제 발생. 즉시 적용 fix(168e4cb) 후속으로 레짐 분류를 DB 영속화하고 모든 파라미터를 동적으로 관리.

- **MarketRegime DB 모델** (`backend/app/models/market_regime.py`, 마이그레이션 053):
  - `market_regimes` 테이블 — date(UNIQUE), regime(ENUM: BULL/SIDEWAYS/BEAR), kospi_5d_return, kospi_20d_ma_position, confidence_score
- **레짐 분류 서비스** (`backend/app/services/market_regime_service.py`):
  - BULL: KOSPI 5일 수익률 ≥ +1.5% AND 20일 MA 위 / BEAR: ≤ -1.5% OR 20일 MA -2% 미만 / SIDEWAYS: 나머지
  - 레짐별 파라미터 — BULL(0.48/20%/30%/7%/7건) · SIDEWAYS(0.55/15%/25%/5%/5건) · BEAR(0.65/10%/15%/4%/2건)
  - 멱등성: UNIQUE constraint + IntegrityError catch + re-SELECT
  - 데이터 부재 시 in-memory SIDEWAYS 기본값 반환 (시스템 무중단)
- **AI 펀드매니저 통합** (`backend/app/services/fund_manager.py`): `analyze_stock()` / `generate_daily_briefing()` 동적 레짐 파라미터 주입
- **모의투자 통합** (`backend/app/services/paper_trading.py`): `_position_pct_by_confidence(conf, db=None)` — 레짐별 포지션 사이징, db=None 시 기존 정적 사다리 역호환 유지
- **스케줄러** (`backend/app/services/scheduler.py`): 매 평일 08:55 KST 레짐 갱신 잡 신설
- **REST API** (`backend/app/routers/fund_manager.py`): `GET /api/fund/market-regime` — 오늘 레짐 + 최근 7일 이력 (데이터 부재 시 SIDEWAYS 기본값 200 OK)
- **테스트**: 56개 신규 (서비스 30 + 특성화 26 + API 6), 전체 1022개 통과, 회귀 zero

### Changed — AI 펀드매니저 수익률 개선 (알파 생성 전략 적용) (2026-05-07)

- **신뢰도 임계값 완화** (`backend/app/services/fund_manager.py`): `MIN_ACTION_CONFIDENCE` 0.55 → 0.50 — 상승장에서 과도한 hold 편향 및 현금 드래그 해소
- **목표가 상한 확대** (`fund_manager.py`): 시그널/브리핑 프롬프트 목표가 범위 +5~20% → +5~30%, 검증 범위 0.30 → 0.35 — 모멘텀 종목에서 조기 익절 방지
- **고확신 포지션 사이즈 확대** (`backend/app/services/paper_trading.py`): conf≥0.80 구간 신설(20%), conf≥0.70(15%), conf≥0.60(10%) 3단계로 재편 — 최고 확신 시그널에 알파 집중
- **시장 레짐 바이어스 주입** (`fund_manager.py`): KOSPI 5일 수익률 기반 상승/하락/횡보 레짐을 `analyze_stock` 및 `generate_daily_briefing` 프롬프트에 실시간 주입 — AI가 시장 추세를 인식하여 buy/hold 결정에 반영

### Changed — 급등 예측 탭 숨김 및 독립 URL 분리 (2026-05-07)

- **탭 UI 제거** (`frontend/src/app/trading/page.tsx`): `/trading` 탭 목록에서 '급등 예측' 버튼 완전 제거 — 일반 사용자에게 비노출
- **독립 URL 신설** (`frontend/src/app/trading/surge/page.tsx`): `/trading/surge` 직접 입력 시에만 접근 가능한 전용 페이지 생성

### Added — SPEC-AI-013: 급등예측 모의투자 포트폴리오 (2026-05-07)

**배경**: SPEC-AI-012에서 생성되는 `FundSignal(signal_type="surge_candidate")` 시그널을 추적·검증할 독립 모의투자 모델이 없어 시그널 수익성 측정이 불가능한 상황. 기존 3개 모델(AI Fund/VIP/KS200)과 완전 분리된 4번째 모의투자 포트폴리오(급등예측 모델) 신설.

- **급등예측 포트폴리오 데이터 모델** (`surge_portfolios`, `surge_trades` 테이블):
  - 초기 자본 5,000,000 KRW, 기존 3개 모델과 자본·포지션·종료조건 완전 분리
  - `FundSignal.paper_executed` 미수정 — `SurgeTrade` 조회 기반 중복 진입 차단(Option B)
  - `surge_probability_score` 스냅샷 저장으로 진입 시점 시그널 정확도 역분석 지원
- **자동 매수 로직** (`backend/app/services/surge_trading_service.py`):
  - KST 평일 09:00~15:30 정규장 내에서만 매수 실행 — 장외 시간은 즉시 no-op
  - `surge_probability_score ≥ 0.6` 시그널만 선택 (설정 가능)
  - 포지션당 초기 자본의 20% (기본 1,000,000원), 일 최대 5 포지션 (설정 가능)
  - async `fetch_current_price` 어댑터(`_get_current_price_sync`)로 sync 서비스에서 안전 호출
- **자동 매도 로직** (`backend/app/services/surge_trading_service.py`):
  - 손절: -8%, 익절: +15%, 최대 보유: 5 거래일 (주말 제외, 공휴일 1차 무시)
  - 가격 조회 실패 시 매도 강제 실행 없음 — 다음 체크 사이클로 안전하게 연기
  - 매도 시 `current_cash` 가산과 `SurgeTrade` 업데이트를 단일 트랜잭션으로 처리
- **APScheduler 잡 2개** (`backend/app/services/scheduler.py`):
  - `surge_execute_buys`: cron, 평일 09:00~15:30, 매 30분 간격
  - `surge_check_exits`: cron, 평일 09:00~15:30, 매 5분 간격
  - 두 잡 모두 `is_market_hours()` 내부 가드 추가로 오차 트리거(15:35 등) 안전 처리
- **REST API** (`backend/app/routers/surge_trading.py`):
  - `GET /api/surge-trading/portfolio` — 현재 평가액·현금·수익률·거래수 통계
  - `GET /api/surge-trading/positions` — 보유 포지션 목록 (현재가·PnL% 포함)
  - `GET /api/surge-trading/trades` — 종료 거래 이력 (페이징, exit_reason/pnl_pct/holding_days)
  - `GET /api/surge-trading/performance` — 누적 수익률 시계열 (days 파라미터)
  - `POST /api/surge-trading/execute` — 관리자 수동 매수 트리거 (X-Admin-Token 인증)
- **DB 마이그레이션**: `052_spec_ai_013_surge_portfolio.py` — `surge_portfolios`·`surge_trades` 테이블, 3개 인덱스, 초기 포트폴리오 레코드(id=1) 자동 생성
- **테스트 40개 추가** (`backend/tests/test_surge_trading.py`): 전체 960/960 PASS
  - AC-SURGE-TRADE-001~031 전체 충족 (매수/매도/API/격리 시나리오 포함)
- **프론트엔드** (`frontend/src/app/trading/page.tsx`): '급등 예측' 탭 추가, `SurgeTab` 인라인 컴포넌트, `frontend/src/lib/api.ts`·`types.ts` Surge 타입 5종·API 함수 4개 통합

### Added — SPEC-AI-012: 급등 징후 탐지 시스템 (2026-05-07)

**배경**: 기존 4개 사전 탐지기(조용한 매집·뉴스-주가 괴리·볼린저밴드 압축·섹터 후행)와 SPEC-AI-004(공시 미반영 갭)만으로는 단기 급등 가능성이 높은 3개 신호 영역(테마 뉴스 클러스터링·거래량-뉴스 복합·공시 유형별 역사적 급등 패턴)이 미포착 상태였음. 룰 기반 앙상블 스코어로 신호 우선순위화 시스템을 구현.

- **테마 뉴스 클러스터 탐지기** (`backend/app/services/surge_detector.py`):
  - 48시간 이내 동일 테마 키워드가 N건 이상 출현한 종목군을 자동 발굴 (`min_news_count` 설정값 경유)
  - 시총 필터·섹터-테마 매핑 적용, 중복 발굴 방지
- **거래량 z-score + 뉴스 복합 신호 탐지기** (`backend/app/services/surge_detector.py`):
  - 24시간 이내 거래량 z-score ≥ 임계값 AND 관련 뉴스 감성 점수 동시 충족 종목 포착
  - z-score 기준값(`volume_zscore_threshold`)과 히스토리 기간(`lookback_days`) 모두 설정 파일 경유
- **공시 유형별 역사적 급등률 탐지기** (`backend/app/services/surge_detector.py`):
  - SPEC-AI-004 FundSignal 데이터를 재활용해 공시 유형별 5일 후 상승 비율(historical surge rate) 산출
  - 24h 인메모리 캐시(`_surge_rate_cache`) 적용으로 DB 쿼리 최소화
  - `min_sample_size`(최소 표본) · `min_surge_rate`(최소 비율) 설정 기반 필터링
- **가중 앙상블 스코어링** (`backend/app/services/surge_detector.py`):
  - `surge_probability_score = 0.25×테마 + 0.30×거래량_뉴스 + 0.25×공시패턴 + 0.20×레거시`
  - 레거시 점수: 기존 4개 탐지기 트리거 수 / 4 (`min(1.0, n/4)`)
  - `min_score_for_signal` 임계값 미달 시 `FundSignal` 생성 미실행
- **surge_candidate 시그널 통합** (`backend/app/services/fund_manager.py`):
  - `_gather_surge_candidates()` — `generate_daily_briefing`의 `asyncio.gather`에서 병렬 호출
  - 5 거래일 이내 동일 종목 중복 시그널 방지 (UPDATE vs INSERT 분기)
  - `FundSignal.surge_metadata` (Text, nullable) 컬럼에 탐지기 조합 JSON 저장
- **신규 API 엔드포인트** (`backend/app/routers/fund_manager.py`):
  - `GET /fund/surge-backtest?days=30` — 방향성 적중률·평균 5일 수익률·탐지기 조합별 통계 반환
- **설정 외부화** (`backend/app/surge_config/surge_detection.yaml`):
  - 모든 임계값(z-score, 테마 키워드 수, 공시 급등률, 앙상블 가중치 등) YAML 설정 경유
  - `SurgeDetectionConfig` Pydantic v2 모델로 타입 안전 로딩 (`model_validator` 가중치 합 검증)
- **DB 마이그레이션**: `051_spec_ai_012_surge_signal.py` — `fund_signals.surge_metadata` Text nullable 컬럼 추가
- **테스트 22개 추가** (`test_surge_detector.py`, `test_surge_backtest.py`): 전체 920/920 PASS
  - AC-SURGE-001 ~ 007 모두 충족
  - 5-day 중복 방지 UPDATE/INSERT 분기 테스트(AC-SURGE-005) 포함

### Fixed — AI 펀드매니저 상승장 과매수 차단 완화 및 프롬프트 개선 (2026-05-06)

**배경**: 한국증시 상승장에서 Stochastic >80 + 이격도 >103% 종목(과매수 상태)이 기술적 승수 0.5를 적용받아 AI confidence가 절반으로 낮아지고 실행 임계값(0.50)에 미달 처리됨. 상승장에서 과매수는 정상 상태임에도 매수 신호가 전혀 생성되지 않는 문제 해결.

- **`_get_technical_multiplier()` 승수 조정** (`backend/app/services/fund_manager.py`):
  - 이중 과매수(Stochastic >80 AND 이격도 >103%): `0.5` → `0.75` (50% 억제 → 25% 억제)
  - 단일 과매수(둘 중 하나): `0.7` → `0.88` (30% 억제 → 12% 억제)
  - 변경 후 AI confidence ≥ 0.67부터 과매수 상태에서도 매수 가능 (기존: 사실상 불가)
- **AI 프롬프트 과매수 판단 기준 개선** (`backend/app/services/fund_manager.py`):
  - 기존: "RSI 과매수 + 볼린저 상단 돌파 = 조정 임박 가능성" → 강한 상승 추세에서도 보수적 판단 유도
  - 변경: 추세 지속 여부 중심 판단, 수급·뉴스 뒷받침 시 과매수 상태도 buy 가능
  - `0.55 미만이면 반드시 hold` 강제 지시 제거 (코드 임계값과 이중 필터링 방지)
- **효과**: 서버 메모리 MemoryMax=700M 적용(systemd OOM kill 방지)과 함께 상승장 대응력 개선

### Added — SPEC-VIP-REBAL-001: VIP 포트폴리오 비중 미러링 리밸런싱 (2026-04-30)

**배경**: VIP 추종 매매에서 2차 매수 시 가용 현금 부족으로 매수를 단순 포기하던 문제 해결. VIP가 이미 종료한 종목이 포트폴리오에 남아 자본이 묶이는 상황을 해소.

- **`_exit_vip_closed_positions()` 신규 함수** (`vip_follow_trading.py`):
  - 가장 최근 공시가 `reduce`/`below5`인 종목의 오픈 포지션 전량 청산
  - `exit_reason="vip_rebalance_exit"`, 종목 단위 그룹 청산, `stock_id` 오름차순 처리
- **`_get_vip_target_weights()` 신규 함수** (`vip_follow_trading.py`):
  - VIP `stake_pct` 비율 기반 목표 비중 산출 (`Σ ≈ 1.0`)
  - `None` stake_pct → 다른 종목 평균값 대체; 전부 None → 1/N 균등 배분
- **`_rebalance_to_vip_weights()` 신규 함수** (`vip_follow_trading.py`):
  - `|current_weight - target_weight| > 0.03` 초과 시만 리밸런싱 실행
  - 매도(trim) 우선 처리 후 매수, 단일 포지션 보호(1개 이하 시 스킵)
- **`_try_rebalance_for_second_buy()` 신규 함수** (`vip_follow_trading.py`):
  - `asyncio.Lock` 동시 실행 방지, 종료포지션청산 → 비중조정 → 현금 충족 여부 반환
- **`check_second_buy_pending()` 확장** (`vip_follow_trading.py`):
  - 현금 부족 시 `VIP_REBALANCE_ENABLED` 확인 후 리밸런싱 재시도
  - 성공 시 `_execute_vip_buy()` 재호출로 2차 매수 실현
- **신규 환경변수**: `VIP_REBALANCE_ENABLED` (기본값 `true`), `VIP_REBALANCE_THRESHOLD` (기본값 `0.03`)
- **테스트 10개 추가** (`test_vip_follow_trading.py`): 전체 23/23 PASS

### Improved — 거래 페이지 UI 용어 및 표시 개선 (2026-04-27)

- **"잔여 현금" → "예수금" 레이블 변경** (`trading/page.tsx`):
  - VIPTab, KS200Tab, PaperTradingTab 세 탭 모두 반영
  - 증권 업계 표준 용어 "예수금"으로 통일
- **현금 카드에 주식평가금액 서브라인 추가**:
  - 예수금 카드 하단에 `주식평가금액 {금액}원` 표시
  - "투자 중" 카드: 포지션 수 → 포지션 평가금액으로 변경

### Fixed — APScheduler DB JobStore 적용 및 yfinance 로그 스팸 억제 (2026-04-27)

- **APScheduler SQLAlchemyJobStore 적용** (`scheduler.py`):
  - 기존 MemoryJobStore는 OOM SIGKILL 재시작 시 스케줄러 상태 소멸 → 당일 브리핑 누락
  - `apscheduler_jobs` PostgreSQL 테이블에 잡 상태 영속화 (37개 잡 등록 확인)
  - OOM 재시작 후 `misfire_grace_time(30s)` 내 누락 잡 자동 재실행
  - 근본 원인: OCI E2.1.Micro 1GB VM 메모리 402MB 도달 → SIGKILL (Apr 24, Apr 25 각 1회)
- **yfinance 로그 스팸 완전 차단** (`main.py`):
  - `ZC=F, ALI=F, ZS=F, ZW=F` 등 미상장 선물 티커 "Failed downloads" 오류가 10분마다 10건씩 출력
  - 하루 144회 ERROR 로그가 journald를 덮어써 OOM 발생 시각 추적 불가
  - `logging.getLogger("yfinance").setLevel(logging.CRITICAL)` 적용으로 완전 차단
  - 검증: 서버 배포 후 10분 경과, yfinance 로그 0건 확인

### Added — SPEC-AI-011: 지배구조 인식 기반 종목선택 개선 (2026-04-22)

**배경**: AI 펀드매니저가 HD조선 관련 뉴스를 처리할 때 실제 수혜 종목(HD한국조선해양)이 아닌 지주사(HD현대)를 선택하는 문제 발생. 지주사는 운영 실체가 없어 뉴스 수혜가 자회사로 귀속됨.

- **`StockRelation` 지배구조 타입 추가** (`stock_relation.py`):
  - `holding_company` / `subsidiary` relation_type 지원
  - 방향 규약: `target_stock_id = 지주사`, `source_stock_id = 자회사`
- **Alembic 마이그레이션 050** (`050_spec_ai_011_holding_company.py`):
  - `idx_stock_relations_source_type` 복합 인덱스 생성 `(source_stock_id, relation_type)`
  - HD현대(267250) → 4개 자회사 시드 데이터: HD한국조선해양(009540), HD현대오일뱅크(329180), 현대일렉트릭(010620), HD현대미포(010140)
- **`relation_propagator.py` 지배구조 관계 전파 차단**:
  - `holding_company` / `subsidiary` 타입은 뉴스 감성 전파 대상에서 제외
  - 자회사 확장은 `fund_manager.py`에서 별도 처리
- **`fund_manager.py` 자회사 후보 확장 로직** (3개 헬퍼 함수 추가):
  - `_is_holding_company(db, stock_id)`: 지주사 여부 판별 (인메모리 캐시 지원)
  - `_get_subsidiaries(db, holding_ids)`: 지주사 → 자회사 ID 매핑
  - `_expand_candidates_with_subsidiaries(db, candidates)`: 지주사 후보 발견 시 자회사를 후보 풀에 자동 추가
  - `generate_daily_briefing` 파이프라인에서 `[:10]` cap 이전에 확장 수행
- **브리핑 프롬프트 지주사 경고 주입** (`fund_manager.py`):
  - 지주사 후보 존재 시 `## 지배구조 주의사항` 섹션을 프롬프트에 주입
  - "지주사는 운영 자회사 대신 검토하세요" 맥락 제공
- **`factor_scoring.py` 지주사 할인 팩터** (`build_factor_scores_json`):
  - 지주사 종목의 `composite_score`에 -5 할인 적용 (floor 0)
  - `factor_scores` JSON에 `holding_company_discount: -5` 필드 추가
  - `stock_id` / `db` 파라미터 추가 (기본값 `None`, 하위 호환성 유지)
- **단위 테스트 20개 추가** (`test_spec_ai_011_holding_company.py`):
  - `TestIsHoldingCompany` (5), `TestGetSubsidiaries` (4), `TestExpandCandidatesWithSubsidiaries` (5), `TestBuildFactorScoresJsonHoldingDiscount` (5), `TestRelationPropagatorGuard` (1)
  - 전체 테스트 888개 통과

### Fixed — APScheduler misfire_grace_time 및 종토방 PendingRollbackError 수정 (2026-04-21)

- **APScheduler `misfire_grace_time` 1초 → 30초로 증가** (`scheduler.py`):
  - `vip_follow_trading` 2차 매수 체크가 KST 09:00(UTC 00:00) 장 시작 시 ~1.1초 동기 블로킹 발생
  - 기본값(1초) 초과로 동시 등록된 5개 잡이 매일 자정 skip되던 문제 해결
- **종토방 `save_forum_posts` TOCTOU 경쟁 조건 제거** (`forum_crawler.py`):
  - SELECT-then-INSERT 패턴 → `INSERT ON CONFLICT DO NOTHING` (PostgreSQL dialect) 로 교체
  - `uq_forum_post` 제약조건 기반 원자적 삽입으로 `UniqueViolation` → `PendingRollbackError` 서비스 장애 완전 차단

### Improved — 모의투자 비교 대시보드 개선 (2026-04-15)

- **AI 펀드매니저 총 수익 계산 개선**: `get_portfolio_stats` async 전환, 오픈 포지션 실시간 현재가 반영
  - `_fetch_prices_batch` 배치 조회로 오픈 포지션 평가금액 산출 (현재가 없으면 매수가 fallback)
  - `GET /api/paper-trading/stats` 응답의 `total_return_pct`, `total_pnl`이 미실현 손익 포함
- **모의투자 개요 API 병렬 최적화**: `GET /api/trading/overview` — 3개 모델 stats를 `asyncio.gather`로 동시 조회
- **비교탭 경쟁 대시보드 UI**: 순위(🥇🥈🥉) + 상대 비율 바 + 컬럼 칸반 포지션 카드 + 트레이드 피드 레이아웃
  - 포지션 카드 색상: 수익률에 따라 red(이익)/blue(손실) 강도 자동 적용 (한국 주식 색상 관례)

### Added — SPEC-AI-008: 네이버 종토방 크롤러 및 이상 활성화 탐지 (2026-04-14)

- `StockForumPost`, `StockForumHourly` 모델 추가: 종토방 게시글 및 시간별 집계 데이터
- Alembic 마이그레이션 048: `stock_forum_posts`, `stock_forum_hourly` 테이블 생성
- `backend/app/services/forum_crawler.py`: httpx + BeautifulSoup 기반 종토방 크롤러 (30분 간격)
  - 감성 키워드 기반 bullish/bearish/neutral 분류 (AI 비용 절감)
  - `overheating_alert`: bullish_ratio > 80% 연속 2회 플래그
  - `volume_surge`: comment_volume이 7일 평균 3배 초과 플래그
- 스케줄러 `forum_crawl` 잡 등록 (30분 주기)
- 관련 버그 수정: circuit_breaker 임포트 오류, 네이버 HTML 컬럼 순서 오류

### Added — SPEC-AI-009: 증권사 컨센서스 목표주가 집계 및 fund_manager 통합 (2026-04-14)

- `_gather_securities_consensus()` 함수 추가: 90일 윈도우 목표주가 집계
  - 평균/중앙값 목표가, 최저/최고가, 프리미엄 비율 계산
  - 매수/보유/매도 의견 비율 통계
  - `consensus_signal` 생성: strong_buy / buy / neutral / caution / insufficient
  - 목표주가 추세: 최근 30일 vs 31~90일 비교
- `analyze_stock()` AI 프롬프트에 "## 9-1. 증권사 컨센서스" 섹션 추가
- 기존 `SecuritiesReport` 테이블만 활용 (신규 DB 테이블 불필요)

### Added — SPEC-AI-010: fund_manager 감성 분석 통합 (종토방 + 증권사 컨센서스) (2026-04-14)

- `_gather_forum_sentiment()` 함수 추가: 종토방 역발상 지표 lazy import로 미배포 시 graceful 처리
- `analyze_stock()` 프롬프트 확장
  - "## 1-2. 종토방 감성 (역발상 지표)" 섹션 추가
  - overheating_alert 발생 시: "※ 종토방이 과열 상태입니다. 개인투자자 쏠림에 의한 고점 가능성을 고려하세요"
  - volume_surge 발생 시: "※ 종토방 댓글 급증 감지: 시장 관심도 급등. 공시/뉴스와 교차 확인 필요"
  - "## 9-1. 증권사 컨센서스" 섹션 통합 (SPEC-AI-009)
- `macro_news_crawler.py`: 7개 거시경제 카테고리 RSS 크롤러 추가
  - 주요 카테고리: Fed 정책, 인플레이션, 반도체, 한국 수출, 유가, 환율, 금리 추이

### Fixed — SPEC-AI-007 사후 수정: CONFIDENCE_FLOOR 버그 및 신뢰도 구간 경계값 정렬 (2026-04-13)

- `fund_manager.py` `_CONFIDENCE_FLOOR` 오설정 수정: `MIN_ACTION_CONFIDENCE`(0.55)와 동일하게 설정되어 market_context 패널티(-0.10/-0.15) 및 CoT 패널티(-0.10)가 무력화되던 버그 해결
  - 변경: floor = `MIN_ACTION_CONFIDENCE` → `MIN_ACTION_CONFIDENCE - 0.05` (0.50)
  - 효과: 시장 리스크 시그널이 실제로 거래를 막을 수 있게 됨
- `signal_verifier.py` 신뢰도 구간(confidence_buckets) medium 하한선 조정: 0.40 → 0.55
  - 기존: 0.40~0.70 범위로 설정 → 0.40~0.54 무효 시그널이 "medium" 버킷에 혼재
  - 개선: `MIN_ACTION_CONFIDENCE`(0.55)를 기준으로 통일 → `get_accuracy_stats`와 `calibrate_confidence` 구간 일치
- `test_signal_verifier.py` medium 구간 테스트 데이터 갱신: confidence 0.5 → 0.65

### Added — SPEC-AI-007: Confidence 임계값 통일 및 모델별 적중률 분리 (2026-04-13)

**배경**: gemini 모델이 실제보다 낮은 적중률을 참조하여 과도한 hold 시그널을 생성하는 자기강화 루프 발생. confidence 임계값이 프롬프트(0.7), 코드 가드(0.45), 거래 실행(0.40) 3개 레이어에 걸쳐 불일치.

- `signal_verifier.py` `get_accuracy_stats()` 모델 필터 추가
  - `ai_model: str | None = None` 파라미터 신설
  - ai_model 지정 시 해당 모델의 시그널만 집계 → 타 모델 데이터 오염 차단
  - 최소 샘플 가드 추가: 검증 데이터가 5건 미만이면 `low_sample_warning` 반환
- `fund_manager.py` 임계값 상수 통일
  - 모듈 레벨 상수 `MIN_ACTION_CONFIDENCE: float = 0.55` 선언
  - 기존 로컬 상수 `_MIN_ACTION_CONFIDENCE = 0.45` 제거 및 통합
  - AI 프롬프트 임계값 지시문 수정: "0.7 이상" → "0.55 이상"
  - `get_accuracy_stats()` 호출 시 `ai_model=settings.GEMINI_MODEL` 전달
  - `low_sample_warning` 수신 시 accuracy_text에 데이터 부족 경고 포함
- `paper_trading.py` 거래 실행 임계값 통일
  - `MIN_ACTION_CONFIDENCE` import 추가
  - 하드코딩된 `0.4` → `MIN_ACTION_CONFIDENCE - 0.05` (0.50)으로 변경

### Performance — 모의투자 포트폴리오 조회 속도 개선 (2026-04-09)

- `_fetch_prices_batch()` 추가: Naver 배치 API(`SERVICE_ITEM`) 사용 — 종목 N개를 1회 요청으로 조회
  - 기존: N개 종목 → `Semaphore(5)` 제약으로 `ceil(N/5)` 순차 배치 (최대 10~20초)
  - 개선: N개 종목 → 배치 API 1회 호출 (1~2초), 배치 실패 시 개별 조회 폴백
- `_fetch_price()` 개선: 30초 인메모리 캐시 추가, timeout 10s → 3s 단축
- `get_vip_portfolio_stats`: Stock N+1 쿼리 → `IN` 쿼리 1회로 통합
- `GET /api/vip-trading/positions`: Stock + VIPDisclosure N+1 → `IN` 쿼리 2회로 통합
- `GET /api/paper-trading/positions`: Stock N+1 → `IN` 쿼리 1회로 통합

### Added — SPEC-FOLLOW-002: 증권사 리포트 수집 및 키워드 알림 확장

- `SecuritiesReport` 모델 추가: 네이버 리서치 종목분석 리포트 저장 테이블
- Alembic 마이그레이션 041: `securities_reports` 테이블 생성 (url UNIQUE, stock_id FK)
- `securities_report_crawler.py`: 네이버 리서치 크롤러 (서킷 브레이커 "naver_research", 30분 간격)
- `keyword_matcher.py` 확장: 리포트 키워드 매칭 루프 추가, type_label 3원 분기
- `scheduler.py` 확장: `_run_securities_report_crawl` 잡 등록
- 테스트 2종 추가: `test_securities_report_crawler.py`, `test_keyword_matcher_report.py`

### 구현 비고 (SPEC-FOLLOW-002)

- PDF 본문 수집 제외 (REQ-FOLLOW-002-N3 준수)
- 서킷 브레이커 "naver_research" 키 — 동적 생성으로 circuit_breaker.py 수정 불필요
- `company_name` 컬럼: String(200) — SPEC 7.1 정합

### Added (SPEC-FOLLOW-001: 기업 팔로잉 시스템 - 완료)

- **팔로잉 기능**: `backend/app/models/following.py` - StockFollowing, StockKeyword, KeywordNotification 모델 추가
  - StockFollowing: 사용자-종목 팔로잉 관계
  - StockKeyword: 카테고리별 키워드 (product, competitor, upstream, market, custom)
  - KeywordNotification: 알림 히스토리
- **키워드 생성 서비스**: `backend/app/services/keyword_generator.py` - AI 기반 자동 키워드 생성
  - 4가지 카테고리에서 핵심 키워드 추출
  - Gemini + Z.AI 다중 프로바이더 지원
  - 생성된 키워드의 수동 편집 가능
- **키워드 매칭 및 알림**: `backend/app/services/keyword_matcher.py`
  - 뉴스/공시 제목+본문에서 사용자 키워드 매칭
  - 중복 알림 방지
  - 매칭 결과 DB 기록
- **텔레그램 통합**: `backend/app/services/telegram_service.py`
  - Telegram Bot API를 통한 실시간 알림 발송
  - 채팅 ID 기반 사용자 연동
  - HTML 포맷 메시지 지원
- **팔로잉 라우터**: `backend/app/routers/following.py` - 12개 엔드포인트
  - 종목 팔로잉 CRUD: POST/DELETE/GET `/api/following/stocks`
  - 키워드 관리: GET/POST/DELETE `/api/following/stocks/{code}/keywords`
  - AI 키워드 생성: POST `/api/following/stocks/{code}/keywords/ai-generate`
  - 텔레그램 연동: POST/GET/DELETE `/api/following/telegram/*`
  - 알림 히스토리: GET `/api/following/notifications`
- **사용자 모델 확장**: `backend/app/models/user.py`
  - telegram_chat_id 컬럼 추가 - 텔레그램 연동 시 저장
- **DB 마이그레이션**: `backend/alembic/versions/040_spec_follow_001_following.py`
  - stock_followings 테이블 (user_id, stock_id, UNIQUE 제약)
  - stock_keywords 테이블 (카테고리, 소스 추적)
  - keyword_notifications 테이블 (알림 히스토리, 중복 방지)
  - users.telegram_chat_id 컬럼
- **스케줄러 통합**: `backend/app/services/scheduler.py`
  - 10분 간격 키워드 매칭 작업 추가
  - 신규 뉴스/공시 수집 직후 실행
- **설정**: `backend/app/config.py`
  - TELEGRAM_BOT_TOKEN 환경변수 추가
- **프론트엔드 페이지**:
  - `/following` - 팔로잉 종목 목록 및 텔레그램 연동 상태
  - `/following/[stock_code]` - 키워드 관리 및 알림 히스토리
  - 네비게이션 메뉴에 "팔로잉" 항목 추가
- **테스트 커버리지**:
  - `backend/tests/test_following.py` - 13개 엔드포인트 테스트
  - `backend/tests/test_keyword_generator.py` - AI 키워드 생성 테스트
  - `backend/tests/test_keyword_matcher.py` - 키워드 매칭 로직 테스트
  - `backend/tests/test_telegram_service.py` - 텔레그램 서비스 테스트

### 구현 비고 (SPEC-FOLLOW-001)

- 텔레그램 연동 코드는 Redis가 아닌 in-memory dict 사용 (MVP 범위, 재시작 시 초기화됨)
- Telegram webhook X-Telegram-Bot-Api-Secret-Token 검증 미구현 (단계적 개선 예정)
- 키워드 매칭 로깅 개선 필요 (현재 except 블록에 로깅 누락)

### Deployment Notes (SPEC-FOLLOW-001)

- DB 마이그레이션 필요: `alembic upgrade head` (revision 040)
- 신규 환경변수: `TELEGRAM_BOT_TOKEN` (BotFather에서 발급)
- 하위 호환성: 기존 API 엔드포인트 변경 없음 (신규 라우터 추가만)
- 스케줄러 자동 등록: 앱 시작 시 keyword_matching 작업 자동으로 시작됨

### Added (SPEC-AI-004: 공시 기반 미반영 호재 탐지 - 진행 중)

- **공시 충격 스코어러**: `disclosure_impact_scorer.py` - 공시 유형/규모별 예상 시장 충격 자동 계산
- **DB 마이그레이션**: `036_spec_ai_004_disclosure_impact.py` - Disclosure 모델에 충격 스코어, 반영도, 미반영 갭 필드 추가
- **AI 모델 추적**: `035_add_ai_model_to_briefing_signal.py` - BriefingSignal에 사용된 AI 모델명 기록

### Added (사용자 인증 시스템)

- **User 모델**: `backend/app/models/user.py` - 이메일 인증 기반 회원 관리
- **인증 라우터**: `backend/app/routers/auth.py` - 회원가입, 로그인, 토큰 갱신 엔드포인트
- **사용자 라우터**: `backend/app/routers/user.py` - 프로필 조회/수정, 관심종목 관리
- **이메일 서비스**: `backend/app/services/email_service.py` - 인증 토큰 발송
- **DB 마이그레이션**: `033_add_user_auth_tables.py`, `034_change_verification_code_to_token.py`
- **Frontend 인증**: 로그인/회원가입/이메일 인증 페이지 + AuthProvider 컴포넌트

### Added (푸시 알림)

- **푸시 서비스**: `backend/app/services/push_service.py` - Web Push 알림 발송
- **푸시 라우터**: `backend/app/routers/push.py` - 구독 관리 엔드포인트
- **Service Worker**: `frontend/public/sw.js` - 브라우저 푸시 수신

### Changed (기존 기능 개선)

- **AI 클라이언트**: `ai_client.py` 리팩토링 - 모델 선택 로직 개선
- **채팅 페이지**: 대화형 분석 UI 대폭 개선 (`frontend/src/app/chat/page.tsx`)
- **메인 페이지/워치리스트/펀드/뉴스 페이지**: 인증 연동 및 UI 개선
- **네이버 파이낸스**: `naver_finance.py` 크롤링 안정성 강화

### Infrastructure

- **MoAI ADK**: v2.8.0 -> v2.9.1 업데이트 (hook 스크립트, skill, rule 갱신)

### Added (SPEC-AI-003: 선행 매수 신호 탐지)

- **선행 지표 탐지 엔진**: 4개 독립 신호 탐지 함수로 가격 상승 이전 시점 포착
  - `_detect_quiet_accumulation()`: 외국인+기관 동시 순매수 + 낮은 가격 변동률 감지
  - `_detect_news_price_divergence()`: 긍정 뉴스 발행 후 미반영 가격 괴리 감지
  - `_detect_bb_compression()`: 볼린저 밴드 수축 + 저거래량 에너지 축적 감지
  - `_detect_sector_laggards()`: 모멘텀 섹터 내 낙오 종목 평균 회귀 기회 감지
- **통합 랭킹 시스템**: 4개 지표 복합 신호 가중 점수 산정, 중복 감지된 종목 우선 배치
- **AI 프롬프트 통합**: `leading_signals` 메타데이터 필드로 신호 타입과 강도 전달
- **asyncio.Semaphore(5)** 동시성 제어: API 호출 병렬화로 60초 이내 처리 완료
- **24개 특성 테스트**: 각 신호 탐지 함수별 단위 테스트, 통합 테스트, 에러 처리 시나리오 검증

### Added (배포/점검 중 시스템 점검 페이지 및 미들웨어)

- 시스템 점검 페이지 (`/maintenance`): "시스템 점검 중" 안내, 10초 자동 재시도, 백엔드 복구 시 자동 홈 이동 (`frontend/src/app/maintenance/page.tsx`)
- Next.js 미들웨어 (`frontend/src/middleware.ts`): 페이지 접근 시 헬스체크 수행, 백엔드 다운 감지 시 `/maintenance`로 리디렉션, Edge Runtime 호환 AbortController 적용
- `fetchWithRetry` 강화 (`frontend/src/lib/api.ts`): 최종 502/503 또는 네트워크 오류 발생 시 `/maintenance`로 자동 이동

### Fixed (뉴스 새로고침 안정성)

- 뉴스 새로고침 후 서버 응답 없음 수정 (`backend/app/routers/news.py`): `_deduplicate_existing` 및 `_backfill_sentiment`을 `asyncio.to_thread()`로 실행하여 이벤트 루프 블로킹 해소, `_backfill_translate`를 최근 200건 / 회당 최대 20건으로 제한
- 뉴스 갱신 안 됨 수정 (`backend/app/services/news_crawler.py`): `del` 이후 참조된 변수(`all_raw_articles`, `existing_urls`)에 의한 NameError 수정

### Deployment Notes (점검 페이지 / 뉴스 새로고침 수정)

- DB 마이그레이션 없음
- 신규 환경변수 없음
- 하위 호환성: 기존 API 엔드포인트 변경 없음

---

### Fixed (원자재 시세 + 뉴스 정확도)

#### 원자재 실시간 가격 수집 (`commodity_service.py`)
- `_download_with_fallback()` 추가: 장 중에는 1분봉(`period="1d", interval="1m"`) 15분 지연 실시간 가격, 장 외 또는 데이터 없을 때는 5일 일봉(`period="5d"`) 종가로 자동 fallback
- 앱 시작 시(lifespan) 시드 완료 직후 `fetch_commodity_prices()` 즉시 실행 — 스케줄러 첫 실행 전 경합 조건 방지 (`main.py`)

#### 석탄 심볼 표준화 (`seed/commodities.py`, `migration 024`)
- 석탄 심볼 `MTF=F` / `BTU` → `COAL` (Range Global Coal ETF 프록시)로 표준화
- `024_ensure_coal_symbol.py` 마이그레이션: BTU와 COAL이 동시 존재하는 unique violation 방지 — BTU 관련 레코드 삭제 후 COAL 보장
- ETF 프록시 사용 이유: Newcastle Coal 선물(MTF=F)은 yfinance 미지원, BTU도 거래 중단으로 `COAL` ETF를 대용

#### 원자재 뉴스 오탐 수정 (`commodity_news_service.py`)
- 키워드 매칭 범위를 기사 **제목만**으로 제한 (기존: 제목 + 본문 500자)
- `귀금속` 키워드를 은(SI=F)의 extra keywords에서 제거 — 금 기사에 은 뱃지가 함께 붙는 오탐 방지

### Deployment Notes

- DB 마이그레이션 필요: `alembic upgrade head` (024_ensure_coal_symbol)
- 신규 환경변수 없음
- 하위 호환성: 기존 API 엔드포인트 변경 없음

---

### Added (SPEC-RELATION-001: 종목 간 관계 기반 간접 영향 뉴스 전파)

- **stock_relations 테이블**: AI 추론 종목/섹터 간 방향성 관계 저장 (공급망, 경쟁사, 장비, 소재, 고객사)
- **stock_relation_service.py**: Gemini AI 기반 섹터 간/섹터 내 관계 자동 추론 (하드코딩 없음)
- **relation_propagator.py**: 관계 그래프 탐색 기반 간접 영향 뉴스 전파 엔진 (감성 역전 포함)
- **간접 뉴스 배지**: "↗ 간접호재" / "↘ 간접악재" 프론트엔드 배지 표시
- **관계 API**: GET/POST/DELETE /api/stocks/relations 엔드포인트
- **DB 마이그레이션**: migration 019 (stock_relations 신규), 020 (news_stock_relations 컬럼 3개 추가)

### Deployment Notes (SPEC-RELATION-001)

- DB 마이그레이션 필요: `alembic upgrade head` (019, 020)
- 앱 재시작 시 AI 관계 추론 자동 실행 (stock_relations 비어있을 때)
- 하위 호환성: 기존 뉴스 크롤링 파이프라인 변경 없음

---

### Added (SPEC-NEWS-001: 뉴스-가격 반응 추적 시스템)

- **NewsPriceImpact 모델**: 뉴스 발행 시점의 주가 스냅샷 및 T+1D/T+5D 가격 변화율 추적
- **가격 스냅샷 자동 캡처**: 뉴스 수집 완료 직후 관련 종목의 현재가를 자동으로 저장
- **자동 백필 스케줄러**: 매일 18:30 KST에 1일/5일 경과 레코드의 수익률 자동 계산
- **뉴스 반응 통계 API**: `GET /api/stocks/{id}/news-impact-stats` — 30일 평균 수익률, 승률 제공
- **뉴스 impact API**: `GET /api/news/{id}/impact` — 특정 뉴스의 가격 반응 데이터 조회
- **AI 브리핑 강화**: 데일리 브리핑 프롬프트에 종목별 뉴스-가격 반응 통계 데이터 통합
- **종목 상세 UI**: 뉴스 반응 통계 카드 (평균 1일/5일 수익률, 승률, 데이터 건수) 추가
- **DB 마이그레이션**: migration 016 — news_price_impact 테이블 (3개 인덱스 포함)
- **90일 자동 정리**: 매일 03:00 KST에 90일 초과 impact 레코드 자동 삭제

### 구현 비고

- `relation_id`는 현재 None으로 전달됨 (대량 삽입 후 ID 역추적은 향후 개선 예정)
- FK 전략: `news_id`는 ON DELETE SET NULL, `stock_id`는 ON DELETE CASCADE
- 신규 환경변수 없음 (기존 `naver_finance.fetch_stock_fundamentals_batch()` 재사용)

### Deployment Notes

- DB 마이그레이션 필요: `alembic upgrade head` (016_add_news_price_impact_table)
- 신규 환경변수 없음
- 하위 호환성: 기존 API 엔드포인트 변경 없음 (신규 엔드포인트 추가만)
