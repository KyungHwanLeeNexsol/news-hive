# SPEC-AI-015 Compact Reference

**Title**: 시장 레짐 적응형 전략 (Market Regime Adaptive Strategy)
**Status**: draft | **Priority**: High | **Dependencies**: SPEC-AI-007, SPEC-AI-003

---

## Requirements (REQ Lines)

### Foundation
- **REQ-AI-015-001 [NEW]**: `market_regimes` 테이블 생성 (date UNIQUE, regime ENUM, kospi_5d_return, kospi_20d_ma_position, volatility_index NULLABLE, confidence_score, timestamps)
- **REQ-AI-015-002 [NEW]**: 룰 기반 분류 — BULL: 5d_ret≥+1.5% AND above 20d MA / BEAR: 5d_ret≤-1.5% OR 20d MA -2% 미만 / 그 외 SIDEWAYS
- **REQ-AI-015-003 [NEW]**: 레짐별 RegimeParams 매핑 (BEAR/SIDEWAYS/BULL):
  - `min_action_confidence`: 0.65 / 0.55 / 0.48
  - `max_position_pct_high`: 0.10 / 0.15 / 0.20
  - `target_pct_max`: 0.15 / 0.25 / 0.30
  - `stop_loss_pct_default`: 0.04 / 0.05 / 0.07
  - `max_daily_trades`: 2 / 5 / 7
- **REQ-AI-015-004 [NEW]**: `market_regime_service.py` 공개 API — classify_market_regime, get_or_create_today_regime, get_regime_params, get_recent_regimes
- **REQ-AI-015-005 [NEW/EXTEND]**: KOSPI 20일 MA 조회 (naver_finance), 실패 시 position=0.0 + confidence≤0.4

### Integration — fund_manager.py
- **REQ-AI-015-010 [MODIFY]**: `analyze_stock()` 레짐 통합 — 동적 confidence floor + AI 프롬프트에 실제 수치 주입
- **REQ-AI-015-011 [MODIFY]**: `generate_daily_briefing()` 통합 — 즉시 적용 fix(168e4cb) 하드코딩 제거, 서비스 호출로 대체

### Integration — paper_trading.py
- **REQ-AI-015-020 [MODIFY]**: `_position_pct_by_confidence(conf, db)` 시그니처 확장 + 레짐 기반 동적 max
- **REQ-AI-015-021 [MODIFY]**: AI가 stop/target 미지정 시 레짐 디폴트 적용 (폴백)
- **REQ-AI-015-022 [MODIFY]**: `execute_signal_trade()` 일일 거래 한도 (BEAR=2, SIDEWAYS=5, BULL=7), 한도 초과 시 hold 다운그레이드

### Scheduling & API
- **REQ-AI-015-030 [MODIFY]**: 평일 09:00 KST 일별 잡 — briefing 이전 실행
- **REQ-AI-015-031 [NEW]**: `GET /fund/market-regime` — today + 7일 history JSON

### Non-Functional
- **REQ-AI-015-040 [HARD]**: Graceful Fallback — 데이터 부재 시 SIDEWAYS 디폴트, 시스템 무중단
- **REQ-AI-015-041 [HARD]**: 멱등성 — UNIQUE(date) + IntegrityError catch + SELECT 재시도
- **REQ-AI-015-042 [HARD]**: 후방 호환 — 기존 테스트 100% 통과
- **REQ-AI-015-043 [SHOULD]**: 레짐 조회 latency < 5ms (필요 시 lru_cache)

---

## Acceptance Criteria (Summary)

1. BULL 레짐 시 `analyze_stock()` confidence floor = 0.48 (코드 + 프롬프트 일치)
2. BEAR 레짐 시 confidence floor = 0.65, 일일 거래 ≤ 2건
3. SIDEWAYS 디폴트 시 즉시 적용 fix 이전 동작과 거의 동일
4. 데이터 부재 시 SIDEWAYS in-memory 디폴트, DB INSERT 없음
5. `GET /fund/market-regime` 200 OK + today + history 7일
6. 같은 날 두 번째 호출 시 멱등 (UNIQUE 위반 catch + SELECT 재시도)
7. 포지션 사이즈 BULL conf=0.85 → 20%, BEAR conf=0.85 → 10%
8. AI stop/target 미지정 시 레짐 디폴트, 명시 시 AI 응답 우선
9. 기존 회귀 테스트 zero 실패
10. 7영업일 후 분포가 KOSPI 실제 추세와 정합

---

## Affected Files

### NEW
- `backend/app/models/market_regime.py`
- `backend/app/services/market_regime_service.py`
- `backend/alembic/versions/XXX_spec_ai_015_market_regime.py`
- `backend/tests/services/test_market_regime_service.py`
- `backend/tests/api/test_fund_market_regime.py`

### MODIFY
- `backend/app/services/fund_manager.py` (analyze_stock, generate_daily_briefing)
- `backend/app/services/paper_trading.py` (_position_pct_by_confidence, execute_signal_trade, defaults)
- `backend/app/routers/fund.py` (new endpoint)
- `backend/app/services/scheduler.py` (09:00 KST job)
- `backend/app/models/__init__.py` (model registration)

---

## Exclusions (What NOT to Build)

1. 실시간 인트라데이 레짐 갱신 (일별만)
2. ML 기반 레짐 검출 (룰 기반만)
3. 프런트엔드 UI 변경 (API 노출만)
4. 별도 설정 파일 외부화 (코드 상수)
5. VIX / 외부 변동성 지수 통합
6. 종목별/섹터별 레짐 (전체 시장 단일)
7. 백테스트 시뮬레이션 / 과거 백필
8. 레짐 전환 알림(notification)
9. 자동 임계값 튜닝 / A/B 테스트
10. 레짐 전환일에 보유 포지션의 stop/target 변경 (진입 당시 파라미터 유지)
