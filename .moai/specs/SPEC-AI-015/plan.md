# SPEC-AI-015 구현 계획 (plan.md)

## 0. 개요

본 계획은 SPEC-AI-015 (시장 레짐 적응형 전략) 의 구현 순서, 기술적 접근, 리스크, 마일스톤을 정의한다. 우선순위 기반으로 정리하며 시간 추정은 사용하지 않는다.

---

## 1. 기술적 접근 (Technical Approach)

### 1.1 아키텍처 개요

```
┌──────────────────────────────────────────────────────────────┐
│                  Daily 09:00 KST Scheduler                    │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
       ┌──────────────────────────────────────┐
       │  market_regime_service               │
       │  ─ classify_market_regime()          │
       │  ─ get_or_create_today_regime()      │◄── SectorMomentum.avg_return_5d
       │  ─ get_regime_params()               │◄── KOSPI 20d MA (naver_finance)
       │  ─ get_recent_regimes()              │
       └────────┬─────────────────────────────┘
                │ persist
                ▼
       ┌──────────────────────────────────────┐
       │  market_regimes (DB table)           │
       │  date UNIQUE, regime ENUM, ...       │
       └────────┬─────────────────────────────┘
                │ read
       ┌────────┴────────────────┬────────────────────┐
       ▼                          ▼                    ▼
  fund_manager.py          paper_trading.py     fund.py (router)
  ─ analyze_stock()        ─ position_pct       ─ GET /market-regime
  ─ generate_briefing()    ─ stop/target
                           ─ daily trade cap
```

### 1.2 핵심 설계 결정

#### D1. 레짐별 파라미터는 코드 내 dict 상수

대안 (외부 YAML, DB 테이블) 대비 코드 상수의 장점:
- 단일 source of truth, git diff 추적 용이
- ORM/마이그레이션 부담 없음
- 변경 시 코드 리뷰 + 테스트 회귀 자동 보장

향후 ML 자동 튜닝이 도입되면 그때 외부화하는 것으로 충분.

#### D2. 레짐 분류는 pure function + 영속화는 별도 단계

`classify_market_regime()` 은 입력 floats만 받아 (regime, confidence) 를 반환하는 pure function. DB 의존 없음 → 단위 테스트 용이.

`get_or_create_today_regime()` 이 분류 결과를 SQLAlchemy로 영속화.

#### D3. KOSPI 20일 MA — 1단계는 naver_finance 의존, 2단계는 캐시

1단계 (본 SPEC):
- `naver_finance.fetch_kospi_20d_ma() -> (current_close, ma_20d)` 신설
- 호출 실패/타임아웃 시 `(None, None)` 반환 → REQ-AI-015-040 fallback 발동

2단계 (별도 SPEC, 본 SPEC out-of-scope):
- KOSPI 일별 종가 시계열 테이블 신설
- 캐시 + offline 계산

#### D4. fund_manager.py / paper_trading.py 시그니처 변경 최소화

- `_position_pct_by_confidence(confidence)` → `_position_pct_by_confidence(confidence, db: Session)` 로 확장
- `analyze_stock()` 의 db 파라미터는 이미 존재 → 추가 인자 없음
- 폴백 디폴트 상수 (`MIN_ACTION_CONFIDENCE`, `MAX_POSITION_PCT`, `DEFAULT_TARGET_PCT`, `DEFAULT_STOP_LOSS_PCT`) 는 그대로 유지하여 graceful fallback 보장

#### D5. 멱등성 보장: UNIQUE constraint + ON CONFLICT 가드

- `market_regimes.date` UNIQUE
- `get_or_create_today_regime()` 내부에서 `SELECT WHERE date=today` 우선, 없으면 INSERT
- IntegrityError catch 시 재 SELECT (race condition 방어)

#### D6. 캐시 전략

- 요청 단위 캐시: FastAPI dependency 또는 contextvar
- 1차 구현은 단순 함수 내 로컬 캐시 없이 매 호출 SELECT (latency < 5ms 충분)
- 성능 이슈 발생 시에만 lru_cache(maxsize=1) 도입 (SR REQ-AI-015-043)

### 1.3 Brownfield 통합 전략

본 SPEC은 기존 코드를 수정하므로 DDD 모드 권장:

- **ANALYZE**: `fund_manager.py:2128~` (analyze_stock), `:2623~` (briefing), `paper_trading.py:124,133` 의 현재 동작 정밀 분석
- **PRESERVE**: 기존 테스트 회귀 검증, characterization test 보강 (특히 `_position_pct_by_confidence` 호출부)
- **IMPROVE**: 레짐 기반 오버라이드 도입 + 폴백 경로 검증

---

## 2. 마일스톤 (Priority-Based, No Time Estimates)

### M1 — Foundation Layer [Priority: High]

