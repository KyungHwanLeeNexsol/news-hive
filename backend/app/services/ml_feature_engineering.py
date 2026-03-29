"""ML 피처 엔지니어링 서비스.

REQ-025: 일별 피처 스냅샷 생성 및 ML 준비 상태 확인.
REQ-AI-011 ML 앙상블 모델 학습을 위한 피처 데이터 축적.
"""

import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.ml_feature import MLFeatureSnapshot
from app.models.sector_momentum import SectorMomentum

logger = logging.getLogger(__name__)

# ML 학습 가능 최소 데이터 일수
ML_READINESS_THRESHOLD_DAYS = 90


async def capture_daily_features(db: Session) -> MLFeatureSnapshot | None:
    """당일 ML 피처를 계산하여 스냅샷으로 저장한다.

    이미 당일 스냅샷이 존재하면 None 반환 (중복 방지).
    """
    today = date.today()

    # 중복 확인
    existing = db.query(MLFeatureSnapshot).filter(
        MLFeatureSnapshot.date == today
    ).first()
    if existing:
        logger.info(f"ML 피처 스냅샷이 이미 존재함: {today}")
        return None

    # 1) 당일 시그널 조회
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    today_signals = db.query(FundSignal).filter(
        FundSignal.created_at >= today_start
    ).all()

    total_signals = len(today_signals)

    # 2) 4-factor 평균 계산
    avg_scores = _compute_factor_averages(today_signals)

    # 3) 추세 정렬 분포
    trend_dist = _compute_trend_alignment_distribution(today_signals)

    # 4) 시장 변동성 레벨 (가장 최근 시그널의 volatility_level 사용)
    volatility = _get_latest_volatility_level(today_signals)

    # 5) 거래량 이상 종목 수 (volume_spike 키워드 기반)
    volume_spike_count = _count_volume_spikes(today_signals)

    # 6) 섹터 모멘텀
    momentum_count, momentum_ids = _get_momentum_sectors(db, today)

    # 7) 최근 5건 적중률
    recent_accuracy = _compute_recent_accuracy(db)

    snapshot = MLFeatureSnapshot(
        date=today,
        avg_news_sentiment=avg_scores.get("news_sentiment"),
        avg_technical=avg_scores.get("technical"),
        avg_supply_demand=avg_scores.get("supply_demand"),
        avg_valuation=avg_scores.get("valuation"),
        trend_alignment_distribution=json.dumps(trend_dist) if trend_dist else None,
        volatility_level=volatility,
        volume_spike_count=volume_spike_count,
        momentum_sector_count=momentum_count,
        momentum_sector_ids=json.dumps(momentum_ids) if momentum_ids else None,
        recent_5_accuracy=recent_accuracy,
        total_signals_today=total_signals,
    )

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    logger.info(
        f"ML 피처 스냅샷 생성 완료: {today}, "
        f"시그널 {total_signals}건, 적중률 {recent_accuracy}"
    )

    # ML 준비 상태 확인
    readiness = check_ml_readiness(db)
    if readiness["ready"]:
        logger.info(f"[ML READY] {readiness['message']}")

    return snapshot


def check_ml_readiness(db: Session) -> dict:
    """ML 학습 가능 상태 확인.

    90일 이상의 피처 데이터가 축적되면 ready=True 반환.
    """
    count = db.query(sa_func.count(MLFeatureSnapshot.id)).scalar() or 0

    if count >= ML_READINESS_THRESHOLD_DAYS:
        return {
            "ready": True,
            "days": count,
            "message": (
                f"ML 앙상블 모델 학습 가능: {count}일분 피처 데이터 축적 완료. "
                f"REQ-AI-011 활성화를 검토하세요."
            ),
        }
    return {
        "ready": False,
        "days": count,
        "message": (
            f"ML 데이터 축적 중: {count}/{ML_READINESS_THRESHOLD_DAYS}일 "
            f"({ML_READINESS_THRESHOLD_DAYS - count}일 남음)"
        ),
    }


def _compute_factor_averages(signals: list[FundSignal]) -> dict[str, float | None]:
    """시그널들의 4-factor 점수 평균을 계산한다."""
    if not signals:
        return {}

    sums: dict[str, float] = {
        "news_sentiment": 0.0,
        "technical": 0.0,
        "supply_demand": 0.0,
        "valuation": 0.0,
    }
    count = 0

    for signal in signals:
        if not signal.factor_scores:
            continue
        try:
            scores = json.loads(signal.factor_scores)
        except (json.JSONDecodeError, TypeError):
            continue

        count += 1
        for key in sums:
            sums[key] += float(scores.get(key, 0))

    if count == 0:
        return {}

    return {key: round(val / count, 4) for key, val in sums.items()}


def _compute_trend_alignment_distribution(
    signals: list[FundSignal],
) -> dict[str, int] | None:
    """시그널들의 추세 정렬 상태 분포를 계산한다."""
    if not signals:
        return None

    dist: dict[str, int] = {"aligned": 0, "divergent": 0, "mixed": 0}
    for signal in signals:
        alignment = signal.trend_alignment
        if alignment in dist:
            dist[alignment] += 1

    if sum(dist.values()) == 0:
        return None
    return dist


def _get_latest_volatility_level(signals: list[FundSignal]) -> str | None:
    """가장 최근 시그널의 변동성 레벨을 반환한다."""
    for signal in reversed(signals):
        if signal.volatility_level:
            return signal.volatility_level
    return None


def _count_volume_spikes(signals: list[FundSignal]) -> int:
    """거래량 이상이 감지된 시그널 수를 센다.

    factor_scores JSON 내 volume_spike 필드 또는
    market_summary에 '거래량 급증' 키워드 기반.
    """
    count = 0
    for signal in signals:
        # factor_scores에서 volume_spike 확인
        if signal.factor_scores:
            try:
                scores = json.loads(signal.factor_scores)
                if scores.get("volume_spike"):
                    count += 1
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

        # market_summary에서 키워드 확인
        if signal.market_summary and "거래량 급증" in signal.market_summary:
            count += 1

    return count


def _get_momentum_sectors(db: Session, target_date: date) -> tuple[int, list[int]]:
    """당일 모멘텀 섹터 정보를 조회한다."""
    momentum_records = db.query(SectorMomentum).filter(
        SectorMomentum.date == target_date,
        SectorMomentum.momentum_tag == "momentum_sector",
    ).all()

    sector_ids = [r.sector_id for r in momentum_records]
    return len(sector_ids), sector_ids


def _compute_recent_accuracy(db: Session) -> float | None:
    """최근 5건의 검증된 시그널 적중률을 계산한다."""
    recent_verified = (
        db.query(FundSignal)
        .filter(FundSignal.is_correct.isnot(None))
        .order_by(FundSignal.verified_at.desc())
        .limit(5)
        .all()
    )

    if not recent_verified:
        return None

    correct = sum(1 for s in recent_verified if s.is_correct)
    return round(correct / len(recent_verified), 4)
