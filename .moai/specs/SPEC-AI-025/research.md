# SPEC-AI-025 — Research Artifact

Generated: 2026-05-29
Scope: Backend-only — `news-hive/backend/`

## 1. Problem Context (Empirical Evidence)

### 1.1 2026-05-29 KST LG그룹 Cascade 사건

당일 KST 거래일 종가 기준:

| 종목 | 코드 | 종가 변동률 | 시그널 발행 여부 |
|------|------|-------------|------------------|
| LG전자 | 066570 | **+29.93%** | (anchor 자체로 처리됨, 별도 데이터 필요) |
| LG이노텍 | 011070 | **+28.57%** | (anchor 자체로 처리됨, 별도 데이터 필요) |
| LG (지주) | 003550 | **+26.60%** | (anchor 자체로 처리됨, 별도 데이터 필요) |
| LG씨엔에스 | 064400 | **+29.91%** | **누락** (SPEC-AI-022 propagation 미발화) |
| 솔루스첨단소재 | 336370 | **+25.70%** | **누락** (SPEC-AI-022 propagation 미발화) |

핵심 관찰: 같은 LG그룹의 anchor(LG전자 + LG이노텍 + LG) **3종이 모두 +25% 이상 동시 마감**한 상황은 통계적으로 극히 드물며, 그룹 cascade의 가장 강력한 신호다. SPEC-AI-022의 intraday 전파가 침묵한 원인은 두 갈래 추정:

1. anchor의 `theme_cluster_score`가 `0.80` 임계값 미만이었다 — 가격은 폭등했으나 뉴스/공시 결합 부족으로 ensemble 점수가 낮았다.
2. anchor 자체가 surge_candidate에 잡혔으나, propagation 함수의 anchor_score_threshold(`0.80`) 필터에서 탈락했다.

어느 경우든 **종가 자체를 독립 시그널로 활용하는 EOD 보강 계층**의 부재가 root cause다.

## 2. Existing Pipeline Map

### 2.1 `_run_coverage_expansion()` 위치 및 호출 관계

`backend/app/services/fund_manager.py`:

- L2866: `_run_coverage_expansion(db, candidates)` 호출 — `_gather_surge_candidates` 직후 surge_candidate DB 저장 완료 시점.
- L3654: `def _run_coverage_expansion(db, surge_results)` 함수 본체.
- 본 함수는 4단계로 구성되어 있다 (현재):
  1. **테마 전파** (SPEC-AI-022 REQ-001) — `propagate_theme_group_signals`
  2. **거래량 이상** (SPEC-AI-022 REQ-002) — `detect_volume_anomaly_dormant_stocks`
  3. **상한가 근접 carry-forward** (SPEC-AI-023) — `detect_near_limit_up_carries`

각 단계는 독립된 try/except로 격리되며, 한 단계 실패가 surge_candidate 결과나 다른 단계에 영향을 주지 않는다. 본 SPEC은 4번째 단계(테마 그룹 강세 carry-forward)로 추가된다.

### 2.2 SPEC-AI-022 propagation 함수 (`propagate_theme_group_signals`)

`backend/app/services/surge_detector.py` L1190-1311:

- 진입 조건: `qualified_candidates` 중 `theme_cluster_score >= 0.80`인 anchor만 propagation 대상.
- 그룹 조회 → peer 조회 → `peer_best` 사전 집계 → 단일 row 발행.
- 시그널 속성: `signal_type="theme_propagation"`, `confidence=0.25`, `paper_executed=False`.
- 본 SPEC과의 차이점:
  - SPEC-AI-022: intraday 앙상블 점수 트리거, `paper_executed=False` (관측 우선)
  - SPEC-AI-025: EOD 종가 트리거, `paper_executed=True` (매수 큐 포함)
  - 양자는 상호 보완. SPEC-AI-022가 발행한 peer는 SPEC-AI-025의 (a) 조건(시그널 부재)에 의해 자동 제외되어 중복 회피 보장.

### 2.3 SPEC-AI-023 reference 패턴 (`detect_near_limit_up_carries`)

`backend/app/services/surge_detector.py` L1471-1577:

- 진입 조건: 시총 상위 N 종목 중 어제 `25% ≤ change_rate ≤ 29.99%`.
- 시그널 속성: `signal_type="surge_candidate"`, `confidence=round(change/30*0.5, 4)`, `paper_executed=True`.
- 메타데이터: `surge_basis: ["near_limit_up_carry"]`.
- 본 SPEC은 이 패턴을 그룹 단위로 확장:
  - SPEC-AI-023: 종목 단위 (시총 상위 스캔, 모든 종목 개별 평가)
  - SPEC-AI-025: 그룹 단위 (그룹 anchor 1종 평가 → 그룹 peer 다수에 전파)
  - 매수 큐 자동 포함 정책(`paper_executed=True`, `signal_type="surge_candidate"`)은 동일하게 채택.

### 2.4 ThemeGroup 모델 (SPEC-AI-022)

`backend/app/models/theme_group.py`:

