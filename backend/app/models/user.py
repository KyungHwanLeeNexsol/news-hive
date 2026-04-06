from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """사용자 인증 모델 (이메일/비밀번호 기반)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 이메일 인증 완료 여부
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 관계
    verification_codes = relationship(
        "EmailVerificationCode", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    watchlist = relationship(
        "UserWatchlist", back_populates="user", cascade="all, delete-orphan"
    )
    preferences = relationship(
        "UserPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    push_subscriptions = relationship(
        "PushSubscription", back_populates="user", cascade="all, delete-orphan"
    )

    # 텔레그램 연동 chat ID (연동 시 저장)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    followings = relationship(
        "StockFollowing", back_populates="user", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "KeywordNotification", back_populates="user", cascade="all, delete-orphan"
    )


class EmailVerificationCode(Base):
    """이메일 인증 URL 토큰 모델 (링크 클릭 방식)."""

    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # URL-safe 랜덤 토큰 (secrets.token_urlsafe(32) — 43자)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 사용 완료 여부
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User", back_populates="verification_codes")


class RefreshToken(Base):
    """JWT 리프레시 토큰 모델 (사용자별 다중 발급 지원)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 토큰 값 (unique 인덱스로 빠른 조회)
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 명시적 폐기 여부 (로그아웃, 비밀번호 변경 시 true)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="refresh_tokens")


class UserWatchlist(Base):
    """사용자 관심 종목 서버사이드 저장 모델."""

    __tablename__ = "user_watchlists"

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
        # 동일 사용자가 동일 종목을 중복 추가하지 못하도록 제약
        UniqueConstraint("user_id", "stock_id", name="uq_user_watchlist"),
    )

    user = relationship("User", back_populates="watchlist")
    stock = relationship("Stock")


class UserPreferences(Base):
    """사용자 알림 및 관심 설정 모델 (사용자당 1개)."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # 전체 푸시 알림 활성화 여부
    notification_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 관심 섹터 ID 목록 (JSON 배열)
    followed_sector_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 관심 종목 ID 목록 (JSON 배열)
    followed_stock_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 알림 임계값: "info" | "warning" | "danger"
    alert_level_threshold: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning"
    )
    # 웹 푸시 알림 활성화 여부
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="preferences")


class PushSubscription(Base):
    """Web Push 구독 정보 모델 (사용자당 다중 디바이스 지원)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Web Push 구독 엔드포인트 URL
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # VAPID 암호화 키
    p256dh_key: Mapped[str] = mapped_column(Text, nullable=False)
    auth_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User", back_populates="push_subscriptions")