- M1.1 [NEW] `MarketRegimeEnum` 정의 (`market_regime_service.py` 헤더)
- M1.2 [NEW] `MarketRegime` SQLAlchemy 모델 (`models/market_regime.py`)
- M1.3 [NEW] Alembic migration 생성 (`alembic revision --autogenerate -m "spec_ai_015_market_regime"`)
- M1.4 [NEW] `models/__init__.py` 등록 + `app/main.py` import
- M1.5 [NEW] 단위 테스트: 모델 CRUD, UNIQUE constraint 검증

**Exit criteria**: `alembic upgrade head` 성공, 테이블 생성 확인, model 단위 테스트 통과

### M2 — Service Layer [Priority: High]

- M2.1 [NEW] `RegimeParams` dataclass + `REGIME_PARAMS_MAP` dict 상수
- M2.2 [NEW] `classify_market_regime()` pure function (REQ-AI-015-002)
- M2.3 [NEW] `get_regime_params()` (REQ-AI-015-003 매핑)
- M2.4 [EXTEND] `naver_finance.fetch_kospi_20d_ma()` 신설 또는 기존 함수 확장
- M2.5 [NEW] `get_or_create_today_regime(db)` 구현 (멱등성 + fallback)
- M2.6 [NEW] `get_recent_regimes(db, days=7)` 조회 함수
- M2.7 [NEW] 단위 테스트: 분류 알고리즘 경계조건, fallback, 멱등성, race 시뮬레이션

**Exit criteria**: 서비스 모듈 단독 테스트 100% 통과, 커버리지 ≥ 85%

### M3 — Integration Layer [Priority: High]

- M3.1 [MODIFY] `fund_manager.analyze_stock()` 레짐 통합 (REQ-AI-015-010)
  - 폴백 경로: 서비스 예외 시 기존 `MIN_ACTION_CONFIDENCE` 사용
  - 프롬프트에 실제 수치 주입
- M3.2 [MODIFY] `fund_manager.generate_daily_briefing()` 통합 (REQ-AI-015-011)
  - 즉시 적용 fix(168e4cb)의 하드코딩 텍스트 주입을 서비스 호출로 대체
- M3.3 [MODIFY] `paper_trading._position_pct_by_confidence()` 시그니처 확장 + 호출부 갱신
- M3.4 [MODIFY] `paper_trading.execute_signal_trade()` 일일 거래 한도 (REQ-AI-015-022)
- M3.5 [MODIFY] 디폴트 stop/target 레짐 기반 오버라이드 (REQ-AI-015-021)
- M3.6 [TEST] 통합 테스트: BULL/BEAR/SIDEWAYS 시나리오별 end-to-end

**Exit criteria**: 통합 테스트 통과, 기존 회귀 테스트 100% 통과

### M4 — Scheduler & API [Priority: Medium]

- M4.1 [MODIFY] 스케줄러에 09:00 KST 잡 등록 (briefing 의존성)
- M4.2 [NEW] `GET /fund/market-regime` 엔드포인트 (`fund.py`)
- M4.3 [NEW] API 테스트: 정상 응답, 데이터 부재 시 SIDEWAYS 응답
- M4.4 [DOCS] CHANGELOG 업데이트, API 문서 갱신

**Exit criteria**: 엔드포인트 200 OK, OpenAPI 스키마 자동 갱신, 스케줄러 잡 정상 등록

### M5 — Verification & Hardening [Priority: Medium]

- M5.1 [TEST] 전체 백엔드 테스트 회귀: `cd backend && uv run pytest tests/ --tb=short -q`
- M5.2 [TEST] LSP 검증: `uv run ruff check . && uv run mypy app/`
- M5.3 [TEST] 사이트 sanity: `uv run python -c "from app.main import app; print('OK')"`
- M5.4 [DEPLOY] OCI 배포 후 실 데이터로 첫 분류 결과 검증

**Exit criteria**: TRUST 5 quality gate 통과, 배포 후 첫 영업일 분류 결과 합리성 확인

---

## 3. 리스크 및 완화 (Risks and Mitigation)

| 리스크 | 영향 | 완화 |
|---|---|---|
| KOSPI 20일 MA 외부 API 실패 | 분류 신뢰도 저하 | REQ-AI-015-040 fallback (SIDEWAYS 디폴트) + confidence_score 0.4 이하 마킹 |
| 레짐 경계값(±1.5%) 부적절 | 잦은 레짐 전환 또는 늦은 전환 | 1차 구현 후 7일 이력 모니터링, 필요 시 별도 SPEC으로 임계값 조정 |
| 일일 거래 한도(BEAR=2)가 기존 거래 흐름 차단 | hold 시그널 폭증, 회귀 발생 | 통합 테스트에서 명시적으로 BEAR 시나리오 검증, 한도 도달 시 hold 다운그레이드 정상 동작 확인 |
| `_position_pct_by_confidence()` 시그니처 변경의 호출부 누락 | runtime TypeError | grep으로 모든 호출부 식별 → 일괄 수정, mypy 검증 |
| 마이그레이션 down_revision 충돌 | alembic 적용 실패 | 직전 head revision 확인 후 정확히 chain |
| AI가 레짐 텍스트와 코드 가드를 무시 (이전 SPEC-AI-007과 동일 양상) | 효과 미발현 | 프롬프트 텍스트와 코드 가드 임계값을 **동일 수치**로 일치, 단위 테스트로 검증 |
| 레짐 전환 시 기존 보유 포지션의 stop/target 변경 여부 모호 | 운용 일관성 저하 | **out-of-scope로 명시**: 본 SPEC은 신규 진입 시그널에만 새 파라미터 적용, 기존 포지션은 진입 당시 파라미터 유지 |

