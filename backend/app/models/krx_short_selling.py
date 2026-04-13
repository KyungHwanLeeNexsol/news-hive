"""KRX 공매도 잔고 데이터 모델.

공매도 잔고 급증 → 기관의 하락 베팅 강화 → 매도 경고 시그널
공매도 잔고 감소 → 공매도 청산(숏커버링) → 반등 가능성
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class KrxShortSelling(Base):
    """KRX 종목별 공매도 잔고 일별 데이터."""

    __tablename__ = "krx_short_selling"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)

    # 당일 공매도 거래 데이터
    short_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)       # 공매도 거래량
    short_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)       # 공매도 거래대금 (원)

    # 누적 잔고 데이터
    short_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)      # 공매도 잔고 (주수)
    short_balance_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 공매도 잔고 금액 (원)
    short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)           # 공매도 비율 (%)

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stock = relationship("Stock", backref="short_selling_records")

    __table_args__ = (
        UniqueConstraint("stock_id", "trade_date", name="uq_krx_short_stock_date"),
    )