```python
class ThemeGroup(Base):
    __tablename__ = "theme_groups"
    id: Mapped[int] = ...
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    anchor_stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None]
    created_at: Mapped[datetime]

    stocks = relationship("Stock", secondary="stock_theme_groups", ...)
    anchor_stock = relationship("Stock", foreign_keys=[anchor_stock_id])

class StockThemeGroup(Base):
    __tablename__ = "stock_theme_groups"
    id: Mapped[int]
    stock_id: Mapped[int]
    theme_group_id: Mapped[int]
    weight: Mapped[float] = 1.0
    created_at: Mapped[datetime]
    UniqueConstraint("stock_id", "theme_group_id")
```

핵심 관찰:
- `anchor_stock_id`는 `nullable=True`이므로 NULL 안전 처리가 필수.
- 본 SPEC은 `anchor_stock_id IS NOT NULL`인 그룹만 평가.
- `stocks` 관계는 `secondary` 다대다이므로 peer 조회는 `StockThemeGroup` 명시 join이 안전.

### 2.5 Naver Finance API 통합점

`backend/app/services/naver_finance.py`:

- L810: `def fetch_current_price_with_change_sync(stock_code: str) -> dict | None:` — 동기 함수. 반환 `{"current_price": int, "change_rate": float, ...}` 또는 None.
- L1168: `async def fetch_current_price_with_change(stock_code: str) -> dict | None:` — 비동기 버전 (본 SPEC은 동기 컨텍스트의 `_run_coverage_expansion`에서 호출하므로 sync 버전 사용).
- SPEC-AI-023이 동일 함수를 사용하므로 mock 패턴 재사용 가능.

## 3. Design Decisions Rationale

### 3.1 signal_type 선택: 신규값 vs `surge_candidate` 재사용

| 옵션 | 장점 | 단점 |
|------|------|------|
| 신규 `theme_group_carry` | 명확한 식별, 분석 분리 용이 | `get_today_signals` 필터 변경 필요 → 매수 큐 통합 코드 변경 |
| `surge_candidate` 재사용 + metadata 구분 | 매수 큐 자동 통합, 코드 무변경 | 신호 출처 추적은 `surge_metadata.surge_basis` 의존 |

**채택**: `surge_candidate` 재사용. SPEC-AI-023과 동일 정책. 익일 매수 큐 자동 통합 이점이 분석 분리 비용보다 크다.

### 3.2 confidence 공식: `change_rate / 30.0 * 0.4`

- anchor +30% → confidence = 0.40 (최대)
- anchor +10% → confidence = 0.133
- anchor +5% → confidence = 0.067
- anchor +8% → confidence = 0.107

`get_today_signals(min_probability=0.10)`의 일반적 임계값을 기준으로 anchor 약 +7.5% 이상이면 매수 큐 통과 가능. 보수적 설계로 anchor 약세(+5~7%)는 발행되나 자동 매수는 제외되는 자연스러운 필터링.

SPEC-AI-023이 동일 공식의 0.5 계수를 사용하는 것과 비교해 0.4 계수는 더 보수적. 이유: SPEC-AI-023은 종목 자체가 상한가 근접(25-30%)이므로 강한 신호. 본 SPEC은 anchor만 강세이고 peer는 검증되지 않았으므로 한 단계 보수적으로 가중.

### 3.3 paper_executed=True 채택 (vs SPEC-AI-022의 False)

- SPEC-AI-022 `theme_propagation`은 `paper_executed=False` — 관측 우선 정책.
- 본 SPEC은 `True` — 다음 근거:
  1. **종가 기반 데이터의 신뢰성**: 장중 변동성 대비 종가는 확정값.
  2. **anchor의 종가 강세는 강한 후행 지표**: SPEC-AI-023 패턴이 이미 입증.
  3. **그룹 cascade는 통계적 사건**: 같은 그룹 다수가 동시 마감 강세는 우연 확률 낮음.

### 3.4 anchor만 평가 (peer 가격 조회 안 함)

- 비용: 그룹당 API 호출 1회 (anchor) × 그룹 수 = 4~수십 회 / 일.
- 만약 peer 가격까지 조회하면: 그룹당 5~10회 × 그룹 수 = 수십~수백 회.
- 본 SPEC의 가설은 "anchor 강세가 peer 강세를 시사한다"이므로 peer 가격 확인은 트리거 단계 불필요. recent_surge_penalty(SPEC-AI-018)는 매수 단계에서 별도 적용된다.

### 3.5 동일 peer 복수 그룹 멤버십 처리

`emitted_in_this_run: set[int]`로 본 SPEC 실행 1회당 동일 peer 1건 발행 보장. 첫 그룹 순회 시점에 발행되므로 그룹 우선순위는 DB 정렬 순서에 의존(현재 `theme_groups.id` 오름차순). 향후 가중치 도입 시 group.priority 추가 가능하나 본 SPEC 범위 외.

## 4. Implementation Risk Analysis

