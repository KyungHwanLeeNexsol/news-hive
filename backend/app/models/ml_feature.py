"""ML 피처 엔지니어링 일별 스냅샷 모델.

REQ-025: ML Feature Engineering Pipeline.
REQ-AI-011 ML 앙상블 모델 학습을 대비하여
일별로 핵심 피처를 계산하고 저장한다.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MLFeatureSnapshot(Base):
    """일별 ML 피처 스냅샷."""
    __tablename__ = "ml_feature_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)

    # 4-factor 평균 점수 (당일 시그널 기준)
    avg_news_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_technical: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_supply_demand: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_valuation: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 추세 정렬 분포 (JSON: {"aligned": N, "divergent": N, "mixed": N})
    trend_alignment_distribution: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 시장 변동성 레벨 (low / normal / high / extreme)
    volatility_level: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # 거래량 이상 종목 수 (volume_spike가 감지된 시그널 개수)
    volume_spike_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 섹터 모멘텀 정보
    momentum_sector_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    momentum_sector_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [1, 3, 5]

    # 최근 5건 시그널 적중률
    recent_5_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 당일 시그널 수
    total_signals_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
