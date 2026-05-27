"""시장 레짐 분류 서비스.

SPEC-AI-015: KOSPI 5일 수익률과 20일 이동평균 위치를 기반으로
시장 국면(상승장/하락장/횡보장)을 분류하고 레짐별 투자 파라미터를 제공한다.

# @MX:ANCHOR: [AUTO] get_or_create_today_regime — paper_trading, fund_manager, scheduler에서 호출
# @MX:REASON: 레짐 파라미터가 매수 비중, 손절 기준, 일일 최대 거래 수를 결정하는 핵심 함수
# @MX:SPEC: SPEC-AI-015
"""

import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.market_regime import MarketRegime, MarketRegimeEnum

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class RegimeParams:
    """레짐별 투자 파라미터."""
    # 시그널 실행 최소 확신도
    min_action_confidence: float
    # 확신도 >= 0.80일 때 최대 포지션 비율
    max_position_pct_high: float
    # 목표가 최대 비율
    target_pct_max: float
    # 기본 손절 비율
    stop_loss_pct_default: float
    # 일일 최대 신규 매수 건수
    max_daily_trades: int


# @MX:NOTE: [AUTO] SPEC-AI-015 Table 1 기준 레짐별 파라미터 — 하드코딩 변경 금지
# @MX:SPEC: SPEC-AI-015
REGIME_PARAMS_MAP: dict[MarketRegimeEnum, RegimeParams] = {
    MarketRegimeEnum.BULL: RegimeParams(
        min_action_confidence=0.48,
        max_position_pct_high=0.20,
        target_pct_max=0.30,
        stop_loss_pct_default=0.07,
        max_daily_trades=7,
    ),
    MarketRegimeEnum.SIDEWAYS: RegimeParams(
        min_action_confidence=0.55,
        max_position_pct_high=0.15,
        target_pct_max=0.25,
        stop_loss_pct_default=0.05,
        max_daily_trades=5,
    ),
    MarketRegimeEnum.BEAR: RegimeParams(
        min_action_confidence=0.65,
        max_position_pct_high=0.10,
        target_pct_max=0.15,
        stop_loss_pct_default=0.04,
        max_daily_trades=2,
    ),
}


def classify_market_regime(
    kospi_5d_return: float,
    kospi_20d_ma_position: float,
    positive_sector_ratio: float = 0.5,
    vol_level: Optional[float] = None,
) -> tuple[MarketRegimeEnum, float]:
    """KOSPI 지표를 기반으로 시장 레짐과 신뢰도를 분류한다.

    분류 기준 (SPEC-AI-015 + SPEC-AI-018):
    - BULL:     kospi_5d_return >= +1.5% AND kospi_20d_ma_position > 0% AND positive_sector_ratio >= 0.6
    - BEAR:     kospi_5d_return <= -1.5% OR  kospi_20d_ma_position < -2% OR positive_sector_ratio <= 0.3
    - SIDEWAYS: 나머지 모든 경우

    Args:
        kospi_5d_return: KOSPI 5일 수익률 (%)
        kospi_20d_ma_position: KOSPI 20일 MA 대비 현재가 위치 (%)
        positive_sector_ratio: 상승 섹터 비율 (0.0~1.0), REQ-018-001 (기본 0.5)
        vol_level: 변동성 지수 (선택적, 현재 미사용)

    Returns:
        (regime, confidence_score) 튜플
    """
    # @MX:WARN: [AUTO] 분류 순서 중요 — BULL 조건을 BEAR보다 먼저 검사해야 함
    # @MX:REASON: REQ-018-001: BULL에 positive_sector_ratio >= 0.6 추가; BEAR에 <= 0.3 OR 조건 추가
    if (
        kospi_5d_return >= 1.5
        and kospi_20d_ma_position > 0.0
        and positive_sector_ratio >= 0.6
    ):
        regime = MarketRegimeEnum.BULL
        # BULL confidence: 5d_ret/3.0 * 0.5 + ma_pos/5.0 * 0.5
        confidence = min(
            1.0,
            (kospi_5d_return / 3.0) * 0.5 + (max(0.0, kospi_20d_ma_position) / 5.0) * 0.5,
        )
    elif (
        kospi_5d_return <= -1.5
        or kospi_20d_ma_position < -2.0
        or positive_sector_ratio <= 0.3
    ):
        regime = MarketRegimeEnum.BEAR
        # BEAR confidence: abs(5d_ret)/3.0 * 0.5 + abs(min(0, ma_pos))/5.0 * 0.5
        confidence = min(
            1.0,
            (abs(kospi_5d_return) / 3.0) * 0.5
            + (abs(min(0.0, kospi_20d_ma_position)) / 5.0) * 0.5,
        )
    else:
        regime = MarketRegimeEnum.SIDEWAYS
        # REQ-018-003: 하드코딩 0.6 → 거리 기반 동적 공식
        # BULL 임계까지 거리
        d_bull = (
            max(0.0, 1.5 - kospi_5d_return) / 1.5 * 0.5
            + max(0.0, -kospi_20d_ma_position) / 2.0 * 0.5
        )
        # BEAR 임계까지 거리
        d_bear = (
            max(0.0, kospi_5d_return - (-1.5)) / 1.5 * 0.5
            + max(0.0, kospi_20d_ma_position - (-2.0)) / 2.0 * 0.5
        )
        # 중간에 깊을수록 높은 신뢰도 (최대 0.9 캡)
        confidence = min(0.9, 0.5 + min(d_bull, d_bear) * 0.4)

    return regime, confidence


