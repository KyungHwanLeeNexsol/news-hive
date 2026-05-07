# SPEC-AI-015 인수 기준 (acceptance.md)

## 0. 개요

본 문서는 SPEC-AI-015 (시장 레짐 적응형 전략) 의 인수 기준을 Given-When-Then 형식으로 정의한다. 모든 시나리오는 자동화 가능하며, "Definition of Done" 섹션의 모든 항목이 충족되어야 SPEC이 완료로 간주된다.

---

## 1. 핵심 시나리오 (Given-When-Then)

### Scenario 1: BULL 레짐 분류 및 동적 임계값 적용

**Given** KOSPI 5일 수익률이 +2.3%이고, 현재 종가가 20일 이동평균선 +1.5% 위에 있는 영업일
**When** 09:00 KST 스케줄러가 `get_or_create_today_regime(db)` 를 호출한다
**Then**:
- `market_regimes` 테이블에 오늘 날짜로 1건 INSERT 된다
- `regime` 컬럼 값은 `BULL`
- `confidence_score` ≥ 0.6
- 같은 날짜에 다시 호출하면 새 INSERT 없이 동일 레코드 반환 (멱등성)

**And When** 같은 날 `analyze_stock(db, ...)` 가 호출된다
**Then**:
- AI 프롬프트에 `_signal_min_confidence=0.48`, `_signal_target_max=0.30`, `_signal_market_regime="상승장"` 텍스트가 포함된다
- AI 응답 confidence가 0.48~0.55 범위면 코드 가드를 통과한다 (이전 0.50 정적 임계값으로는 통과 못 함)
- AI 응답 confidence가 0.47이면 코드 가드에서 hold로 다운그레이드된다

---

### Scenario 2: BEAR 레짐 시 보수 모드 진입

**Given** KOSPI 5일 수익률이 -2.1%이고, 현재 종가가 20일 이동평균선 -3.5% 아래
**When** 09:00 KST 스케줄러 실행 후
**Then**:
- 오늘 레짐은 `BEAR`, `confidence_score` ≥ 0.6
- `get_regime_params(BEAR)` 는 `min_action_confidence=0.65`, `max_position_pct_high=0.10`, `target_pct_max=0.15`, `stop_loss_pct_default=0.04`, `max_daily_trades=2` 를 반환한다

**And When** AI가 confidence=0.62로 매수 시그널을 생성한다
**Then**:
- 코드 가드에서 0.65 미달 → hold로 다운그레이드
- `paper_trading.execute_signal_trade()` 는 매수를 실행하지 않는다

**And When** AI가 confidence=0.85로 매수 시그널을 3건 연속 생성한다 (같은 날)
**Then**:
- 첫 2건은 정상 실행 (포지션 사이즈 conf≥0.80 → BEAR max=0.10)
- 3번째는 일일 거래 한도(BEAR=2) 초과로 hold 다운그레이드
- 로그에 "max_daily_trades exceeded for regime=BEAR" 기록

---

### Scenario 3: SIDEWAYS 레짐 디폴트 동작

**Given** KOSPI 5일 수익률이 +0.4% (BULL/BEAR 임계값 미달)
**When** 분류 실행
**Then**:
- 레짐은 `SIDEWAYS`
- `RegimeParams` 는 `min_action_confidence=0.55`, `max_position_pct_high=0.15`, `target_pct_max=0.25`, `stop_loss_pct_default=0.05`, `max_daily_trades=5`
- 이는 즉시 적용 fix(168e4cb) 이전의 기본 동작과 거의 동일 (역호환)

---

### Scenario 4: 데이터 부재 Graceful Fallback

**Given** `SectorMomentum` 테이블에 오늘 데이터가 없거나, KOSPI 20일 MA 조회 외부 API가 타임아웃
**When** `get_or_create_today_regime(db)` 호출
**Then**:
- DB INSERT 시도하지 않음 (또는 NULL 가용 컬럼만 채워 INSERT)
- 호출자에게 `regime=SIDEWAYS`, `confidence_score=0.5` 의 in-memory 객체 반환
- WARN 레벨 로그: "market_regime fallback: data unavailable"
- `analyze_stock()`, `_position_pct_by_confidence()` 모두 SIDEWAYS 파라미터로 정상 동작
- 시스템 무중단

---

### Scenario 5: API 엔드포인트 응답

**Given** 7영업일 누적 데이터가 `market_regimes` 에 존재
**When** 클라이언트가 `GET /fund/market-regime` 요청
**Then**:
- HTTP 200 응답
- JSON 스키마:
  - `today.date`, `today.regime`, `today.kospi_5d_return`, `today.kospi_20d_ma_position`, `today.confidence_score`, `today.params.{5개 필드}` 모두 존재
  - `history` 배열 길이는 1~7
  - `history[i].date` 는 today 미포함, 최신순 정렬

