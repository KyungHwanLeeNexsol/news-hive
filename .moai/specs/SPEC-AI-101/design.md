# SPEC-AI-101 Design

## §A. 설계 범위

두 개의 독립적인 서브시스템을 다룬다 — (B~D) 신호가 기준 EOD 최대수익률 라벨, (E~G)
SPEC-AI-100 섀도우 관측 실행. 두 서브시스템은 서로 참조하지 않으며 독립적으로
구현·검증·배포 가능하다(plan.md TASK 분해에서 병렬 마일스톤으로 취급).

## §B. 라벨 설계 — 왜 EOD 근사가 "point-in-time"의 정당한 축소 범위인가

원 비평의 요구는 "신호 발행 시점 이후의 미래 가격 경로"를 라벨에 반영하는 것이다. 이상적
형태(30/60/120분 다중 지평 + MAE + 슬리피지)는 시계열 전체를 요구하지만, 핵심 결함
(종가 단일 관측점)의 대부분은 **하루 중 최고점 하나만 추가**해도 해소된다 — 원 비평이
제시한 두 반례 모두 "그날의 고점이 신호가 대비 목표 수익률을 넘었는가"만으로 올바르게
재분류된다. 즉 EOD 최댓값은 이상적 설계의 정보 손실 있는 근사이지만, 비평이 실제로
문제 삼은 실패 사례 클래스를 재현 없이 커버하는 최소 충분 설계다.

### B.1 계산식

```
day_high_price(T, code)      = prev_close_price(T-1, code) × (1 + high_change_rate(T, code) / 100)
forward_max_return_pct       = (day_high_price − price_at_signal) / price_at_signal × 100
```

- `high_change_rate(T, code)`: `SurgeActualOutcome`에 이미 SPEC-AI-093으로 실측 수집됨(T-1
  종가 대비 장중 고가 등락률, %).
- `prev_close_price(T-1, code)`: `fetch_stock_price_history_sync(code)`의 반환 리스트에서
  `date == T-1`을 매칭해 조회(SPEC-AI-072 선례 — 인덱스가 아닌 날짜 매칭).
- `price_at_signal`: `FundSignal.price_at_signal`(이미 저장됨, 시그널 발행 시점 주가).

### B.2 왜 `SurgeActualOutcome`이 아닌 신규 테이블인가

`SurgeActualOutcome`의 PK는 `(trading_date, stock_code)` — 종목당 하루 1행이다.
`forward_max_return_pct`는 **신호 단위**로 다른 값을 가질 수 있다(예: T-1 15:20 배치
신호와 09:30 이벤트 재스캔 신호가 같은 종목·같은 날 다른 `price_at_signal`을 가짐,
SPEC-AI-083). 신호 단위 값을 (날짜,종목) 단위 테이블에 넣으면 마지막 신호로 덮어써지는
데이터 손실이 생긴다 — D1이 신규 테이블을 채택한 이유다.

### B.3 왜 `SurgeActualOutcome.was_surge` 자체를 바꾸지 않는가