def get_regime_params(regime: MarketRegimeEnum) -> RegimeParams:
    """레짐에 해당하는 투자 파라미터를 반환한다.

    Args:
        regime: 시장 레짐 유형

    Returns:
        RegimeParams 인스턴스
    """
    return REGIME_PARAMS_MAP[regime]


def get_or_create_today_regime(db: Session) -> MarketRegime:
    """오늘 날짜의 시장 레짐을 조회하거나 새로 분류하여 생성한다.

    - 오늘 레짐이 이미 존재하면 SELECT하여 반환 (멱등성)
    - 없으면 KOSPI 데이터를 기반으로 분류 후 INSERT
    - IntegrityError(경쟁 상태) 발생 시 re-SELECT
    - 데이터 조회 불가 시 인메모리 SIDEWAYS 기본값 반환 (DB 미저장)

    Args:
        db: SQLAlchemy sync Session

    Returns:
        MarketRegime 인스턴스 (id=None인 경우 인메모리 기본값)
    """
    today = datetime.datetime.now(_KST).date()

    # 이미 오늘 레짐이 존재하는지 확인
    existing = (
        db.query(MarketRegime)
        .filter(MarketRegime.date == today)
        .first()
    )
    if existing:
        return existing

    # KOSPI 데이터 수집
    try:
        kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio = _fetch_kospi_indicators(db)
    except Exception as e:
        logger.warning(
            "KOSPI 지표 수집 실패 — SIDEWAYS 기본값으로 대체: %s", e
        )
        return _make_default_regime(today)

    # 레짐 분류
    classified_regime, confidence = classify_market_regime(
        kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio
    )

    # REQ-018-002: 히스테리시스 — 직전 2일 기준 플립 억제
    final_regime, raw_regime_value = _apply_hysteresis(
        db, classified_regime, confidence
    )

    # DB INSERT
    new_regime = MarketRegime(
        date=today,
        regime=final_regime,
        kospi_5d_return=kospi_5d_return,
        kospi_20d_ma_position=kospi_20d_ma_position,
        confidence_score=confidence,
        raw_regime=raw_regime_value,
    )
    db.add(new_regime)
    try:
        db.commit()
        db.refresh(new_regime)
        logger.info(
            "시장 레짐 분류 완료: %s (신뢰도=%.2f, 5d_ret=%.2f%%, ma_pos=%.2f%%, raw=%s)",
            final_regime.value, confidence, kospi_5d_return, kospi_20d_ma_position,
            raw_regime_value,
        )
        return new_regime
    except IntegrityError:
        # 경쟁 상태: 다른 프로세스가 먼저 INSERT — rollback 후 re-SELECT
        db.rollback()
        logger.info("IntegrityError 감지 — re-SELECT: date=%s", today)
        existing = (
            db.query(MarketRegime)
            .filter(MarketRegime.date == today)
            .first()
        )
        if existing:
            return existing
        # 극단적 경쟁 상태: 기본값 반환
        logger.warning("re-SELECT 실패 — SIDEWAYS 기본값 반환")
        return _make_default_regime(today)