**And When** `market_regimes` 테이블이 비어 있는 상태에서 요청
**Then**:
- HTTP 200 응답
- `today.regime = "SIDEWAYS"`, `today.confidence_score = 0.5`
- `history = []`
- `today.date = today (KST)`
- 시스템은 SIDEWAYS 디폴트 응답을 인메모리 생성하여 반환 (DB INSERT 강제 안 함)

---

### Scenario 6: 멱등성 및 Race Condition 방어

**Given** 09:00:00 KST에 스케줄러가 실행되고, 09:00:01 KST에 사용자가 `GET /fund/market-regime` 호출 (분류 진행 중)
**When** 두 호출이 동시에 `get_or_create_today_regime(db)` 진입
**Then**:
- UNIQUE constraint on `date` 가 race를 차단
- 한쪽이 IntegrityError 발생 시 catch 후 SELECT 재시도하여 동일 레코드 반환
- 최종적으로 1건만 INSERT, 두 호출 모두 동일 객체 반환

---

### Scenario 7: 레짐별 포지션 사이즈

**Given** BULL 레짐, AI confidence=0.85
**When** `_position_pct_by_confidence(0.85, db)` 호출
**Then**: 반환값 = 0.20 (BULL `max_position_pct_high`)

**Given** BEAR 레짐, AI confidence=0.85
**When** `_position_pct_by_confidence(0.85, db)` 호출
**Then**: 반환값 = 0.10 (BEAR `max_position_pct_high`)

**Given** SIDEWAYS 레짐, AI confidence=0.65
**When** `_position_pct_by_confidence(0.65, db)` 호출
**Then**: 반환값 = 0.075 (SIDEWAYS 0.15 × 0.50, 0.05 ~ 0.20 clamp 적용)

---

### Scenario 8: 폴백 디폴트 stop/target

**Given** BULL 레짐, AI 응답이 `stop_loss_pct` / `target_pct` 필드를 명시하지 않은 경우
**When** `paper_trading.execute_signal_trade()` 가 거래를 생성
**Then**:
- `stop_loss_pct = 0.07` (BULL `stop_loss_pct_default`)
- `target_pct = 0.30` (BULL `target_pct_max`)

**Given** AI 응답이 `target_pct = 0.18` 명시
**When** 거래 생성
**Then**: `target_pct = 0.18` (AI 응답 우선, 폴백 미적용)

---

### Scenario 9: 후방 호환 — 기존 테스트 회귀 없음

