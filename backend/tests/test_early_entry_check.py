"""SPEC-AI-042: early_entry_check 갭 필터 경계값 테스트.

REQ-042-006 갭 필터:
  - gap_rate >= gap_entry_threshold(0.05): skip → skipped_gapup++
  - gap_rate < 0: skip → skipped_gapdown++
  - 0 <= gap_rate < 0.05: 채택 → entered++
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import ARRAY, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    @compiles(ARRAY, "sqlite")
    def _array_sqlite(type_, compiler, **kw):
        return "TEXT"

    _engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture()
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()


_counter = [0]


def _make_stock(db: Session, suffix: str = "") -> Stock:
    _counter[0] += 1
    sector = Sector(name=f"섹터갭{_counter[0]}{suffix}")
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=f"{9000 + _counter[0]:06d}", name=f"갭테스트{_counter[0]}", sector_id=sector.id)
    db.add(stock)
    db.flush()
    return stock


def _make_today_preday_signal(db: Session, stock_id: int) -> FundSignal:
    """당일 08:30 KST 시각의 preday_disclosure 시그널 생성."""
    today_kst = datetime.now(KST).date()
    created_at = datetime.combine(today_kst, time(8, 30)).replace(tzinfo=KST)
    import json
    sig = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.80,
        reasoning="갭 필터 테스트 시그널",
        signal_type="preday_disclosure",
        surge_metadata=json.dumps({
            "detector": "immediate_disclosure",
            "source": "immediate_disclosure",
            "surge_probability_score": 0.80,
        }),
        created_at=created_at,
    )
    db.add(sig)
    db.flush()
    return sig


# ---------------------------------------------------------------------------
# 갭 필터 경계값 테스트
# ---------------------------------------------------------------------------

class TestGapFilterBoundaries:
    """REQ-042-006 갭 필터 경계값 검증."""

    def test_gap_filter_exact_threshold_5pct(self, db: Session):
        """gap == 0.05 (정확히 임계값) → skip (skipped_gapup++).

        경계: gap_rate >= gap_entry_threshold → skip
        0.05 >= 0.05 이므로 스킵이 되어야 한다.
        """
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "threshold")
        _make_today_preday_signal(db, stock.id)

        with patch(
            "app.services.preday_signal_service._compute_gap_rate",
            return_value=0.05,  # 정확히 5%
        ):
            result = early_entry_check(db)

        assert result["skipped_gapup"] >= 1, "gap=0.05 → skipped_gapup 증가해야 함"
        assert result["entered"] == 0, "gap=0.05 → 진입하면 안 됨"

    def test_gap_filter_just_under_threshold(self, db: Session):
        """gap == 0.049 (임계값 직하) → enter (REQ-042-006).

        0.049 < 0.05 이므로 채택되어야 한다.
        """
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "justunder")
        _make_today_preday_signal(db, stock.id)

        mock_execute_result = {"executed": 1, "skipped": 0, "failed": 0}

        with (
            patch(
                "app.services.preday_signal_service._compute_gap_rate",
                return_value=0.049,  # 임계값 직하
            ),
            patch(
                "app.services.preday_signal_service.execute_buy_orders",
                return_value=mock_execute_result,
            ) as mock_exec,
        ):
            result = early_entry_check(db)

        assert result["entered"] >= 1, "gap=0.049 → entered 증가해야 함"
        assert result["skipped_gapup"] == 0, "gap=0.049 → skipped_gapup이면 안 됨"
        assert mock_exec.called, "gap=0.049 → execute_buy_orders 호출되어야 함"

    def test_gap_filter_zero(self, db: Session):
        """gap == 0.0 → enter (REQ-042-006).

        0.0 >= 0 이고 0.0 < 0.05 이므로 채택.
        """
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "zero")
        _make_today_preday_signal(db, stock.id)

        mock_execute_result = {"executed": 1, "skipped": 0, "failed": 0}

        with (
            patch(
                "app.services.preday_signal_service._compute_gap_rate",
                return_value=0.0,
            ),
            patch(
                "app.services.preday_signal_service.execute_buy_orders",
                return_value=mock_execute_result,
            ) as mock_exec,
        ):
            result = early_entry_check(db)

        assert result["entered"] >= 1, "gap=0.0 → entered 증가해야 함"
        assert result["skipped_gapdown"] == 0, "gap=0.0 → 갭다운 아님"
        assert mock_exec.called, "gap=0.0 → execute_buy_orders 호출되어야 함"

    def test_gap_filter_negative_boundary(self, db: Session):
        """gap == -0.001 → skip (skipped_gapdown++).

        -0.001 < 0 이므로 갭다운 스킵.
        """
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "negboundary")
        _make_today_preday_signal(db, stock.id)

        with patch(
            "app.services.preday_signal_service._compute_gap_rate",
            return_value=-0.001,  # 미세 갭다운
        ):
            result = early_entry_check(db)

        assert result["skipped_gapdown"] >= 1, "gap=-0.001 → skipped_gapdown 증가해야 함"
        assert result["entered"] == 0, "gap=-0.001 → 진입하면 안 됨"

    def test_gap_filter_large_gapup(self, db: Session):
        """gap == 0.10 (10% 갭업) → skipped_gapup++ (갭풀백 위임)."""
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "largegapup")
        _make_today_preday_signal(db, stock.id)

        with patch(
            "app.services.preday_signal_service._compute_gap_rate",
            return_value=0.10,
        ):
            result = early_entry_check(db)

        assert result["skipped_gapup"] >= 1
        assert result["entered"] == 0

    def test_gap_filter_large_gapdown(self, db: Session):
        """gap == -0.05 (5% 갭다운) → skipped_gapdown++."""
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "largegapdown")
        _make_today_preday_signal(db, stock.id)

        with patch(
            "app.services.preday_signal_service._compute_gap_rate",
            return_value=-0.05,
        ):
            result = early_entry_check(db)

        assert result["skipped_gapdown"] >= 1
        assert result["entered"] == 0
