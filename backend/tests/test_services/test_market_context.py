"""market_context 모듈 테스트.

SPEC-AI-002 REQ-AI-020: 시장 변동성 기반 포지션 사이징.
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.services.market_context import (
    calculate_volatility_level,
    format_volatility_for_briefing,
    get_market_volatility,
)


class TestCalculateVolatilityLevel:
    """calculate_volatility_level 유닛 테스트."""

    def test_empty_returns_normal_default(self) -> None:
        """데이터 없음 → graceful degradation, normal 반환."""
        result = calculate_volatility_level([])
        assert result["volatility_level"] == "normal"
        assert result["weight_multiplier"] == 1.0
        assert result["confidence_adjustment"] == 0.0
        assert result["tags"] == []

    def test_insufficient_data_returns_default(self) -> None:
        """5일 미만 데이터 → 기본값 반환."""
        result = calculate_volatility_level([0.5, -0.3, 0.1])
        assert result["volatility_level"] == "normal"

    def test_low_volatility(self) -> None:
        """표준편차 < 1% → low."""
        # 20개의 작은 수익률 (표준편차 ≈ 0.3%)
        returns = [0.1, -0.1, 0.2, -0.2, 0.1, -0.1, 0.2, -0.2,
                   0.1, -0.1, 0.2, -0.2, 0.1, -0.1, 0.2, -0.2,
                   0.1, -0.1, 0.2, -0.2]
        result = calculate_volatility_level(returns)
        assert result["volatility_level"] == "low"
        assert result["weight_multiplier"] == 1.0
        assert result["tags"] == []

    def test_normal_volatility(self) -> None:
        """표준편차 1%~2% → normal."""
        # 수익률 분산이 약 1.5% 표준편차가 되도록
        returns = [1.5, -1.5, 1.0, -1.0, 2.0, -2.0, 1.5, -1.5,
                   1.0, -1.0, 1.5, -1.5, 1.0, -1.0, 1.5, -1.5,
                   1.0, -1.0, 1.5, -1.5]
        result = calculate_volatility_level(returns)
        assert result["volatility_level"] == "normal"
        assert result["weight_multiplier"] == 1.0

    def test_high_volatility(self) -> None:
        """표준편차 2%~3% → high, weight_multiplier = 0.7."""
        # 수익률 분산이 약 2.5% 표준편차가 되도록
        returns = [3.0, -3.0, 2.0, -2.0, 3.5, -3.5, 2.5, -2.5,
                   1.5, -1.5, 3.0, -3.0, 2.0, -2.0, 3.5, -3.5,
                   2.5, -2.5, 1.5, -1.5]
        result = calculate_volatility_level(returns)
        assert result["volatility_level"] == "high"
        assert result["weight_multiplier"] == 0.7
        assert "high_volatility_caution" in result["tags"]
        assert result["confidence_adjustment"] == 0.0

    def test_extreme_volatility(self) -> None:
        """표준편차 > 3% → extreme, weight_multiplier = 0.5, confidence -0.15."""
        # 수익률 분산이 약 4% 표준편차가 되도록
        returns = [5.0, -5.0, 4.0, -4.0, 6.0, -6.0, 3.0, -3.0,
                   5.0, -5.0, 4.0, -4.0, 6.0, -6.0, 3.0, -3.0,
                   5.0, -5.0, 4.0, -4.0]
        result = calculate_volatility_level(returns)
        assert result["volatility_level"] == "extreme"
        assert result["weight_multiplier"] == 0.5
        assert result["confidence_adjustment"] == -0.15
        assert "high_volatility_warning" in result["tags"]

    def test_uses_max_20_days(self) -> None:
        """20일 초과 데이터 → 앞 20일만 사용."""
        # 30일 데이터 제공, 앞 20일만 사용
        returns = [0.1] * 30  # 매우 낮은 변동성
        result = calculate_volatility_level(returns)
        assert result["volatility_level"] == "low"
        assert result["volatility_pct"] == 0.0  # 모든 값이 동일

    def test_volatility_pct_is_rounded(self) -> None:
        """volatility_pct는 소수점 2자리로 반올림."""
        returns = [1.0, -1.0, 0.5, -0.5, 1.0, -1.0, 0.5, -0.5,
                   1.0, -1.0]
        result = calculate_volatility_level(returns)
        pct_str = str(result["volatility_pct"])
        # 소수점 이하 최대 2자리
        if "." in pct_str:
            assert len(pct_str.split(".")[1]) <= 2


class TestFormatVolatilityForBriefing:
    """format_volatility_for_briefing 유닛 테스트."""

    def test_normal_level(self) -> None:
        """normal 레벨 → 기본 텍스트."""
        info = {
            "volatility_level": "normal",
            "volatility_pct": 1.5,
            "weight_multiplier": 1.0,
            "tags": [],
        }
        text = format_volatility_for_briefing(info)
        assert "보통" in text
        assert "1.50%" in text

    def test_high_level_shows_weight(self) -> None:
        """high 레벨 → 투자비중 표시."""
        info = {
            "volatility_level": "high",
            "volatility_pct": 2.5,
            "weight_multiplier": 0.7,
            "tags": ["high_volatility_caution"],
        }
        text = format_volatility_for_briefing(info)
        assert "주의" in text
        assert "70%" in text
        assert "보수적" in text

    def test_extreme_level_shows_warning(self) -> None:
        """extreme 레벨 → 경고 텍스트."""
        info = {
            "volatility_level": "extreme",
            "volatility_pct": 4.0,
            "weight_multiplier": 0.5,
            "tags": ["high_volatility_warning"],
            "confidence_adjustment": -0.15,
        }
        text = format_volatility_for_briefing(info)
        assert "경고" in text
        assert "50%" in text
        assert "극단적 변동성" in text


@pytest.mark.asyncio
class TestGetMarketVolatility:
    """get_market_volatility 통합 테스트."""

    async def test_returns_default_on_fetch_failure(self) -> None:
        """데이터 수집 실패 → graceful degradation, normal 반환."""
        with patch(
            "app.services.naver_finance.fetch_stock_price_history",
            new_callable=AsyncMock,
            side_effect=Exception("네트워크 오류"),
        ):
            result = await get_market_volatility()
            assert result["volatility_level"] == "normal"
            assert result["weight_multiplier"] == 1.0

    async def test_returns_default_on_empty_history(self) -> None:
        """빈 히스토리 → 기본값 반환."""
        with patch(
            "app.services.naver_finance.fetch_stock_price_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_market_volatility()
            assert result["volatility_level"] == "normal"
