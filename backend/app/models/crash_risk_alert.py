"""코스피 대폭락 조기 경보 알림 이력 모델 (SPEC-AI-064)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CrashRiskAlert(Base):
    """폭락 위험 스캔 이력 — 선행지표 기반 위험도 산출·텔레그램 발송 기록."""

    __tablename__ = "crash_risk_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 스캔 종류: "us_close"(06:30) | "premarket"(08:30) | "intraday"(09:05)
    scan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 위험도: "SAFE" | "CAUTION" | "WARNING" | "DANGER"
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    # 트리거된 신호 목록 JSON — [{"name":"sp500_close","value":-1.8,"threshold":-1.5}, ...]
    triggered_signals: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 장중 스캔 시 코스피 전일 대비 변동률(%)
    kospi_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 텔레그램 발송 성공 여부
    telegram_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
