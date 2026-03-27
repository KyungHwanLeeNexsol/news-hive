from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NewsStockRelation(Base):
    __tablename__ = "news_stock_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey("news_articles.id"), nullable=False)
    stock_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=True)
    sector_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sectors.id"), nullable=True)
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'keyword' | 'ai_classified' | 'propagated'
    relevance: Mapped[str] = mapped_column(String(20), nullable=False)  # 'direct' | 'indirect'
    # 전파 관련 필드
    relation_sentiment: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 'positive' | 'negative' | 'neutral'
    propagation_type: Mapped[str | None] = mapped_column(String(10), nullable=True, default="direct")  # 'direct' | 'propagated'
    impact_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    news = relationship("NewsArticle", back_populates="relations")
    stock = relationship("Stock", back_populates="news_relations")
    sector = relationship("Sector", back_populates="news_relations")
