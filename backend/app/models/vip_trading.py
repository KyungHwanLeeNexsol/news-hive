"""VIP투자자문 추종 매매 모델.

SPEC-VIP-001: VIP투자자문 지분 추종 자동매매 시스템의 데이터 모델.
기존 virtual_portfolio, paper_trading과 완전히 분리된 독립 테이블.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VIPDisclosure(Base):
    # @MX:ANCHOR: VIP 공시 원본 데이터 — 매매 트리거의 단일 진실 공급원
    # @MX:REASON: 스케줄러, 매매 서비스, API 등 3개 이상 컴포넌트가 직접 참조
    # @MX:SPEC: SPEC-VIP-001 REQ-VIP-001
    """VIP투자자문 대량보유 공시 기록 테이블."""

    __tablename__ = "vip_disclosures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # DART 접수번호 — 중복 수집 방지용 unique 키
    rcept_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    corp_name: Mapped[str] = mapped_column(String(100), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    stock_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=True)
    # 보유비율 (%) — 보고서 본문 XML 파싱으로 추출
    stake_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 평균취득단가 (원) — 보고서 본문 XML 파싱으로 추출
    avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # accumulate: 5% 이상 신규/추가 취득, reduce: 처분, below5: 5% 미만, unknown: 미분류
    disclosure_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # YYYYMMDD 형식의 접수일
    rcept_dt: Mapped[str] = mapped_column(String(10), nullable=False)
    # 공시자명 — "VIP투자자문" 포함 여부로 필터링
    flr_nm: Mapped[str] = mapped_column(String(200), nullable=False)
    # 원본 보고서명
    report_nm: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 원본 XML (디버깅 및 백테스트용 보존)
    raw_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 매매 처리 완료 여부 — False: 미처리, True: 매매 실행 완료 또는 스킵 확정
    processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    stock = relationship("Stock", backref="vip_disclosures")
    trades = relationship("VIPTrade", back_populates="disclosure")


class VIPPortfolio(Base):
    # @MX:ANCHOR: VIP 포트폴리오 단일 인스턴스 — 현금 잔고의 중앙 관리 지점
    # @MX:REASON: 매수/매도 시 current_cash 직접 차감/증가하는 공유 상태
    # @MX:SPEC: SPEC-VIP-001 REQ-VIP-005
    """VIP 추종 포트폴리오 (단일 인스턴스 운영)."""

    __tablename__ = "vip_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), default="VIP 추종 포트폴리오")
    # 초기 자본금 — 5천만원
    initial_capital: Mapped[int] = mapped_column(Integer, default=50_000_000)
    # 현재 현금 잔고 — 매수 시 차감, 매도 시 증가
    current_cash: Mapped[int] = mapped_column(Integer, default=50_000_000)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trades = relationship("VIPTrade", back_populates="portfolio")


class VIPTrade(Base):
    # @MX:NOTE: split_sequence 1=1차매수, 2=2차매수 — 분할 매수 추적용
    # @MX:SPEC: SPEC-VIP-001 REQ-VIP-002 REQ-VIP-004
    """VIP 추종 매매 기록.

    분할 매수(1차/2차), 부분 익절, 전량 매도를 단일 레코드로 추적한다.
    quantity는 현재 보유 수량 — 부분 매도 후 감소한다.
    """

    __tablename__ = "vip_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vip_portfolios.id"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)
    vip_disclosure_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vip_disclosures.id"), nullable=False
    )
    # 1=1차 매수, 2=2차 매수
    split_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[int] = mapped_column(Integer, nullable=False)
    # 현재 보유 수량 — 부분 매도 후 차감
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 청산 정보 (전량 매도 시 기록)
    exit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # vip_sell: VIP 5% 미만 공시, profit_lock: 50% 익절, manual: 수동 청산
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # 실현 손익 (전량 청산 시 계산)
    pnl: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 50% 수익률 달성 시 30% 부분 매도 완료 여부 — 포지션당 1회만 트리거
    partial_sold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    portfolio = relationship("VIPPortfolio", back_populates="trades")
    stock = relationship("Stock", backref="vip_trades")
    disclosure = relationship("VIPDisclosure", back_populates="trades")
