"""뉴스-가격 반응 추적 모델.

뉴스 기사 발행 시점의 주가 스냅샷과 이후 1일/5일 가격 변동을 기록하여
뉴스가 주가에 미치는 영향을 추적한다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NewsPriceImpact(Base):
    """뉴스 발행 시점 가격 스냅샷 + 사후 가격 반응 추적."""
    __tablename__ = "news_price_impact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK: 뉴스 삭제(7일 정책) 시 SET NULL → impact 레코드는 90일간 유지
    news_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("news_articles.id", ondelete="SET NULL"), nullable=True
    )
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("news_stock_relations.id", ondelete="SET NULL"), nullable=True
    )

    # 뉴스 발행 시점 가격
    price_at_news: Mapped[float] = mapped_column(Float, nullable=False)

    # 1일 후 가격 반응
    price_after_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_1d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 5일 후 가격 반응
    price_after_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_5d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 타임스탬프
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    backfill_1d_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    backfill_5d_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    news = relationship("NewsArticle")
    stock = relationship("Stock")
