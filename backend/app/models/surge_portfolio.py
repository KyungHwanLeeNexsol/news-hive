"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 데이터 모델.

SPEC-AI-012가 생성한 FundSignal(signal_type="surge_candidate") 시그널 기반의
4번째 독립 모의투자 포트폴리오 모델.

virtual_*/vip_*/ks200_* 테이블과 완전히 분리된 독립 운영.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SurgePortfolio(Base):
    # @MX:ANCHOR: [AUTO] SurgePortfolio 단일 인스턴스 — 현금 잔고 중앙 관리 지점
    # @MX:REASON: [AUTO] 매수/매도 시 current_cash 직접 차감/증가하는 공유 상태, execute_buy_orders, execute_sell, get_portfolio_stats 등 다수 컴포넌트 참조
    # @MX:SPEC: SPEC-AI-013
    """급등예측 모의투자 포트폴리오 (단일 인스턴스, id=1, 초기자본 5,000,000원)."""

    __tablename__ = "surge_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 초기 자본금 — 5,000,000 KRW (고정)
    initial_capital: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, server_default="5000000"
    )
    # 현재 가용 현금 — 매수 시 차감, 매도 시 증가
    current_cash: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, server_default="5000000"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    trades = relationship("SurgeTrade", back_populates="portfolio")


class SurgeTrade(Base):
    # @MX:NOTE: [AUTO] exit_reason 값: "stop_loss"(-8%), "take_profit"(+15%), "max_holding_period"(5거래일), "manual"
    # @MX:SPEC: SPEC-AI-013
    """급등예측 매매 기록.

    매수 시 is_open=True, 종료 시 is_open=False + exit 정보 기록.
    손절(-8%), 익절(+15%), 최대 보유 기간(5거래일) 조건으로 종료.
    """

    __tablename__ = "surge_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("surge_portfolios.id"), nullable=False
    )
    # 빠른 조회를 위한 비정규화 필드
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 매수 트리거가 된 FundSignal ID (역추적용)
    signal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fund_signals.id"), nullable=True
    )
    entry_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 종료 정보
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # "stop_loss" | "take_profit" | "max_holding_period" | "manual"
    exit_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 진입 시점의 시그널 확률 스냅샷 (역분석용)
    surge_probability_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    portfolio = relationship("SurgePortfolio", back_populates="trades")
