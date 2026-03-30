"""가상 포트폴리오 및 가상 매매 모델."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VirtualPortfolio(Base):
    """가상 포트폴리오 (페이퍼 트레이딩 계좌)."""
    __tablename__ = "virtual_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), default="기본 포트폴리오")
    initial_capital: Mapped[int] = mapped_column(Integer, default=100_000_000)  # 초기 자본금 (1억원)
    current_cash: Mapped[int] = mapped_column(Integer, default=100_000_000)  # 현재 현금
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_defensive_mode: Mapped[bool] = mapped_column(Boolean, default=False)  # 방어 모드 활성화 여부
    defensive_mode_entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )  # 방어 모드 진입 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trades = relationship("VirtualTrade", back_populates="portfolio")
    snapshots = relationship("PortfolioSnapshot", back_populates="portfolio")


class VirtualTrade(Base):
    """가상 매매 기록."""
    __tablename__ = "virtual_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("virtual_portfolios.id"), nullable=False)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)
    signal_id: Mapped[int] = mapped_column(Integer, ForeignKey("fund_signals.id"), nullable=False)

    # 진입 정보
    entry_price: Mapped[int] = mapped_column(Integer, nullable=False)  # 진입가
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)  # 수량
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # 'long' | 'short'
    entry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 청산 정보
    exit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 청산가
    exit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # exit_reason: target_hit, stop_loss, timeout, signal_sell, manual

    # 성과
    pnl: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 손익 (원)
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 수익률 (%)

    # 시그널 조건
    target_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True)  # 포지션 오픈 여부

    portfolio = relationship("VirtualPortfolio", back_populates="trades")
    stock = relationship("Stock")
    signal = relationship("FundSignal")


class PortfolioSnapshot(Base):
    """일일 포트폴리오 스냅샷 (성과 추적)."""
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("virtual_portfolios.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 자산 현황
    total_value: Mapped[int] = mapped_column(Integer, nullable=False)  # 총 자산 (현금+평가액)
    cash: Mapped[int] = mapped_column(Integer, nullable=False)
    positions_value: Mapped[int] = mapped_column(Integer, nullable=False)  # 보유 종목 평가액
    open_positions: Mapped[int] = mapped_column(Integer, default=0)  # 오픈 포지션 수

    # 성과 지표
    daily_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 일일 수익률
    cumulative_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 누적 수익률

    portfolio = relationship("VirtualPortfolio", back_populates="snapshots")
