"""종목토론방(종토방) 데이터 모델 (SPEC-AI-008).

네이버 금융 종목토론방 게시글을 수집·집계하여
역발상 지표 및 과열 경보를 생성한다.

사용처:
  from app.models.stock_forum import StockForumPost, StockForumHourly
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StockForumPost(Base):
    """종목토론방 개별 게시글 레코드."""

    __tablename__ = "stock_forum_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 종목 연결 (삭제된 종목 보호를 위해 SET NULL)
    stock_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("stocks.id", ondelete="SET NULL"),
        nullable=True,
    )
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 게시글 내용 (제목/미리보기 최대 200자)
    content: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    post_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 조회/추천 지표
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    agree_count: Mapped[int] = mapped_column(Integer, default=0)
    disagree_count: Mapped[int] = mapped_column(Integer, default=0)

    # 감성 분류: bullish / bearish / neutral
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")

    # 수집 시각
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 관계
    stock = relationship("Stock", backref="forum_posts")

    __table_args__ = (
        UniqueConstraint("stock_code", "post_date", "nickname", name="uq_forum_post"),
        Index("ix_forum_posts_stock_id", "stock_id"),
        Index("ix_forum_posts_collected_at", "collected_at"),
        Index("ix_forum_posts_stock_code", "stock_code"),
    )


# @MX:ANCHOR: [AUTO] StockForumHourly — fund_manager._gather_forum_sentiment() 및 스케줄러 집계가 이 모델을 참조
# @MX:REASON: 스케줄러 집계 잡 + fund_manager 감성 수집 + 과열 경보 판정 등 3개 이상 호출자가 의존
class StockForumHourly(Base):
    """종목토론방 시간별 집계 메트릭.

    스케줄러가 매 30분마다 upsert하며, fund_manager._gather_forum_sentiment()가 조회한다.
    """

    __tablename__ = "stock_forum_hourly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 종목 연결
    stock_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("stocks.id", ondelete="SET NULL"),
        nullable=True,
    )
    aggregated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 게시글 수 집계
    total_posts: Mapped[int] = mapped_column(Integer, default=0)
    bullish_count: Mapped[int] = mapped_column(Integer, default=0)
    bearish_count: Mapped[int] = mapped_column(Integer, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0)

    # 비율 및 볼륨
    bullish_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    comment_volume: Mapped[int] = mapped_column(Integer, default=0)
    avg_7d_volume: Mapped[float] = mapped_column(Float, default=0.0)

    # 과열/급등 경보
    volume_surge: Mapped[bool] = mapped_column(Boolean, default=False)
    overheating_alert: Mapped[bool] = mapped_column(Boolean, default=False)

    # 관계
    stock = relationship("Stock", backref="forum_hourly")

    __table_args__ = (
        UniqueConstraint("stock_id", "aggregated_at", name="uq_forum_hourly"),
        Index("ix_forum_hourly_stock_id", "stock_id"),
        Index("ix_forum_hourly_aggregated_at", "aggregated_at"),
    )
