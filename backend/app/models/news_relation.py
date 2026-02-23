from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NewsStockRelation(Base):
    __tablename__ = "news_stock_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey("news_articles.id"), nullable=False)
    stock_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=True)
    sector_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sectors.id"), nullable=True)
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'keyword' | 'ai_classified'
    relevance: Mapped[str] = mapped_column(String(20), nullable=False)  # 'direct' | 'indirect'

    news = relationship("NewsArticle", back_populates="relations")
    stock = relationship("Stock", back_populates="news_relations")
    sector = relationship("Sector", back_populates="news_relations")
