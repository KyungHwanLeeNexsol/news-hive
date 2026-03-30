"""REQ-025: ML 피처 엔지니어링 서비스 테스트."""

import json
from datetime import date, datetime, timezone

import pytest

from app.models.ml_feature import MLFeatureSnapshot
from app.models.sector_momentum import SectorMomentum
from app.services.ml_feature_engineering import (
    ML_READINESS_THRESHOLD_DAYS,
    capture_daily_features,
    check_ml_readiness,
    _compute_factor_averages,
    _compute_recent_accuracy,
    _compute_trend_alignment_distribution,
    _count_volume_spikes,
    _get_momentum_sectors,
)


# ---------------------------------------------------------------------------
# capture_daily_features 통합 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capture_daily_features_creates_snapshot(db, make_fund_signal):
    """당일 시그널이 있을 때 스냅샷이 생성되어야 한다."""
    factor_json = json.dumps({
        "news_sentiment": 70,
        "technical": 60,
        "supply_demand": 50,
        "valuation": 80,
    })
    make_fund_signal(
        factor_scores=factor_json,
        trend_alignment="aligned",
        volatility_level="normal",
    )
    make_fund_signal(
        factor_scores=factor_json,
        trend_alignment="divergent",
        volatility_level="high",
    )
    db.commit()

    snapshot = await capture_daily_features(db)

    assert snapshot is not None
    assert snapshot.date == date.today()
    assert snapshot.total_signals_today == 2
    assert snapshot.avg_news_sentiment == 70.0
    assert snapshot.avg_technical == 60.0
    assert snapshot.volatility_level == "high"  # 마지막 시그널 기준


@pytest.mark.asyncio
async def test_capture_daily_features_no_duplicate(db, make_fund_signal):
    """같은 날 두 번 실행하면 두 번째는 None을 반환해야 한다."""
    make_fund_signal()
    db.commit()

    first = await capture_daily_features(db)
    second = await capture_daily_features(db)

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_capture_daily_features_empty_signals(db):
    """시그널이 없어도 스냅샷은 생성되어야 한다."""
    snapshot = await capture_daily_features(db)

    assert snapshot is not None
    assert snapshot.total_signals_today == 0
    assert snapshot.avg_news_sentiment is None
    assert snapshot.trend_alignment_distribution is None


# ---------------------------------------------------------------------------
# check_ml_readiness 테스트
# ---------------------------------------------------------------------------

def test_ml_readiness_not_ready(db):
    """데이터가 부족하면 ready=False."""
    result = check_ml_readiness(db)

    assert result["ready"] is False
    assert result["days"] == 0
    assert str(ML_READINESS_THRESHOLD_DAYS) in result["message"]


def test_ml_readiness_ready(db):
    """90일 이상 데이터가 있으면 ready=True."""
    from datetime import timedelta

    for i in range(ML_READINESS_THRESHOLD_DAYS):
        snapshot = MLFeatureSnapshot(
            date=date.today() - timedelta(days=i),
            total_signals_today=0,
            volume_spike_count=0,
            momentum_sector_count=0,
        )
        db.add(snapshot)
    db.flush()

    result = check_ml_readiness(db)

    assert result["ready"] is True
    assert result["days"] == ML_READINESS_THRESHOLD_DAYS
    assert "REQ-AI-011" in result["message"]


# ---------------------------------------------------------------------------
# 헬퍼 함수 단위 테스트
# ---------------------------------------------------------------------------

def test_compute_factor_averages_empty():
    """시그널이 없으면 빈 dict 반환."""
    assert _compute_factor_averages([]) == {}


def test_compute_factor_averages(make_fund_signal, db):
    """팩터 점수 평균 계산."""
    s1 = make_fund_signal(factor_scores=json.dumps({
        "news_sentiment": 80, "technical": 60,
        "supply_demand": 40, "valuation": 100,
    }))
    s2 = make_fund_signal(factor_scores=json.dumps({
        "news_sentiment": 60, "technical": 40,
        "supply_demand": 60, "valuation": 80,
    }))
    db.flush()

    result = _compute_factor_averages([s1, s2])

    assert result["news_sentiment"] == 70.0
    assert result["technical"] == 50.0
    assert result["supply_demand"] == 50.0
    assert result["valuation"] == 90.0


def test_compute_trend_alignment_distribution(make_fund_signal, db):
    """추세 정렬 분포 계산."""
    s1 = make_fund_signal(trend_alignment="aligned")
    s2 = make_fund_signal(trend_alignment="aligned")
    s3 = make_fund_signal(trend_alignment="divergent")
    db.flush()

    result = _compute_trend_alignment_distribution([s1, s2, s3])

    assert result == {"aligned": 2, "divergent": 1, "mixed": 0}


def test_compute_trend_alignment_distribution_empty():
    """시그널이 없으면 None 반환."""
    assert _compute_trend_alignment_distribution([]) is None


def test_count_volume_spikes_from_factor_scores(make_fund_signal, db):
    """factor_scores 내 volume_spike 플래그 기반 카운트."""
    s1 = make_fund_signal(factor_scores=json.dumps({
        "news_sentiment": 50, "volume_spike": True,
    }))
    s2 = make_fund_signal(factor_scores=json.dumps({
        "news_sentiment": 50, "volume_spike": False,
    }))
    db.flush()

    assert _count_volume_spikes([s1, s2]) == 1


def test_count_volume_spikes_from_market_summary(make_fund_signal, db):
    """market_summary 키워드 기반 카운트."""
    s1 = make_fund_signal(market_summary="오늘 거래량 급증 포착됨")
    db.flush()

    assert _count_volume_spikes([s1]) == 1


def test_get_momentum_sectors(db, make_sector):
    """모멘텀 섹터 조회."""
    sector = make_sector(name="반도체")
    db.flush()

    momentum = SectorMomentum(
        sector_id=sector.id,
        date=date.today(),
        daily_return=2.5,
        momentum_tag="momentum_sector",
    )
    db.add(momentum)
    db.flush()

    count, ids = _get_momentum_sectors(db, date.today())

    assert count == 1
    assert sector.id in ids


def test_compute_recent_accuracy_no_data(db):
    """검증된 시그널이 없으면 None."""
    assert _compute_recent_accuracy(db) is None


def test_compute_recent_accuracy(db, make_fund_signal):
    """최근 5건 중 3건 적중 -> 0.6."""
    now = datetime.now(timezone.utc)
    for i, correct in enumerate([True, True, True, False, False]):
        make_fund_signal(
            is_correct=correct,
            verified_at=now,
        )
    db.flush()

    accuracy = _compute_recent_accuracy(db)

    assert accuracy == 0.6