def get_recent_regimes(db: Session, days: int = 7) -> list[MarketRegime]:
    """최근 N일간의 시장 레짐 데이터를 날짜 역순으로 반환한다.

    Args:
        db: SQLAlchemy sync Session
        days: 조회할 일수 (기본 7일)

    Returns:
        MarketRegime 리스트 (날짜 역순)
    """
    cutoff = datetime.datetime.now(_KST).date() - datetime.timedelta(days=days)
    return (
        db.query(MarketRegime)
        .filter(MarketRegime.date >= cutoff)
        .order_by(MarketRegime.date.desc())
        .all()
    )


def _fetch_kospi_indicators(db: Session) -> tuple[float, float, float]:
    """KOSPI 5일 수익률, 20일 MA 위치, 섹터 폭 비율을 계산하여 반환한다.

    kospi_5d_return: SectorMomentum.avg_return_5d 전체 평균 (오늘 날짜)
    kospi_20d_ma_position: benchmark._load_kospi_closes()로 계산
    positive_sector_ratio: avg_return_5d > 0 섹터 수 / 전체 섹터 수 (REQ-018-001)

    Args:
        db: SQLAlchemy sync Session

    Returns:
        (kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio) 3-튜플 (단위: %)

    Raises:
        ValueError: 데이터를 구할 수 없는 경우
    """
    today = datetime.datetime.now(_KST).date()

    # KOSPI 5일 수익률: SectorMomentum 전체 평균
    from app.models.sector_momentum import SectorMomentum

    avg_row = (
        db.query(func.avg(SectorMomentum.avg_return_5d))
        .filter(SectorMomentum.date == today)
        .scalar()
    )
    # 섹터 폭 계산에 사용할 날짜 (avg_row와 동일 날짜 기준)
    sector_date = today

    if avg_row is None:
        # 당일 데이터는 장 마감 후(16:30 KST) 수집됨 — 장 중/새벽에는 항상 없음.
        # 최근 3거래일 이내 가장 최신 데이터로 폴백하여 실제 국면 파라미터 적용.
        fallback = (
            db.query(func.avg(SectorMomentum.avg_return_5d), SectorMomentum.date)
            .filter(SectorMomentum.date >= today - datetime.timedelta(days=4))
            .filter(SectorMomentum.date < today)
            .group_by(SectorMomentum.date)
            .order_by(SectorMomentum.date.desc())
            .first()
        )
        if fallback and fallback[0] is not None:
            avg_row = fallback[0]
            sector_date = fallback[1]
            logger.info(
                "SectorMomentum 폴백: %s 데이터 없음 → %s 데이터 사용",
                today,
                fallback[1],
            )
        else:
            raise ValueError(f"SectorMomentum 데이터 없음 (date={today})")
    kospi_5d_return = float(avg_row)

    # REQ-018-001: 섹터 폭(breadth) 계산 — 상승 섹터 수 / 전체 섹터 수
    total_sectors = (
        db.query(func.count(SectorMomentum.id))
        .filter(SectorMomentum.date == sector_date)
        .scalar()
    ) or 0
    positive_sectors = (
        db.query(func.count(SectorMomentum.id))
        .filter(SectorMomentum.date == sector_date)
        .filter(SectorMomentum.avg_return_5d > 0)
        .scalar()
    ) or 0
    positive_sector_ratio = (
        float(positive_sectors) / float(total_sectors)
        if total_sectors > 0
        else 0.5  # 데이터 없으면 중립(0.5) 기본값
    )

    # KOSPI 20일 MA 위치: benchmark에서 종가 로드
    from app.services import benchmark

    # asyncio.run()은 이미 실행 중인 이벤트 루프에서 호출하면 RuntimeError 발생.
    # generate_daily_briefing 같은 async 컨텍스트에서 호출될 때 새 스레드로 분리.
    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
            closes = _ex.submit(
                lambda: asyncio.run(benchmark._load_kospi_closes(pages=3))
            ).result(timeout=30)
    except RuntimeError:
        closes = asyncio.run(benchmark._load_kospi_closes(pages=3))
    if not closes:
        raise ValueError("KOSPI 종가 데이터 없음")

    # 최근 날짜 기준 정렬
    sorted_dates = sorted(closes.keys(), reverse=True)
    if len(sorted_dates) < 2:
        raise ValueError(f"KOSPI 종가 데이터 부족: {len(sorted_dates)}개")

    # 가장 최근 종가
    current_close = closes[sorted_dates[0]]

    # 최근 20거래일 평균 (데이터가 20개 미만이면 있는 것만 사용)
    recent_20 = sorted_dates[:20]
    ma_20 = sum(closes[d] for d in recent_20) / len(recent_20)

    if ma_20 <= 0:
        raise ValueError("20일 MA 계산 오류: 0 이하")

    kospi_20d_ma_position = (current_close - ma_20) / ma_20 * 100.0
    return kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio


