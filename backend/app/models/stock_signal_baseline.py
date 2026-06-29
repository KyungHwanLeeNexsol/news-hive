"""SPEC-AI-065 REQ-1: 종목별 탐지기 30거래일 롤링 기준선 모델.

stock_signal_baselines 테이블은 (stock_code, detector_name) 쌍마다
rolling_mean, rolling_std, sample_count를 저장하여 z-score 정규화에 사용한다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockSignalBaseline(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-065 REQ-1 — (stock_code, detector_name) 쌍의 30거래일 롤링 통계.
    # @MX:SPEC: SPEC-AI-065 REQ-1
    """종목별 탐지기 롤링 기준선 테이블.

    Welford's online algorithm 방식으로 누적된
    (rolling_mean, rolling_var, sample_count)를 저장한다.
    rolling_std = sqrt(rolling_var / max(1, sample_count - 1)).
    """

    __tablename__ = "stock_signal_baselines"
    __table_args__ = (
        UniqueConstraint("stock_code", "detector_name", name="uq_stock_detector_baseline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 종목 코드 (6자리 문자열)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    # 탐지기 이름 (theme_cluster, volume_news_combo, ...)
    detector_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Welford's algorithm 누적 통계
    rolling_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 분산 누적값 (M2) — std = sqrt(M2 / max(1, n-1))
    rolling_m2: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 관측 샘플 수 (최대 30거래일)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
