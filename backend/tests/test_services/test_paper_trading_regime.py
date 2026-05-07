"""SPEC-AI-015: paper_trading 레짐 통합 특성화 테스트.

[DDD PRESERVE] 기존 paper_trading.py의 동작을 캡처하는 특성화 테스트.
이 테스트들은 T-007, T-008 수정 이후에도 반드시 PASS해야 한다.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models.fund_signal import FundSignal
from app.models.virtual_portfolio import VirtualPortfolio, VirtualTrade
from app.services.paper_trading import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TARGET_PCT,
    MAX_DAILY_TRADES,
    _position_pct_by_confidence,
)


# ---------------------------------------------------------------------------
# 특성화 테스트: _position_pct_by_confidence 기존 동작 캡처
# ---------------------------------------------------------------------------

class TestCharacterizePositionPctByConfidence:
    """_position_pct_by_confidence 경계값 동작 특성화.

    T-007 수정 후에도 db=None(기본값)일 때 동일한 결과를 반환해야 한다.
    """

    def test_characterize_low_confidence_returns_5pct(self):
        """confidence=0.50 → 0.05 (db=None, 기존 동작)."""
        result = _position_pct_by_confidence(0.50)
        assert result == 0.05

    def test_characterize_medium_low_confidence_returns_10pct(self):
        """confidence=0.60 → 0.10 (db=None, 기존 동작)."""
        result = _position_pct_by_confidence(0.60)
        assert result == 0.10

    def test_characterize_medium_high_confidence_returns_15pct(self):
        """confidence=0.70 → 0.15 (db=None, 기존 동작)."""
        result = _position_pct_by_confidence(0.70)
        assert result == 0.15

    def test_characterize_high_confidence_returns_20pct(self):
        """confidence=0.80 → 0.20 (db=None, 기존 동작)."""
        result = _position_pct_by_confidence(0.80)
        assert result == 0.20

    def test_characterize_max_confidence_returns_20pct(self):
        """confidence=0.99 → 0.20 (최대 상한, db=None, 기존 동작)."""
        result = _position_pct_by_confidence(0.99)
        assert result == 0.20

    def test_characterize_below_60_returns_5pct(self):
        """confidence=0.59 → 0.05 (0.60 미만은 5%, db=None)."""
        result = _position_pct_by_confidence(0.59)
        assert result == 0.05

    def test_characterize_below_70_returns_10pct(self):
        """confidence=0.65 → 0.10 (0.60 이상 0.70 미만은 10%, db=None)."""
        result = _position_pct_by_confidence(0.65)
        assert result == 0.10

    def test_characterize_below_80_returns_15pct(self):
        """confidence=0.79 → 0.15 (0.70 이상 0.80 미만은 15%, db=None)."""
        result = _position_pct_by_confidence(0.79)
        assert result == 0.15

    def test_backward_compat_0_85(self):
        """T-007 이후에도: _position_pct_by_confidence(0.85) == 0.20."""
        result = _position_pct_by_confidence(0.85)
        assert result == 0.20

    def test_backward_compat_0_65(self):
        """T-007 이후에도: _position_pct_by_confidence(0.65) == 0.10."""
        result = _position_pct_by_confidence(0.65)
        assert result == 0.10


# ---------------------------------------------------------------------------
# 특성화 테스트: 일일 매수 한도 = 5 (MAX_DAILY_TRADES)
# ---------------------------------------------------------------------------

class TestCharacterizeMaxDailyTrades:
    """일일 매수 한도 상수 특성화.

    T-008 이전의 기본값 = 5.
    """

    def test_characterize_max_daily_trades_is_5(self):
        """MAX_DAILY_TRADES 기본값 = 5."""
        assert MAX_DAILY_TRADES == 5


# ---------------------------------------------------------------------------
# 특성화 테스트: 기본 목표가/손절가 비율
# ---------------------------------------------------------------------------

class TestCharacterizeDefaultTpSl:
    """기본 TP/SL 비율 특성화.

    T-008 수정 이후에도 상수값은 유지된다 (fallback 역할).
    """

    def test_characterize_default_target_pct_is_15pct(self):
        """DEFAULT_TARGET_PCT = 0.15 (기본 +15% 익절)."""
        assert DEFAULT_TARGET_PCT == 0.15

    def test_characterize_default_stop_loss_pct_is_5pct(self):
        """DEFAULT_STOP_LOSS_PCT = 0.05 (기본 -5% 손절)."""
        assert DEFAULT_STOP_LOSS_PCT == 0.05
