"""SPEC-AI-012: 급등 징후 탐지 백테스트 서비스 테스트.

AC-SURGE-006: 백테스트 정확도 및 조합별 통계
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_backtest import SurgeBacktestResult, compute_surge_backtest


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def sector_test(db: Session) -> Sector:
    s = Sector(name="테스트섹터")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def make_stock_for_backtest(db: Session, sector_test: Sector):
    """종목 팩토리."""
    _counter = [0]

    def _factory(name: str | None = None) -> Stock:
        _counter[0] += 1
        stock = Stock(
            name=name or f"테스트주{_counter[0]}",
            stock_code=f"BT{_counter[0]:04d}",
            sector_id=sector_test.id,
            market_cap=500,
        )
        db.add(stock)
        db.flush()
        return stock

    return _factory


def _make_surge_signal(
    db: Session,
    stock: Stock,
    price_at_signal: int,
    price_after_5d: int,
    surge_basis: list[str],
    days_ago: float = 1.0,
) -> FundSignal:
    """테스트용 surge_candidate 시그널 생성 헬퍼."""
    metadata = json.dumps({
        "surge_probability_score": 0.7,
        "surge_basis": surge_basis,
        "theme_cluster_score": 0.5,
        "combo_score": 0.6,
        "pattern_score": 0.4,
        "legacy_score": 0.3,
    })
    signal = FundSignal(
        stock_id=stock.id,
        signal="buy",
        confidence=0.7,
        reasoning="백테스트 테스트 시그널",
        signal_type="surge_candidate",
        price_at_signal=price_at_signal,
        price_after_5d=price_after_5d,
        surge_metadata=metadata,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(signal)
    db.flush()
    return signal


# ---------------------------------------------------------------------------
# AC-SURGE-006: 백테스트 정확도
# ---------------------------------------------------------------------------

class TestSurgeBacktest:
    """급등 징후 탐지 백테스트 테스트."""

    def test_characterize_accuracy_calculation(
        self,
        db: Session,
        make_stock_for_backtest,
    ):
        """방향성 적중률이 올바르게 계산된다 (AC-SURGE-006 시나리오 1).

        4개 시그널: 3개 적중(상승), 1개 실패(하락)
        → directional_accuracy = 3/4 = 0.75
        """
        stock = make_stock_for_backtest()

        # 3개 적중: price_after > price_at
        for i in range(3):
            _make_surge_signal(
                db,
                stock,
                price_at_signal=10000,
                price_after_5d=11000,  # 10% 상승
                surge_basis=["theme_cluster", "volume_news_combo"],
                days_ago=float(i + 1),
            )

        # 1개 실패: price_after <= price_at
        _make_surge_signal(
            db,
            stock,
            price_at_signal=10000,
            price_after_5d=9500,  # 5% 하락
            surge_basis=["theme_cluster"],
            days_ago=4.0,
        )

        result = compute_surge_backtest(db, days=30)

        assert result.total_signals == 4
        assert abs(result.directional_accuracy - 0.75) < 0.001
        # 평균 수익률: (10 + 10 + 10 - 5) / 4 = 6.25%
        assert abs(result.average_return_pct - 6.25) < 0.01

    def test_characterize_by_combination_breakdown(
        self,
        db: Session,
        make_stock_for_backtest,
    ):
        """탐지기 조합별 통계가 분리된다 (AC-SURGE-006 시나리오 2)."""
        stock1 = make_stock_for_backtest()
        stock2 = make_stock_for_backtest()

        # 조합 A: theme_cluster+volume_news_combo — 2개 적중
        for i in range(2):
            _make_surge_signal(
                db,
                stock1,
                price_at_signal=10000,
                price_after_5d=11000,
                surge_basis=["theme_cluster", "volume_news_combo"],
                days_ago=float(i + 1),
            )

        # 조합 B: disclosure_pattern — 1개 적중, 1개 실패
        _make_surge_signal(
            db,
            stock2,
            price_at_signal=10000,
            price_after_5d=11000,
            surge_basis=["disclosure_pattern"],
            days_ago=3.0,
        )
        _make_surge_signal(
            db,
            stock2,
            price_at_signal=10000,
            price_after_5d=9800,
            surge_basis=["disclosure_pattern"],
            days_ago=4.0,
        )

        result = compute_surge_backtest(db, days=30)

        assert result.total_signals == 4
        assert "theme_cluster+volume_news_combo" in result.by_combination
        assert "disclosure_pattern" in result.by_combination

        combo_a = result.by_combination["theme_cluster+volume_news_combo"]
        assert combo_a["count"] == 2
        assert abs(combo_a["accuracy"] - 1.0) < 0.001  # 2/2 = 100%

        combo_b = result.by_combination["disclosure_pattern"]
        assert combo_b["count"] == 2
        assert abs(combo_b["accuracy"] - 0.5) < 0.001  # 1/2 = 50%

    def test_characterize_empty_signals_returns_zero_result(self, db: Session):
        """surge_candidate 시그널이 없으면 모든 값이 0이다."""
        result = compute_surge_backtest(db, days=30)

        assert result.total_signals == 0
        assert result.directional_accuracy == 0.0
        assert result.average_return_pct == 0.0
        assert result.by_combination == {}

    def test_characterize_signals_outside_days_range_excluded(
        self,
        db: Session,
        make_stock_for_backtest,
    ):
        """days 파라미터 범위 밖의 시그널은 집계에서 제외된다."""
        stock = make_stock_for_backtest()

        # 30일 이내 시그널 1개
        _make_surge_signal(
            db,
            stock,
            price_at_signal=10000,
            price_after_5d=11000,
            surge_basis=["theme_cluster"],
            days_ago=20.0,
        )

        # 30일 이외 시그널 1개 (31일 전)
        _make_surge_signal(
            db,
            stock,
            price_at_signal=10000,
            price_after_5d=11000,
            surge_basis=["theme_cluster"],
            days_ago=31.0,
        )

        result = compute_surge_backtest(db, days=30)

        # 30일 이내 1개만 집계
        assert result.total_signals == 1
