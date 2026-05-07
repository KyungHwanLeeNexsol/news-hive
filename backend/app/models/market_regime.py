"""시장 레짐 모델.

SPEC-AI-015: 시장 국면(상승장/하락장/횡보장) 분류 및 파라미터 관리.
KOSPI 5일 수익률과 20일 이동평균 위치를 기반으로 레짐을 분류하고,
각 레짐별 투자 파라미터를 제공한다.
"""

import datetime
import enum

from sqlalchemy import Date, DateTime, Enum, Float, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketRegimeEnum(str, enum.Enum):
    """시장 레짐 유형."""
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"


class MarketRegime(Base):
    """시장 레짐 일별 분류 데이터."""
    __tablename__ = "market_regimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # UNIQUE: 날짜당 하나의 레짐만 허용 (race condition 방지)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, unique=True)
    regime: Mapped[MarketRegimeEnum] = mapped_column(
        Enum(MarketRegimeEnum, name="market_regime_type"),
        nullable=False,
    )
    # KOSPI 5일 수익률 (%)
    kospi_5d_return: Mapped[float] = mapped_column(Float, nullable=False)
    # KOSPI 20일 이동평균 대비 현재가 위치 (%)
    kospi_20d_ma_position: Mapped[float] = mapped_column(Float, nullable=False)
    # 변동성 지수 (선택적)
    volatility_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 분류 신뢰도 (0.0 ~ 1.0)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_market_regimes_date", "date"),
    )