def _apply_hysteresis(
    db: Session,
    classified_regime: MarketRegimeEnum,
    confidence: float,
) -> tuple[MarketRegimeEnum, str | None]:
    """REQ-018-002: 히스테리시스 규칙으로 최종 레짐을 결정한다.

    플립 규칙:
    - BEAR 전환은 항상 즉시 적용 (비대칭 자본 보호 규칙)
    - 신뢰도 >= 0.75이면 즉시 플립 허용
    - 직전 2일이 모두 새 레짐과 동일하면 플립 허용
    - 그 외: 직전 안정 레짐 유지, raw_regime에 분류값 기록

    Returns:
        (최종_레짐, raw_regime_값_or_None)
    """
    # BEAR 전환은 항상 즉시 적용 (자본 보호 우선)
    if classified_regime == MarketRegimeEnum.BEAR:
        return classified_regime, None

    # 직전 레코드 조회
    recent = get_recent_regimes(db, days=3)

    # 이력 없으면 그대로 적용
    if len(recent) < 2:
        return classified_regime, None

    # 신뢰도 >= 0.75이면 즉시 플립
    if confidence >= 0.75:
        return classified_regime, None

    # 직전 2일이 모두 classified_regime과 동일하면 플립 허용
    prev_two = recent[:2]
    if all(r.regime == classified_regime for r in prev_two):
        return classified_regime, None

    # 히스테리시스 억제: 직전 안정 레짐 유지
    stable_regime = recent[0].regime
    logger.info(
        "히스테리시스 억제: 분류=%s → 유지=%s (신뢰도=%.2f)",
        classified_regime.value, stable_regime.value, confidence,
    )
    return stable_regime, classified_regime.value


def _make_default_regime(today: datetime.date) -> MarketRegime:
    """데이터 부재 시 반환할 인메모리 SIDEWAYS 기본값 (DB 저장 없음).

    REQ-AI-015-040: 데이터 미사용 가능 시 SIDEWAYS + 신뢰도 0.5 반환.
    """
    return MarketRegime(
        id=None,  # type: ignore[arg-type]
        date=today,
        regime=MarketRegimeEnum.SIDEWAYS,
        kospi_5d_return=0.0,
        kospi_20d_ma_position=0.0,
        confidence_score=0.5,
        raw_regime=None,
    )
