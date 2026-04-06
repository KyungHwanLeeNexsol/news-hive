"""증권사 리포트 데이터 모델 (SPEC-FOLLOW-002).

네이버 리서치 센터에서 수집한 증권사 종목분석 리포트를 저장한다.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SecuritiesReport(Base):
    """증권사 종목분석 리포트."""

    __tablename__ = "securities_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 리포트 기본 정보
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # 종목 연결 (stock_code가 매핑되면 stock_id 설정, 없으면 NULL)
    stock_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("stocks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 증권사 정보
    securities_firm: Mapped[str] = mapped_column(String(100), nullable=False)
    opinion: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 매수/중립/매도 등
    target_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 목표주가 (원)

    # 리포트 URL (중복 방지 키)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)

    # 날짜
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 관계
    stock = relationship("Stock", backref="securities_reports")

    __table_args__ = (
        UniqueConstraint("url", name="uq_securities_reports_url"),
        Index("ix_securities_reports_stock_id", "stock_id"),
        Index("ix_securities_reports_collected_at", "collected_at"),
    )
