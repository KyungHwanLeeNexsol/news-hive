"""SPEC-AI-099: 급등예측 피처 스냅샷 데이터 인프라 (모델 학습 미포함).

종목별·스캔사이클별(per-stock, per-scan-cycle) 불변(immutable) 피처 스냅샷을 저장한다.
기존 일 단위 집계(MLFeatureSnapshot, SPEC-AI-025)와는 다른 그레인이며 이를 대체하지 않는다.
모델 학습/서빙은 본 SPEC의 범위가 아니다 — 데이터 캡처·조회 가능 상태까지만.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeFeatureSnapshot(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-099 — 종목별·사이클별 불변 피처 스냅샷. 동일 종목이 재스캔되면
    # 새 행이 추가된다(FundSignal의 갱신형 UPDATE 패턴과 다름, REQ-AI099-001). 무기한 보존
    # (자동 삭제 잡 없음, §Decisions D4) — 정리 로직은 별도 SPEC 재검토 대상.
    # @MX:SPEC: SPEC-AI-099 REQ-AI099-001
    """앙상블 스코어링 사이클마다 평가된 모든 후보(승격/비승격 무관)의 피처를 개별 행으로 저장한다."""

    __tablename__ = "surge_feature_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # 스캔 사이클 실행 시각 — date가 아닌 datetime (하루 여러 사이클 구분, SPEC-AI-083)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    theme_cluster_score: Mapped[float] = mapped_column(Float, nullable=False)
    combo_score: Mapped[float] = mapped_column(Float, nullable=False)
    # compute_ensemble_score 내부 max(pattern_score, immediate_disclosure_score) 재사용
    best_disclosure_score: Mapped[float] = mapped_column(Float, nullable=False)
    legacy_score: Mapped[float] = mapped_column(Float, nullable=False)
    news_delayed_score: Mapped[float] = mapped_column(Float, nullable=False)
    volume_breakout_score: Mapped[float] = mapped_column(Float, nullable=False)
    momentum_continuation_score: Mapped[float] = mapped_column(Float, nullable=False)
    squeeze_score: Mapped[float] = mapped_column(Float, nullable=False)

    # compute_ensemble_score 내부 active_groups 재사용
    active_groups: Mapped[int] = mapped_column(Integer, nullable=False)
    # compute_ensemble_score 반환값(보정 전 raw, surge_calibrator 미적용)
    surge_score: Mapped[float] = mapped_column(Float, nullable=False)

    price_5d_trend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_pool: Mapped[str] = mapped_column(String(20), nullable=False)
    active_detectors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 시가총액 (억원 단위, Stock.market_cap 기존 컬럼 관례 유지)
    market_cap_eok: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 신호 시점 현재가 (원 단위)
    price_at_signal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 메인 루프 임계값 통과 또는 3개 우회 경로 중 하나로 최종 qualified_codes에 포함되었는지
    qualified: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # 정답 라벨 조인 키(다음 거래일) — 백필 전에는 NULL
    outcome_trading_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    outcome_change_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_was_surge: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 조회 패턴: 특정 종목의 시계열 조회
        Index("ix_surge_feature_snapshots_stock_scanned", "stock_code", "scanned_at"),
        # 백필 잡의 대상 선정 쿼리
        Index("ix_surge_feature_snapshots_outcome_trading_date", "outcome_trading_date"),
    )