---

## 4. 데이터 마이그레이션 (Data Migration)

### 4.1 신규 테이블 생성

```python
# alembic/versions/XXX_spec_ai_015_market_regime.py
def upgrade():
    market_regime_enum = sa.Enum('BULL', 'BEAR', 'SIDEWAYS', name='market_regime_enum')
    market_regime_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'market_regimes',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('date', sa.Date, nullable=False, unique=True, index=True),
        sa.Column('regime', market_regime_enum, nullable=False),
        sa.Column('kospi_5d_return', sa.Float, nullable=False),
        sa.Column('kospi_20d_ma_position', sa.Float, nullable=False),
        sa.Column('volatility_index', sa.Float, nullable=True),
        sa.Column('confidence_score', sa.Float, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

def downgrade():
    op.drop_table('market_regimes')
    sa.Enum(name='market_regime_enum').drop(op.get_bind(), checkfirst=True)
```

### 4.2 백필 (Backfill) — Out of Scope

본 SPEC은 도입일 이후 데이터만 누적한다. 과거 레짐 시뮬레이션 백필은 별도 작업으로 분리.

---

## 5. 테스트 전략 (Test Strategy)

### 5.1 단위 테스트

`tests/services/test_market_regime_service.py`:

- `classify_market_regime()` — 9개 boundary 케이스 (BULL/BEAR/SIDEWAYS × 경계값 ±)
- `get_regime_params()` — 3개 enum 값 매핑 정확성
- `get_or_create_today_regime()` — 신규 INSERT, 중복 호출 멱등성, IntegrityError 시 SELECT fallback
- KOSPI 20d MA 조회 실패 시 SIDEWAYS 디폴트 + confidence ≤ 0.4

### 5.2 통합 테스트

`tests/services/test_fund_manager_regime.py`:

- BULL 시 `analyze_stock()` confidence floor = 0.48
- BEAR 시 confidence floor = 0.65
- SIDEWAYS 시 confidence floor = 0.55
- 레짐 서비스 예외 시 `MIN_ACTION_CONFIDENCE=0.50` 폴백

`tests/services/test_paper_trading_regime.py`:

- BULL conf=0.85 → position 20%
- BEAR conf=0.85 → position 10%
- BEAR 일일 3번째 매수 시그널 → hold 다운그레이드
- AI가 stop/target 미지정 → 레짐 디폴트 적용

### 5.3 API 테스트

`tests/api/test_fund_market_regime.py`:

- `GET /fund/market-regime` 200 OK + 스키마 검증
- 7일 history 길이 ≤ 7
- 데이터 부재 시 SIDEWAYS 디폴트 응답

### 5.4 회귀 검증

- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 100% 통과
- 기존 `test_fund_manager.py`, `test_paper_trading.py` 회귀 zero

---

## 6. 운영 고려사항 (Operational Notes)

### 6.1 배포 순서

1. DB migration 적용 (`alembic upgrade head`)
2. 백엔드 재시작 (systemctl restart newshive)
3. 첫 영업일 09:00 KST 분류 결과 확인 (`SELECT * FROM market_regimes ORDER BY date DESC LIMIT 1;`)
4. 7일 후 분포 검증 (BULL/BEAR/SIDEWAYS 비율이 KOSPI 실제 추세와 정합)

### 6.2 모니터링 포인트

- 일별 09:00 KST 잡 실행 로그 (`journalctl -u newshive -n 50 --no-pager | grep "market_regime"`)
- KOSPI 20d MA 조회 실패율 (fallback 발동 빈도)
- 레짐별 일일 거래 건수 분포

### 6.3 롤백 전략

- 본 SPEC은 모든 변경에 폴백 디폴트 상수 유지 → 레짐 서비스 비활성화 시에도 시스템 정상 동작
- 긴급 비활성화: `market_regime_service.get_or_create_today_regime()` 첫 줄에 `raise RuntimeError("disabled")` 삽입 → 자동으로 폴백 디폴트 사용
- 영구 롤백: alembic downgrade -1 + 호출부 코드 revert

---

## 7. Out-of-Scope 재확인

본 plan은 spec.md Section 3 (Exclusions) 의 항목을 어떤 형태로든 구현하지 않는다. 특히:

- 인트라데이 레짐 갱신, ML 분류, 프런트 UI, 외부 설정 파일, VIX 통합, 종목별 레짐, 백테스트 시뮬레이션, 알림, A/B 테스트는 본 SPEC 범위 밖이다.