`was_surge`는 이 프로젝트 전체(`diagnose_non_scannable_causes`,
`evaluate_surge_predictions` 표준 T-1→T 경로, `surge_evaluation_service.py` 내 최소 7곳)의
소비 지점을 가진 SSOT다. SPEC-AI-095가 동일한 상황(`high_change_rate`라는 "더 정확할
수 있는" 대안 지표 도입)에서 "동결 + 병렬 추가"를 선택했고 이는 이 프로젝트의 확립된
컨벤션이다. 재정의를 선택하면 과거 평가 이력(recall/precision 시계열)이 소급 변경되어
SPEC-AI-050/061/065 등 과거 튜닝 결정의 근거 데이터가 흔들린다 — 이 위험을 감수할 근거가
없어 파괴적 재정의를 기각한다(D1).

## §C. 신규 테이블 스키마 (초안 — Open Question 1)

```python
class SurgeSignalForwardOutcome(Base):
    __tablename__ = "surge_signal_forward_outcome"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    fund_signal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    price_at_signal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prev_close_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    day_high_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    forward_max_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`(trading_date, fund_signal_id)`를 UNIQUE 제약으로 두어 평가 잡 재실행 시 upsert
(`SurgeActualOutcome`이 이미 쓰는 upsert 패턴 재사용)로 멱등성을 보장한다. 정확한 필드명·
인덱스 전략은 구현 시 `FundSignal` 테이블의 기존 인덱스 관례를 따라 확정한다(Open
Question 1).

## §D. `evaluate_surge_predictions()` 통합 지점

REQ-AI101-001/002는 `surge_evaluation_service.py`의 기존 `predicted_set` 확정 지점
(`:736-746`) **이후**, `high_based_*` 계산 블록(`:858-908`)과 **나란히** 새 블록을
추가한다 — 동일한 try/except + `db.rollback()` 격리 패턴, 동일한 "predicted_set은 이미
확정, 재조회 금지" 원칙을 재사용한다. `predicted_set` 자체, `actual_set` 자체,
`legacy_recall`/`scannable_recall`/`coverage` 산출 로직은 이 REQ의 구현으로 무수정이다.

## §E. 섀도우 관측 활성화 순서 (실행 순서 제약)

REQ-AI101-003(`shadow_mode_enabled: true` 전환)은 REQ-AI101-004(영속화 함수 구현)
**이후**에 적용되어야 한다 — 순서를 바꾸면 영속화 없이 관측이 시작되어 D3이 해결하려는
"로그만으로는 변화 없는 날이 누락된다" 문제가 그대로 재현된다. plan.md TASK 순서가 이
제약을 반영한다.

## §F. 섀도우 비교 영속화 — `run_horizon_shadow_comparison` 확장

현재 시그니처:

```python
def run_horizon_shadow_comparison(
    merged: dict[str, SurgeCandidate],
    qualified_codes: set[str],
    market_regime: str,
    config: SurgeDetectionConfig,
) -> None:
```

확장 후(신규 `db` 인자 추가, 반환 타입 무변경 — 호출부 `surge_detector.py:2561` 1곳만
수정 필요):

```python
def run_horizon_shadow_comparison(
    merged: dict[str, SurgeCandidate],
    qualified_codes: set[str],
    market_regime: str,
    config: SurgeDetectionConfig,
    db: "Session | None" = None,
) -> None:
```

`db=None` 기본값으로 기존 호출부(만약 다른 곳에서 위치 인자로 호출하는 곳이 있다면)와의
하위 호환을 보존한다. 함수 본문의 `if added or removed: logger.info(...)` 블록은
**그대로 유지**하고, 그 아래에 무조건(변화 유무와 무관하게) `db`가 제공된 경우
`SurgeHorizonShadowObservation` 1행을 적재하는 코드를 추가한다. 영속화 실패는 기존
`except Exception as shadow_exc:` 블록에 포함시켜 격리한다(REQ-AI100-007 예외 격리
원칙 재사용, D4).

`compute_ensemble_score`/`compute_horizon_signature`/`select_effective_threshold` 호출
순서와 인자는 무수정이다 — 이 함수들이 반환한 `shadow_qualified_codes`를 신규 테이블에
적재하는 것만 추가한다.

## §G. 전환 게이트 판정 함수

```python
def check_horizon_transition_readiness(db: Session) -> dict:
    """SPEC-AI-100 REQ-AI100-009 3요건 판정 참고 정보를 반환한다. 자동 전환은 하지 않는다."""
    # 관측 고유 거래일 수
    # 관측된 시장 레짐 집합 (BULL/SIDEWAYS/BEAR)
    # 관측 기간 중 (added+removed)/기존qualified 최대 변화폭 %
    ...
```

반환 예시: `{"observed_trading_days": N, "regimes_observed": {...}, "max_change_pct": X.X,
"all_criteria_met": bool}`. `all_criteria_met`은 표시용 참고값이며, 이 값을 근거로
`enabled` 플래그를 자동 전환하는 코드는 어디에도 두지 않는다(D5, REQ-AI101-005 필수
조건).

## §H. 리스크

- **`price_at_signal` 채움률 미확인 리스크**: nullable 컬럼이라 실측 채움률을 아직
  확인하지 못했다(Open Question 2). 채움률이 낮으면 신규 지표의 표본이 작아져 실효성이
  제한된다 — 구현 착수 시 도메인 검증으로 확정한다.
- **`day_high_price` 근사 오차 리스크**: `high_change_rate`는 T-1 종가 대비 %이므로,
  `prev_close_price` 조회가 실패하거나(공휴일 경계, 신규 상장 종목 등) 부정확하면
  파생값 오차가 누적된다 — REQ-AI101-001이 이 경우 NULL 처리를 명시해 조용한 오분류를
  방지한다.
- **섀도우 테이블 무한 증가 리스크**: 매 스코어링 사이클마다 1행씩 적재되므로 장기
  운영 시 테이블이 커진다 — Open Question 3(보존 정책)으로 명시했으며, 전환 게이트
  판정 자체는 본 SPEC 완료의 필수 조건이 아니므로(관측 인프라 구축까지가 DoD) 보존
  정책 확정은 후속 작업으로 유예 가능하다.
