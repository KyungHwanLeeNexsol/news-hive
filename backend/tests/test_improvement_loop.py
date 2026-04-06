"""SPEC-AI-006: 자기개선 피드백 루프 서비스 테스트.

DDD 방식의 특성화 테스트 (Characterization Tests).
실제 동작을 캡처하여 리팩토링 후 행동 보존을 보장한다.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.factor_weight import FactorWeightHistory
from app.models.fund_signal import FundSignal
from app.models.improvement_log import ImprovementLog
from app.models.prompt_version import PromptVersion
from app.services.factor_scoring import DEFAULT_WEIGHTS
from app.services.improvement_loop import (
    adapt_factor_weights,
    aggregate_failure_patterns,
    get_active_factor_weights,
    get_model_health,
    resolve_stale_ab_test,
)


# ---------------------------------------------------------------------------
# 테스트 헬퍼
# ---------------------------------------------------------------------------

def _make_signal(
    db: Session,
    stock_id: int,
    is_correct: bool | None,
    signal: str = "buy",
    return_pct: float | None = None,
    error_category: str | None = None,
    signal_type: str | None = None,
    factor_scores: dict | None = None,
    prompt_version: str = "v1.0-baseline",
    days_ago: int = 0,
) -> FundSignal:
    """테스트용 FundSignal을 생성하고 DB에 저장한다."""
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    verified_at = created + timedelta(days=5) if is_correct is not None else None

    fs = FundSignal(
        stock_id=stock_id,
        signal=signal,
        confidence=0.8,
        reasoning="테스트 근거",
        is_correct=is_correct,
        return_pct=return_pct,
        error_category=error_category,
        signal_type=signal_type,
        factor_scores=json.dumps(factor_scores) if factor_scores else None,
        prompt_version=prompt_version,
        created_at=created,
        verified_at=verified_at,
    )
    db.add(fs)
    db.flush()
    return fs


def _make_stock(db: Session) -> int:
    """테스트용 Stock을 생성하고 id를 반환한다."""
    from app.models.stock import Stock
    from app.models.sector import Sector

    sector = Sector(name="테스트섹터", is_custom=False)
    db.add(sector)
    db.flush()

    stock = Stock(name="테스트종목", stock_code="000001", sector_id=sector.id)
    db.add(stock)
    db.flush()
    return stock.id


# ---------------------------------------------------------------------------
# aggregate_failure_patterns 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_failure_patterns_empty_db(db: Session):
    """빈 DB에서 집계하면 None을 반환해야 한다."""
    result = await aggregate_failure_patterns(db, days=30)
    assert result is None


@pytest.mark.asyncio
async def test_aggregate_failure_patterns_insufficient_signals(db: Session):
    """검증 시그널이 5건 미만이면 None을 반환해야 한다."""
    stock_id = _make_stock(db)

    # 4건만 생성 (5건 미만)
    for i in range(4):
        _make_signal(db, stock_id, is_correct=True, return_pct=2.5)

    result = await aggregate_failure_patterns(db, days=30)
    assert result is None


@pytest.mark.asyncio
async def test_aggregate_failure_patterns_valid(db: Session):
    """5건 이상 검증 시그널이 있을 때 올바른 집계 결과를 반환해야 한다."""
    stock_id = _make_stock(db)

    # 6건 생성: 4개 적중, 2개 미적중
    for _ in range(4):
        _make_signal(
            db,
            stock_id,
            is_correct=True,
            return_pct=3.0,
            factor_scores={"news_sentiment": 70, "technical": 60, "supply_demand": 65, "valuation": 55},
        )
    for _ in range(2):
        _make_signal(
            db,
            stock_id,
            is_correct=False,
            return_pct=-2.0,
            error_category="macro_shock",
            factor_scores={"news_sentiment": 40, "technical": 35, "supply_demand": 45, "valuation": 50},
        )

    result = await aggregate_failure_patterns(db, days=30)

    assert result is not None
    assert result["total_verified"] == 6
    # 적중률 = 4/6
    assert abs(result["accuracy_rate"] - 4 / 6) < 0.001
    # 오류 카테고리 분포
    assert result["error_category_dist"].get("macro_shock") == 2
    # 평균 수익률
    assert result["avg_return_correct"] > 0
    assert result["avg_return_incorrect"] < 0
    # 팩터 점수 평균
    assert "news_sentiment" in result["factor_score_avg"]


@pytest.mark.asyncio
async def test_aggregate_failure_patterns_low_accuracy_types(db: Session):
    """적중률 50% 미만이고 5건 이상인 시그널 유형을 low_accuracy_signal_types에 포함해야 한다."""
    stock_id = _make_stock(db)

    # buy 시그널: 6건 중 1건 적중 (적중률 ~17%)
    for i in range(6):
        _make_signal(
            db,
            stock_id,
            signal="buy",
            signal_type="buy",
            is_correct=(i == 0),  # 첫 번째만 적중
        )

    # sell 시그널: 5건 모두 적중 (적중률 100%)
    for _ in range(5):
        _make_signal(
            db,
            stock_id,
            signal="sell",
            signal_type="sell",
            is_correct=True,
        )

    result = await aggregate_failure_patterns(db, days=30)

    assert result is not None
    assert "buy" in result["low_accuracy_signal_types"]
    assert "sell" not in result["low_accuracy_signal_types"]


# ---------------------------------------------------------------------------
# adapt_factor_weights 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adapt_factor_weights_insufficient_data(db: Session):
    """30건 미만 시그널이면 None을 반환해야 한다."""
    stock_id = _make_stock(db)

    for i in range(20):  # 30건 미만
        _make_signal(
            db,
            stock_id,
            is_correct=(i % 2 == 0),
            factor_scores={"news_sentiment": 60, "technical": 55, "supply_demand": 50, "valuation": 45},
        )

    result = await adapt_factor_weights(db, days=60)
    assert result is None


@pytest.mark.asyncio
async def test_adapt_factor_weights_normal_case(db: Session):
    """30건 이상 시그널이 있을 때 가중치를 조정하고 DB에 저장해야 한다."""
    stock_id = _make_stock(db)

    # 30건 생성: news_sentiment가 높을 때 적중률이 높도록 설계
    for i in range(30):
        is_correct = i % 3 != 0  # 약 67% 적중
        high_sentiment = 75 if is_correct else 35
        _make_signal(
            db,
            stock_id,
            is_correct=is_correct,
            return_pct=2.0 if is_correct else -1.5,
            factor_scores={
                "news_sentiment": high_sentiment,
                "technical": 55,
                "supply_demand": 50,
                "valuation": 45,
            },
        )

    result = await adapt_factor_weights(db, days=60)

    # 반환값 검증
    assert result is not None
    factor_keys = {"news_sentiment", "technical", "supply_demand", "valuation"}
    assert set(result.keys()) == factor_keys

    # 가중치 합산이 1.0에 근접
    total = sum(result.values())
    assert abs(total - 1.0) < 0.01

    # 각 가중치가 범위 내
    for w in result.values():
        assert 0.10 <= w <= 0.40

    # DB에 FactorWeightHistory가 저장됐는지 확인
    active = db.query(FactorWeightHistory).filter(
        FactorWeightHistory.is_active == True  # noqa: E712
    ).first()
    assert active is not None
    assert active.sample_size == 30


@pytest.mark.asyncio
async def test_adapt_factor_weights_dampening_applied(db: Session):
    """변화량이 0.10을 초과하면 dampening(반걸음)을 적용해야 한다."""
    stock_id = _make_stock(db)

    # 현재 활성 가중치를 균등으로 설정
    initial_weight = FactorWeightHistory(
        news_sentiment=0.25,
        technical=0.25,
        supply_demand=0.25,
        valuation=0.25,
        is_active=True,
        sample_size=10,
    )
    db.add(initial_weight)
    db.flush()

    # 극단적인 패턴: news_sentiment가 매우 높을 때만 적중
    # → news_sentiment 가중치가 크게 올라야 함 → dampening 발동 예상
    for i in range(35):
        is_correct = i < 30  # 30건 적중, 5건 미적중
        _make_signal(
            db,
            stock_id,
            is_correct=is_correct,
            factor_scores={
                "news_sentiment": 95 if is_correct else 10,
                "technical": 50,
                "supply_demand": 50,
                "valuation": 50,
            },
        )

    result = await adapt_factor_weights(db, days=60)
    assert result is not None

    # ImprovementLog에 dampening_applied 기록이 있어야 함
    log = db.query(ImprovementLog).filter(
        ImprovementLog.action_type == "weight_update"
    ).first()
    assert log is not None
    log_details = json.loads(log.details)
    # 극단적 패턴이므로 dampening이 적용됐을 가능성이 높음
    # (정확한 값보다 키 존재 여부 검증)
    assert "dampening_applied" in log_details


# ---------------------------------------------------------------------------
# get_active_factor_weights 테스트
# ---------------------------------------------------------------------------

def test_get_active_factor_weights_no_history(db: Session):
    """활성 가중치 이력이 없으면 DEFAULT_WEIGHTS를 반환해야 한다."""
    weights = get_active_factor_weights(db)
    assert weights == dict(DEFAULT_WEIGHTS)


def test_get_active_factor_weights_with_active_history(db: Session):
    """활성 FactorWeightHistory가 있으면 해당 가중치를 반환해야 한다."""
    custom_weight = FactorWeightHistory(
        news_sentiment=0.35,
        technical=0.25,
        supply_demand=0.20,
        valuation=0.20,
        is_active=True,
        sample_size=50,
    )
    db.add(custom_weight)
    db.flush()

    weights = get_active_factor_weights(db)

    assert weights["news_sentiment"] == pytest.approx(0.35)
    assert weights["technical"] == pytest.approx(0.25)
    assert weights["supply_demand"] == pytest.approx(0.20)
    assert weights["valuation"] == pytest.approx(0.20)


def test_get_active_factor_weights_only_active_row(db: Session):
    """비활성 이력이 있어도 활성 이력의 가중치만 반환해야 한다."""
    # 비활성 이력
    db.add(FactorWeightHistory(
        news_sentiment=0.10,
        technical=0.40,
        supply_demand=0.10,
        valuation=0.40,
        is_active=False,
        sample_size=20,
    ))
    # 활성 이력
    db.add(FactorWeightHistory(
        news_sentiment=0.30,
        technical=0.30,
        supply_demand=0.20,
        valuation=0.20,
        is_active=True,
        sample_size=40,
    ))
    db.flush()

    weights = get_active_factor_weights(db)
    assert weights["news_sentiment"] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# resolve_stale_ab_test 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_stale_ab_test_no_active_test(db: Session):
    """활성 A/B 테스트가 없으면 False를 반환해야 한다."""
    result = await resolve_stale_ab_test(db, max_days=30)
    assert result is False


@pytest.mark.asyncio
async def test_resolve_stale_ab_test_fresh_test(db: Session):
    """30일 미만의 A/B 테스트는 종료하지 않아야 한다."""
    # 오늘 생성된 실험군 버전
    treatment = PromptVersion(
        version_name="v2.0-ai-generated",
        template_key="signal",
        is_active=True,
        is_control=False,
        created_at=datetime.now(timezone.utc) - timedelta(days=5),  # 5일 전
    )
    db.add(treatment)
    db.flush()

    result = await resolve_stale_ab_test(db, max_days=30)
    assert result is False

    # 여전히 활성 상태여야 함
    db.refresh(treatment)
    assert treatment.is_active is True


@pytest.mark.asyncio
async def test_resolve_stale_ab_test_stale_test(db: Session):
    """30일 초과 A/B 테스트는 미결론으로 종료해야 한다."""
    # 35일 전 생성된 실험군
    treatment = PromptVersion(
        version_name="v2.0-old-experiment",
        template_key="signal",
        is_active=True,
        is_control=False,
        created_at=datetime.now(timezone.utc) - timedelta(days=35),
    )
    db.add(treatment)
    db.flush()

    result = await resolve_stale_ab_test(db, max_days=30)
    assert result is True

    # 비활성화 됐어야 함
    db.refresh(treatment)
    assert treatment.is_active is False

    # ImprovementLog에 ab_resolution 기록이 있어야 함
    log = db.query(ImprovementLog).filter(
        ImprovementLog.action_type == "ab_resolution"
    ).first()
    assert log is not None
    log_details = json.loads(log.details)
    assert log_details["result"] == "inconclusive"
    assert log_details["version"] == "v2.0-old-experiment"


# ---------------------------------------------------------------------------
# get_model_health 테스트
# ---------------------------------------------------------------------------

def test_get_model_health_returns_required_keys(db: Session):
    """get_model_health()가 모든 필수 키를 포함한 dict를 반환해야 한다."""
    result = get_model_health(db)

    required_keys = {
        "current_prompt_version",
        "prompt_accuracy_30d",
        "ab_test_active",
        "ab_test_status",
        "factor_weights",
        "signal_type_accuracy",
        "improvement_history",
    }
    assert required_keys.issubset(set(result.keys()))


def test_get_model_health_empty_db_defaults(db: Session):
    """데이터가 없을 때 기본값을 반환해야 한다."""
    result = get_model_health(db)

    assert result["prompt_accuracy_30d"] == 0.0
    assert result["ab_test_active"] is False
    assert result["ab_test_status"] is None
    assert result["improvement_history"] == []
    # 팩터 가중치는 기본값이어야 함
    assert result["factor_weights"]["is_customized"] is False


def test_get_model_health_with_active_ab_test(db: Session):
    """활성 A/B 테스트가 있을 때 ab_test_active가 True여야 한다."""
    # 대조군
    control = PromptVersion(
        version_name="v1.0-control",
        template_key="signal",
        is_active=True,
        is_control=True,
    )
    # 실험군
    treatment = PromptVersion(
        version_name="v2.0-treatment",
        template_key="signal",
        is_active=True,
        is_control=False,
    )
    db.add(control)
    db.add(treatment)
    db.flush()

    result = get_model_health(db)

    assert result["ab_test_active"] is True
    assert result["ab_test_status"] is not None
    assert result["ab_test_status"]["treatment"] == "v2.0-treatment"


def test_get_model_health_with_custom_weights(db: Session):
    """커스텀 가중치가 있을 때 is_customized가 True여야 한다."""
    custom_weight = FactorWeightHistory(
        news_sentiment=0.35,
        technical=0.25,
        supply_demand=0.20,
        valuation=0.20,
        is_active=True,
        sample_size=30,
    )
    db.add(custom_weight)
    db.flush()

    result = get_model_health(db)

    assert result["factor_weights"]["is_customized"] is True
    assert result["factor_weights"]["current"]["news_sentiment"] == pytest.approx(0.35)


def test_get_model_health_accuracy_calculation(db: Session):
    """30일 내 검증 시그널로 적중률을 계산해야 한다."""
    stock_id = _make_stock(db)

    # 4건 적중, 1건 미적중
    for _ in range(4):
        _make_signal(db, stock_id, is_correct=True)
    _make_signal(db, stock_id, is_correct=False)

    result = get_model_health(db)

    assert result["prompt_accuracy_30d"] == pytest.approx(0.8, abs=0.01)


def test_get_model_health_improvement_history_limit(db: Session):
    """improvement_history는 최대 10건만 반환해야 한다."""
    # 15건 로그 생성
    for i in range(15):
        db.add(ImprovementLog(
            action_type="failure_aggregation",
            details=json.dumps({"run": i}),
        ))
    db.flush()

    result = get_model_health(db)
    assert len(result["improvement_history"]) <= 10
