"""market_context 모듈 테스트.

SPEC-AI-002 REQ-AI-020: 시장 변동성 기반 포지션 사이징.
SPEC-AI-002 REQ-AI-024: 원자재 연관 종목 크로스 검증.
"""

from datetime import datetime, timezone

import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.orm import Session

from app.models.commodity import Commodity, CommodityPrice, SectorCommodityRelation
from app.services.market_context import (
    COMMODITY_DIVERGENCE_CONFIDENCE_PENALTY,
    COMMODITY_DIVERGENCE_DAYS,
    apply_commodity_adjustment,
    calculate_volatility_level,
    check_commodity_divergence,
    format_commodity_context_for_briefing,
    format_volatility_for_briefing,
    get_commodity_trend,
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


# ---------------------------------------------------------------------------
# REQ-AI-024: 원자재 크로스 검증 테스트
# ---------------------------------------------------------------------------

@pytest.fixture
def make_commodity(db: Session):
    """Commodity 팩토리."""
    _counter = 0

    def _factory(
        symbol: str = "CL=F",
        name_ko: str = "WTI 원유",
        name_en: str = "WTI Crude Oil",
        category: str = "energy",
        **kwargs,
    ) -> Commodity:
        nonlocal _counter
        _counter += 1
        defaults = {
            "symbol": symbol if _counter == 1 else f"{symbol}_{_counter}",
            "name_ko": name_ko,
            "name_en": name_en,
            "category": category,
            "unit": "barrel",
            "currency": "USD",
        }
        defaults.update(kwargs)
        commodity = Commodity(**defaults)
        db.add(commodity)
        db.flush()
        return commodity

    return _factory


@pytest.fixture
def make_commodity_price(db: Session):
    """CommodityPrice 팩토리."""
    _counter = 0

    def _factory(
        commodity_id: int,
        price: float = 70.0,
        change_pct: float | None = None,
        **kwargs,
    ) -> CommodityPrice:
        nonlocal _counter
        _counter += 1
        defaults = {
            "commodity_id": commodity_id,
            "price": price,
            "change_pct": change_pct,
            "source": "test",
        }
        defaults.update(kwargs)
        record = CommodityPrice(**defaults)
        db.add(record)
        db.flush()
        return record

    return _factory


@pytest.fixture
def make_sector_commodity_relation(db: Session):
    """SectorCommodityRelation 팩토리."""

    def _factory(
        sector_id: int,
        commodity_id: int,
        correlation_type: str = "positive",
    ) -> SectorCommodityRelation:
        rel = SectorCommodityRelation(
            sector_id=sector_id,
            commodity_id=commodity_id,
            correlation_type=correlation_type,
        )
        db.add(rel)
        db.flush()
        return rel

    return _factory


class TestGetCommodityTrend:
    """get_commodity_trend 유닛 테스트."""

    def test_no_relations_returns_empty(self, db: Session, make_sector) -> None:
        """섹터-원자재 매핑 없음 → 빈 리스트."""
        sector = make_sector()
        result = get_commodity_trend(db, sector.id)
        assert result == []

    def test_returns_commodity_prices(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """매핑된 원자재의 가격 추세를 반환한다."""
        sector = make_sector(name="에너지")
        commodity = make_commodity(symbol="CL=F", name_ko="WTI 원유")
        make_sector_commodity_relation(sector.id, commodity.id, "positive")

        # 5일 가격 데이터
        for i in range(5):
            make_commodity_price(commodity.id, price=70.0 - i, change_pct=-1.0)

        result = get_commodity_trend(db, sector.id, days=5)
        assert len(result) == 1
        assert result[0]["commodity_name"] == "WTI 원유"
        assert result[0]["symbol"] == "CL=F"
        assert len(result[0]["prices"]) == 5
        assert result[0]["consecutive_decline"] == 5

    def test_consecutive_decline_counting(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """연속 하락일 수를 정확히 계산한다."""
        sector = make_sector(name="철강")
        commodity = make_commodity(symbol="HG=F", name_ko="구리")
        make_sector_commodity_relation(sector.id, commodity.id)

        # 최신 3일 하락, 이후 상승
        make_commodity_price(commodity.id, price=68.0, change_pct=-0.5)
        make_commodity_price(commodity.id, price=69.0, change_pct=-1.0)
        make_commodity_price(commodity.id, price=70.0, change_pct=-0.3)
        make_commodity_price(commodity.id, price=71.0, change_pct=0.5)
        make_commodity_price(commodity.id, price=72.0, change_pct=1.0)

        result = get_commodity_trend(db, sector.id, days=5)
        assert result[0]["consecutive_decline"] == 3


class TestCheckCommodityDivergence:
    """check_commodity_divergence 유닛 테스트 (AC-024-1)."""

    def test_non_buy_signal_no_divergence(self, db: Session, make_sector) -> None:
        """매수가 아닌 시그널 → 역행 검사 불필요."""
        sector = make_sector()
        result = check_commodity_divergence(db, sector.id, "sell")
        assert result["divergence"] is False
        assert result["confidence_adjustment"] == 0.0

    def test_hold_signal_no_divergence(self, db: Session, make_sector) -> None:
        """hold 시그널 → 역행 검사 불필요."""
        sector = make_sector()
        result = check_commodity_divergence(db, sector.id, "hold")
        assert result["divergence"] is False

    def test_no_commodity_data_no_divergence(self, db: Session, make_sector) -> None:
        """원자재 데이터 없음 → 경고 없이 통과."""
        sector = make_sector()
        result = check_commodity_divergence(db, sector.id, "buy")
        assert result["divergence"] is False
        assert result["confidence_adjustment"] == 0.0

    def test_buy_with_5day_decline_triggers_divergence(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """매수 + 원자재 5일 연속 하락 → commodity_divergence + confidence -0.1."""
        sector = make_sector(name="정유")
        commodity = make_commodity(symbol="CL=F_div", name_ko="WTI 원유")
        make_sector_commodity_relation(sector.id, commodity.id, "positive")

        # 5일 연속 하락
        for i in range(5):
            make_commodity_price(commodity.id, price=70.0 - i, change_pct=-1.5)

        result = check_commodity_divergence(db, sector.id, "buy")
        assert result["divergence"] is True
        assert result["warning"] == "commodity_divergence"
        assert result["confidence_adjustment"] == COMMODITY_DIVERGENCE_CONFIDENCE_PENALTY
        assert len(result["details"]) == 1
        assert result["details"][0]["name"] == "WTI 원유"

    def test_buy_with_partial_decline_no_divergence(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """매수 + 원자재 3일만 하락(5일 미만) → 역행 없음."""
        sector = make_sector(name="화학")
        commodity = make_commodity(symbol="NG=F", name_ko="천연가스")
        make_sector_commodity_relation(sector.id, commodity.id, "positive")

        # 3일 하락 + 2일 상승
        make_commodity_price(commodity.id, price=67.0, change_pct=-1.0)
        make_commodity_price(commodity.id, price=68.0, change_pct=-0.5)
        make_commodity_price(commodity.id, price=69.0, change_pct=-0.8)
        make_commodity_price(commodity.id, price=70.0, change_pct=0.5)
        make_commodity_price(commodity.id, price=71.0, change_pct=1.0)

        result = check_commodity_divergence(db, sector.id, "buy")
        assert result["divergence"] is False

    def test_negative_correlation_buy_with_rise_triggers_divergence(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """역상관 원자재: 매수 + 원자재 5일 연속 상승 → 역행."""
        sector = make_sector(name="항공")
        commodity = make_commodity(symbol="CL=F_neg", name_ko="항공유")
        make_sector_commodity_relation(sector.id, commodity.id, "negative")

        # 5일 연속 상승 (역상관이면 이것이 역행)
        for i in range(5):
            make_commodity_price(commodity.id, price=70.0 + i, change_pct=1.5)

        result = check_commodity_divergence(db, sector.id, "buy")
        assert result["divergence"] is True
        assert result["warning"] == "commodity_divergence"


class TestApplyCommodityAdjustment:
    """apply_commodity_adjustment 유닛 테스트."""

    def test_divergence_reduces_confidence(self) -> None:
        """역행 발생 시 confidence -0.1."""
        divergence = {
            "divergence": True,
            "confidence_adjustment": -0.1,
        }
        result = apply_commodity_adjustment(0.8, divergence)
        assert result == pytest.approx(0.7)

    def test_no_divergence_no_change(self) -> None:
        """역행 없음 → confidence 변경 없음."""
        no_divergence = {
            "divergence": False,
            "confidence_adjustment": 0.0,
        }
        result = apply_commodity_adjustment(0.8, no_divergence)
        assert result == 0.8

    def test_confidence_floor_at_zero(self) -> None:
        """confidence는 최소 0.0."""
        divergence = {
            "divergence": True,
            "confidence_adjustment": -0.1,
        }
        result = apply_commodity_adjustment(0.05, divergence)
        assert result == 0.0


class TestFormatCommodityContextForBriefing:
    """format_commodity_context_for_briefing 유닛 테스트."""

    def test_empty_sector_ids_returns_empty(self, db: Session) -> None:
        """빈 섹터 리스트 → 빈 문자열."""
        result = format_commodity_context_for_briefing(db, [])
        assert result == ""

    def test_no_commodity_data_returns_empty(self, db: Session, make_sector) -> None:
        """원자재 데이터 없는 섹터 → 빈 문자열."""
        sector = make_sector()
        result = format_commodity_context_for_briefing(db, [sector.id])
        assert result == ""

    def test_formats_commodity_trends(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """원자재 가격 동향을 텍스트로 변환한다."""
        sector = make_sector(name="에너지")
        commodity = make_commodity(symbol="CL=F_fmt", name_ko="WTI 원유")
        make_sector_commodity_relation(sector.id, commodity.id)

        for i in range(5):
            make_commodity_price(commodity.id, price=70.0 + i, change_pct=0.5)

        result = format_commodity_context_for_briefing(db, [sector.id])
        assert "원자재 가격 동향" in result
        assert "WTI 원유" in result

    def test_shows_warning_for_long_decline(
        self,
        db: Session,
        make_sector,
        make_commodity,
        make_commodity_price,
        make_sector_commodity_relation,
    ) -> None:
        """5일 이상 연속 하락 시 경고 표시."""
        sector = make_sector(name="정유")
        commodity = make_commodity(symbol="CL=F_warn", name_ko="WTI 원유")
        make_sector_commodity_relation(sector.id, commodity.id)

        for i in range(5):
            make_commodity_price(commodity.id, price=70.0 - i, change_pct=-2.0)

        result = format_commodity_context_for_briefing(db, [sector.id])
        assert "경고" in result
        assert "연속 하락" in result