| 위험 | 영향도 | 완화책 |
|------|--------|--------|
| `fetch_current_price_with_change_sync` 외부 API 장애 | 중 | 그룹별 try/except, 실패 그룹만 스킵 |
| `_run_coverage_expansion` 5번째 블록 예외 | 중 | 함수 외부 try/except로 격리, 다른 단계 무영향 |
| 동일 peer 다중 그룹 멤버십 시 N건 발행 | 중 | `emitted_in_this_run` set 가드 |
| `anchor_stock_id IS NULL` 그룹 NULL 접근 | 높음 | 진입 직후 NULL 가드 |
| `paper_executed=True`로 무차별 매수 큐 추가 | 중 | confidence 0.4 계수로 보수적 가중, `get_today_signals` min_probability 필터 자연 작동 |
| SPEC-AI-022 `theme_propagation`과 중복 발행 | 낮음 | (a) 조건 `signal_type` 불문 시그널 부재 확인 |

## 5. Test Coverage Strategy

### 5.1 Unit Tests (`backend/tests/test_theme_group_carry.py`)

- AC-001: anchor +8% → 2개 peer 시그널, confidence 검증
- AC-002: anchor +3% → 0건
- AC-003: peer 시그널 기존 → 스킵
- AC-004: anchor_stock_id NULL → 그룹 스킵, API 미호출
- AC-005: 가격 API 예외 → 그룹 격리 (다른 그룹 정상 처리)
- AC-006: max_signals_per_group 제한 검증
- AC-007: 동일 peer 복수 그룹 → 1건 발행
- AC-008: enabled=False → 즉시 종료

### 5.2 Integration Tests (`backend/tests/test_coverage_expansion_integration.py`)

- AC-009: `_run_coverage_expansion` 5번째 블록 예외 시 격리
- AC-010: 발행된 시그널이 `get_today_signals` 통과 확인

### 5.3 Mock 패턴

```python
# SPEC-AI-023 테스트에서 검증된 패턴 재사용
from unittest.mock import patch

@patch("app.services.surge_detector.fetch_current_price_with_change_sync")
def test_anchor_surge_triggers_carry(mock_fetch, db, theme_groups_fixture):
    mock_fetch.return_value = {"change_rate": 8.0}
    config = ThemeGroupCarryConfig(anchor_surge_min_pct=5.0)
    result = detect_theme_group_carry_forward(db, config)
    assert len(result) == 2
    assert result[0].confidence == 0.1067
```

## 6. Open Questions (Resolved at Spec Writing Time)

| 질문 | 결정 | 근거 |
|------|------|------|
| signal_type 신규값 도입? | No, surge_candidate 재사용 | 매수 큐 통합 단순성 |
| peer 가격 검증? | No, anchor만 평가 | API 호출 비용 |
| recent_surge_penalty 적용? | No, 매수 단계에서 별도 적용 | 관심 분리 |
| paper_executed 정책? | True | SPEC-AI-023 패턴 정합성 |
| 동일 peer 다중 그룹? | 1건만 발행 | 중복 방지 |
| anchor_stock_id NULL 그룹? | 스킵 | 안전 처리 |
| max_signals_per_group 기본값? | 5 | 그룹당 적정 한도 |
| confidence 계수? | 0.4 | SPEC-AI-023(0.5) 대비 보수적 |
| anchor_surge_min_pct 기본값? | 5.0% | 일반 강세 vs 강한 강세 경계 |

## 7. Cross-Reference Map

| SPEC-AI-025 컴포넌트 | 의존 / 영향 SPEC |
|----------------------|------------------|
| `ThemeGroup`/`StockThemeGroup` 스키마 | SPEC-AI-022 마이그레이션 037 (필수 선행) |
| `signal_type="surge_candidate"` 재사용 | SPEC-AI-012 surge_detector 앙상블 (기존 정의 준수) |
| `paper_executed=True` 익일 매수 큐 | SPEC-AI-013 surge_trading_service.get_today_signals (자동 통합) |
| `surge_basis: ["theme_group_carry"]` 메타데이터 | SPEC-AI-022 coverage 엔드포인트 (by_signal_type 집계는 미세분, 후속 분석 가능) |
| anchor 종가 강세 트리거 | SPEC-AI-018 시장 레짐 (직접 의존하지 않음, 매수 단계에서 별도 평가) |
| `_run_coverage_expansion` 통합 | SPEC-AI-022 REQ-001/002, SPEC-AI-023 (같은 함수 내 동거) |

## 8. Verification Evidence Plan

- 시그널 발행 후 7~14일 후속 추적: `created_at + N일`의 가격 변동을 별도 분석 스크립트로 측정.
- SPEC-AI-022 `theme_propagation` 적중률 vs SPEC-AI-025 `theme_group_carry` 적중률 비교 — `surge_metadata.surge_basis`로 필터링하여 분석.
- LG그룹 사례(2026-05-29)를 backtest 시드로 사용하여 LG씨엔에스, 솔루스첨단소재가 본 SPEC으로 정상 발행되는지 검증.

---

End of research artifact.
