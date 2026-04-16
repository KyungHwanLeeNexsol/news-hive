"""KOSPI 200 스토캐스틱+이격도 자동매매 모델.

SPEC-KS200-001: 기존 AI 펀드(virtual_portfolios), VIP 추종(vip_portfolios)과
완전히 독립된 3번째 매매 모델의 데이터 모델.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class KS200Portfolio(Base):
    # @MX:ANCHOR: KS200 포트폴리오 단일 인스턴스 — 현금 잔고의 중앙 관리 지점
    # @MX:REASON: 매수/매도 시 current_cash 직접 차감/증가하는 공유 상태, 3개 이상 컴포넌트 참조
    # @MX:SPEC: SPEC-KS200-001
    """KOSPI 200 스토캐스틱+이격도 포트폴리오 (단일 인스턴스 운영)."""

    __tablename__ = "ks200_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(100), default="KOSPI200 스토캐스틱+이격도"
    )
    # 초기 자본금 — 1억원
    initial_capital: Mapped[int] = mapped_column(Integer, default=100_000_000)
    # 현재 현금 잔고 — 매수 시 차감, 매도 시 증가
    current_cash: Mapped[int] = mapped_column(Integer, default=100_000_000)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trades = relationship("KS200Trade", back_populates="portfolio")


class KS200Trade(Base):
    # @MX:NOTE: exit_reason — "signal_sell" 신호 청산, "manual" 수동 청산만 존재 (손절/익절 없음)
    # @MX:SPEC: SPEC-KS200-001
    """KS200 매매 기록.

    매수 시 is_open=True, 청산 시 is_open=False + exit 정보 기록.
    손절/익절 조건 없음 — 매도 신호 또는 수동 청산만.
    """

    __tablename__ = "ks200_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ks200_portfolios.id"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id"), nullable=False
    )
    # 빠른 조회를 위한 비정규화 필드
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    entry_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 청산 정보
    exit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "signal_sell": 신호 청산, "manual": 수동 청산
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # 분할 매수 차수: 1 = 1차 매수(50%), 2 = 2차 추가 매수(나머지 50%)
    tranche: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    # 실현 손익 (청산 시 계산)
    pnl: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    portfolio = relationship("KS200Portfolio", back_populates="trades")
    stock = relationship("Stock", backref="ks200_trades")


class KS200Signal(Base):
    # @MX:ANCHOR: KS200 신호 레코드 — 스캔과 실행 사이의 비동기 브릿지
    # @MX:REASON: run_daily_signal_scan, execute_pending_signals, router 3개 컴포넌트에서 참조
    # @MX:SPEC: SPEC-KS200-001
    """KS200 매매 신호 기록.

    signal_type: "buy" 또는 "sell"
    executed=False: 미실행 신호 (execute_pending_signals 처리 대상)
    executed=True: 실행 완료 또는 조건 불충족으로 스킵
    """

    __tablename__ = "ks200_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stocks.id"), nullable=True
    )
    # "buy" 또는 "sell"
    signal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # 신호 발생 시점의 %K_slow 값
    stoch_k: Mapped[float] = mapped_column(Float, nullable=False)
    # 신호 발생 시점의 이격도 값
    disparity: Mapped[float] = mapped_column(Float, nullable=False)
    price_at_signal: Mapped[int] = mapped_column(Integer, nullable=False)
    executed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    signal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    stock = relationship("Stock", backref="ks200_signals")
