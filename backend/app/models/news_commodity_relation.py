from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NewsCommodityRelation(Base):
    """뉴스-원자재 매핑 테이블 (뉴스가 어떤 원자재에 영향을 주는지)."""
    __tablename__ = "news_commodity_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False
    )
    commodity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("commodities.id"), nullable=False
    )
    relevance: Mapped[str] = mapped_column(String(20), nullable=False)  # 'direct' / 'indirect'
    impact_direction: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 'price_up'/'price_down'/'supply_disruption'/'demand_change'/'policy_change'/'neutral'
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'keyword' / 'ai_classified'

    news = relationship("NewsArticle")
    commodity = relationship("Commodity")
