"""SPEC-AI-022: 시그널 커버리지 대시보드 API 응답 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TopMissedStock(BaseModel):
    """커버리지 미달 상위 종목 항목."""

    stock_code: str
    name: str
    # 오늘 등락률 (%)
    change_pct: float
    # 시가총액 (억원)
    market_cap: int | None = None


class CoverageDashboardResponse(BaseModel):
    """GET /api/surge-trading/coverage 응답 스키마."""

    # 응답 생성 시각 (KST)
    as_of: datetime | str

    # 전체 추적 종목 수
    total_stocks_tracked: int = Field(ge=0)

    # 오늘 생성된 시그널 수 (모든 signal_type 합산)
    signals_generated_today: int = Field(ge=0)

    # 커버리지 비율 (%)
    coverage_pct: float = Field(ge=0.0, le=100.0)

    # signal_type별 시그널 수
    by_signal_type: dict[str, int]

    # theme_propagation 시그널 수
    theme_propagation_triggered: int = Field(ge=0, default=0)

    # volume_anomaly 시그널 수
    volume_anomaly_triggered: int = Field(ge=0, default=0)

    # 미커버 상위 종목 목록 (시총 >= 1000억, 등락률 >= 15%)
    top_missed: list[TopMissedStock] = Field(default_factory=list)

    # top_missed가 타임아웃으로 부분 응답인 경우 True
    top_missed_partial: bool = False
