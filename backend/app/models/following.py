"""기업 팔로잉 시스템 모델 (SPEC-FOLLOW-001).

사용자가 관심 기업을 팔로잉하고 AI 생성 키워드로 알림을 받는 시스템.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# @MX:ANCHOR: [AUTO] StockFollowing — CRUD, 키워드 매처, 알림 발송 3개 이상 호출자가 참조
# @MX:REASON: 팔로잉 테이블은 키워드 매처(scheduler), 라우터 CRUD, 알림 발송에서 모두 조회됨
class StockFollowing(Base):
    """사용자-종목 팔로잉 관계 모델."""

    __tablename__ = "stock_followings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # 동일 사용자가 동일 종목을 중복 팔로잉하지 못하도록 제약
        UniqueConstraint("user_id", "stock_id", name="uq_stock_following"),
    )

    # 관계
    user = relationship("User", back_populates="followings")
    stock = relationship("Stock")
    keywords = relationship(
        "StockKeyword", back_populates="following", cascade="all, delete-orphan"
    )


class StockKeyword(Base):
    """팔로잉 종목에 대한 모니터링 키워드 모델.

    AI 자동 생성 또는 사용자 수동 추가 키워드를 저장한다.
    카테고리: product(제품/서비스), competitor(경쟁사), upstream(공급망), market(시장), custom(사용자 정의)
    """

    __tablename__ = "stock_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    following_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stock_followings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    # 키워드 카테고리: product|competitor|upstream|market|custom
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    # 생성 출처: ai(AI 자동 생성)|manual(사용자 수동 추가)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # 동일 팔로잉에 동일 키워드 중복 방지
        UniqueConstraint("following_id", "keyword", name="uq_stock_keyword"),
    )

    # 관계
    following = relationship("StockFollowing", back_populates="keywords")


class KeywordNotification(Base):
    """키워드 매칭 알림 발송 이력 모델.

    동일 (user_id, content_type, content_id) 조합으로 중복 알림을 방지한다.
    """

    __tablename__ = "keyword_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 매칭된 키워드 (삭제 시 NULL로 유지)
    keyword_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stock_keywords.id", ondelete="SET NULL"), nullable=True
    )
    # 콘텐츠 유형: news|disclosure|report
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content_title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 발송 채널: telegram|web_push
    channel: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        # 동일 사용자에게 동일 콘텐츠 중복 알림 방지
        UniqueConstraint("user_id", "content_type", "content_id", name="uq_keyword_notification"),
    )

    # 관계
    user = relationship("User", back_populates="notifications")