**Given** main 브랜치의 모든 기존 테스트
**When** `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 실행
**Then**:
- 100% 통과
- 본 SPEC 도입 전 대비 신규 실패 zero
- 신규 테스트는 추가되지만 기존 테스트는 변경 없거나 시그니처 변경에 따른 호출부 update만

---

## 2. Edge Cases

| 케이스 | 처리 방식 |
|---|---|
| KOSPI 5일 수익률 = +1.499% (BULL 경계 미달) | SIDEWAYS |
| KOSPI 5일 수익률 = +1.500% & 20일 MA 위 | BULL |
| KOSPI 5일 수익률 = -1.5%, 20일 MA 위 | BEAR (5일 조건만 충족해도 BEAR — OR 조건) |
| KOSPI 5일 수익률 = +0.5%, 20일 MA -3% 아래 | BEAR (20일 MA 조건이 -2% 초과 → BEAR) |
| `volatility_index` NULL 입력 | 분류는 진행, DB는 NULL 저장 |
| 같은 날 두 번째 INSERT 시도 | UNIQUE 위반 catch → SELECT 재시도 |
| `get_recent_regimes(days=0)` | 빈 리스트 반환 |
| `get_recent_regimes(days=-1)` | 빈 리스트 반환 (방어) |
| 일일 거래 한도 도달 후 매도 시그널 | 매도는 한도와 무관하게 실행 (한도는 매수만 적용) |
| 레짐 전환일에 보유 중인 포지션의 stop/target | 진입 당시 파라미터 유지 (out-of-scope, 변경 없음) |
| 토요일/일요일 스케줄러 실행 | KOSPI 거래 없음 → SIDEWAYS or 직전 평일 데이터로 폴백 |
| 공휴일 (한국 증시 휴장) | 직전 거래일 SectorMomentum 사용, 또는 SIDEWAYS 디폴트 |

---

## 3. Quality Gate 기준 (TRUST 5)

### Tested
- [ ] 단위 테스트 커버리지 ≥ 85% on `market_regime_service.py`
- [ ] 통합 테스트: BULL/BEAR/SIDEWAYS 각 레짐별 end-to-end 시나리오 1건 이상
- [ ] API 테스트: 정상 응답 + 데이터 부재 응답 2건 이상
- [ ] 회귀 테스트 100% 통과 (`pytest tests/ --tb=short -q -m "not slow"`)

### Readable
- [ ] `RegimeParams` dataclass + `REGIME_PARAMS_MAP` dict의 의미가 한국어 docstring으로 설명됨
- [ ] 레짐 분류 임계값(±1.5%, ±2%)이 모듈 상수로 분리되어 의미를 명확히 함
- [ ] 함수명이 의도를 드러냄 (`classify_market_regime`, `get_or_create_today_regime`)

### Unified
- [ ] `ruff check .` 0 warnings
- [ ] `mypy app/services/market_regime_service.py` 0 errors
- [ ] 기존 코드 스타일과 일관 (snake_case, type hints 100%)

### Secured
- [ ] DB 입력값 검증 (`kospi_5d_return` 범위 -50% ~ +50% 가드)
- [ ] API 응답에 민감정보 없음 (시장 데이터만)
- [ ] SQL injection 방지: SQLAlchemy ORM만 사용

### Trackable
- [ ] 커밋 메시지: `feat(fund-manager): 시장 레짐 적응형 전략 도입 (SPEC-AI-015)` 형식
- [ ] CHANGELOG에 SPEC-AI-015 항목 추가
- [ ] `.moai/specs/SPEC-AI-015/spec.md` 가 git tracked

---

## 4. Definition of Done

본 SPEC은 다음 모든 항목이 충족될 때 완료로 간주된다:

### 코드 완성도
- [ ] `backend/app/models/market_regime.py` 신규 파일 생성
- [ ] `backend/app/services/market_regime_service.py` 신규 파일 생성
- [ ] `backend/alembic/versions/XXX_spec_ai_015_market_regime.py` 마이그레이션 작성
- [ ] `backend/app/services/fund_manager.py` 통합 (analyze_stock + briefing)
- [ ] `backend/app/services/paper_trading.py` 통합 (position + stop/target + daily cap)
- [ ] `backend/app/routers/fund.py` 엔드포인트 추가
- [ ] 스케줄러 09:00 KST 잡 등록

### 테스트 완성도
- [ ] `tests/services/test_market_regime_service.py` 신규
- [ ] `tests/api/test_fund_market_regime.py` 신규
- [ ] `tests/services/test_fund_manager_regime.py` 또는 기존 파일 확장
- [ ] `tests/services/test_paper_trading_regime.py` 또는 기존 파일 확장
- [ ] 모든 신규 테스트 통과, 기존 테스트 회귀 zero

### 운영 검증
- [ ] OCI 배포 후 첫 영업일 09:00 KST에 `market_regimes` 테이블에 1건 자동 INSERT 확인
- [ ] `GET /fund/market-regime` 외부 호출 200 OK 확인
- [ ] 1주일 운영 후 레짐 분포가 KOSPI 실제 추세와 합리적으로 정합 (BULL/BEAR/SIDEWAYS 분포 검증)
- [ ] 폴백 경로 검증: SectorMomentum 데이터 부재 강제 시 SIDEWAYS 디폴트 응답 확인

### 문서 완성도
- [ ] `.moai/specs/SPEC-AI-015/spec.md` 최종본 (HISTORY 갱신)
- [ ] `.moai/specs/SPEC-AI-015/plan.md` 최종본
- [ ] `.moai/specs/SPEC-AI-015/acceptance.md` 본 문서
- [ ] `.moai/specs/SPEC-AI-015/spec-compact.md` 압축본
- [ ] CHANGELOG.md 업데이트
- [ ] 본 SPEC ID가 `.moai/specs/ROADMAP.md` 에 반영

### Quality Gate
- [ ] TRUST 5 모든 항목 충족 (위 Section 3 참조)
- [ ] `cd backend && uv run ruff check . && uv run mypy app/` 통과
- [ ] `cd backend && uv run python -c "from app.main import app; print('OK')"` 통과

---

## 5. 검증 시나리오 — 운영 환경 1주차

배포 1주일 후 다음을 검증:

| 검증 항목 | 기준 | 측정 방법 |
|---|---|---|
| 레짐 분류 자동 실행 | 영업일 매일 1건 INSERT | `SELECT date, regime FROM market_regimes ORDER BY date DESC LIMIT 7;` |
| 레짐 분포 합리성 | BULL+BEAR+SIDEWAYS 합 = 영업일 수 | 위 쿼리 결과 집계 |
| AI 매수 시그널 빈도 (BULL 시) | 직전 1주 대비 상승 추세 영업일에 더 많은 buy 시그널 | `FundSignal` 테이블 일별 buy 카운트 vs `market_regimes.regime` 조인 |
| 일일 거래 한도 적용 (BEAR 시) | BEAR 일에 paper trade ≤ 2건 | `virtual_trades` + `market_regimes` 조인 |
| API 가용성 | 7일간 5xx error rate < 1% | 모니터링 로그 |
| 폴백 발동 빈도 | < 5% (KOSPI 20d MA 조회 실패율) | 로그 grep "market_regime fallback" |

---

## 6. 인수 책임자

- **개발 완료 확인**: manager-quality (TRUST 5 검증)
- **운영 검증**: 배포 후 1주일 사용자(Nexsol) 확인
- **최종 인수**: 본 acceptance.md의 모든 체크박스 충족 시
