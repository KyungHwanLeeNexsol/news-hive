"""시그널 적중률 검증 서비스.

과거 발행된 FundSignal의 시그널 방향(buy/sell)이 실제 주가 변동과
일치하는지 검증하고, 적중률 통계를 산출한다.
REQ-AI-003: 실패한 시그널의 오류 패턴을 AI로 분류한다.
REQ-AI-004: 과거 적중률 기반 Bayesian 신뢰도 보정을 수행한다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# REQ-AI-003: 허용되는 오류 카테고리 목록
_VALID_ERROR_CATEGORIES = frozenset({
    "macro_shock",
    "supply_reversal",
    "earnings_miss",
    "sector_contagion",
    "technical_breakdown",
})


async def _get_current_price(stock_code: str) -> int | None:
    """현재 주가를 가져온다 (KIS → Naver fallback)."""
    from app.services.kis_api import fetch_kis_stock_price
    from app.services.naver_finance import fetch_stock_fundamentals

    try:
        kis = await fetch_kis_stock_price(stock_code)
        if kis and kis.current_price:
            return kis.current_price
    except Exception:
        pass

    try:
        fund = await fetch_stock_fundamentals(stock_code)
        if fund and fund.current_price:
            return fund.current_price
    except Exception:
        pass

    return None


async def _classify_error(signal: FundSignal, stock_name: str) -> str | None:
    """실패한 시그널의 오류 패턴을 AI로 분류한다.

    Args:
        signal: 실패한 FundSignal (is_correct=False)
        stock_name: 종목명

    Returns:
        오류 카테고리 문자열 또는 None (분류 실패 시)
    """
    from app.services.ai_client import ask_ai

    prompt = f"""투자 시그널이 실패한 원인을 분류해주세요.

시그널 정보:
- 종목: {stock_name}
- 시그널 유형: {signal.signal} (confidence: {signal.confidence:.2f})
- 시그널 발행 시 주가: {signal.price_at_signal}원
- 5일 후 주가: {signal.price_after_5d}원
- 수익률: {signal.return_pct}%

다음 5가지 카테고리 중 하나만 영어로 응답해주세요 (카테고리명만 출력):
- macro_shock: 거시경제 충격 (금리, 환율, 글로벌 이벤트 등)
- supply_reversal: 수급 반전 (외국인/기관 매매 방향 전환)
- earnings_miss: 실적 미달 (예상 대비 실적 부진)
- sector_contagion: 섹터 전이 (동종 업종 악재 확산)
- technical_breakdown: 기술적 이탈 (지지선/저항선 돌파 실패)"""

    try:
        response = await ask_ai(prompt, max_retries=2)
        if not response:
            return None

        # AI 응답에서 카테고리 추출
        category = response.strip().lower().replace(" ", "_")
        # 응답에 유효한 카테고리가 포함되어 있는지 확인
        for valid in _VALID_ERROR_CATEGORIES:
            if valid in category:
                return valid

        logger.warning("AI가 유효하지 않은 오류 카테고리를 반환: %s", response)
        return None
    except Exception:
        logger.exception("오류 패턴 분류 중 예외 발생")
        return None


async def verify_signals(db: Session) -> dict:
    """미검증 시그널들의 적중 여부를 검증한다.

    - 1일 이상 지난 시그널: price_after_1d 기록
    - 3일 이상 지난 시그널: price_after_3d 기록
    - 5일 이상 지난 시그널: price_after_5d + is_correct + return_pct 기록

    Returns:
        {"verified": 검증 완료 수, "updated": 가격 업데이트 수}
    """
    now = datetime.now(timezone.utc)
    stats = {"verified": 0, "updated": 0}

    # 미완료 시그널 조회 (buy/sell만, hold는 검증 불필요)
    unverified = (
        db.query(FundSignal)
        .filter(
            FundSignal.signal.in_(["buy", "sell"]),
            FundSignal.verified_at.is_(None),
            FundSignal.price_at_signal.isnot(None),  # 시그널 발행 시 주가가 기록된 것만
        )
        .all()
    )

    if not unverified:
        logger.info("No unverified signals to process")
        return stats

    # 종목별로 그룹핑하여 주가 조회 최소화
    stock_ids = set(s.stock_id for s in unverified)
    stock_map: dict[int, Stock] = {}
    for stock in db.query(Stock).filter(Stock.id.in_(stock_ids)).all():
        stock_map[stock.id] = stock

    price_cache: dict[str, int | None] = {}

    for signal in unverified:
        stock = stock_map.get(signal.stock_id)
        if not stock:
            continue

        age_days = (now - signal.created_at).days
        if age_days < 1:
            continue

        # 현재가 조회 (캐시)
        if stock.stock_code not in price_cache:
            price_cache[stock.stock_code] = await _get_current_price(stock.stock_code)

        current_price = price_cache.get(stock.stock_code)
        if not current_price:
            continue

        updated = False

        # 1일 후 가격 기록
        if age_days >= 1 and signal.price_after_1d is None:
            signal.price_after_1d = current_price
            updated = True

        # 3일 후 가격 기록
        if age_days >= 3 and signal.price_after_3d is None:
            signal.price_after_3d = current_price
            updated = True

        # 5일 후 최종 검증
        if age_days >= 5 and signal.price_after_5d is None:
            signal.price_after_5d = current_price

            # 적중 여부 판단
            price_change = current_price - signal.price_at_signal
            signal.return_pct = round(price_change / signal.price_at_signal * 100, 2)

            if signal.signal == "buy":
                signal.is_correct = price_change > 0  # 매수 시그널 → 주가 상승이면 적중
            elif signal.signal == "sell":
                signal.is_correct = price_change < 0  # 매도 시그널 → 주가 하락이면 적중

            # REQ-AI-003: 실패한 시그널의 오류 패턴 분류
            if signal.is_correct is False:
                error_cat = await _classify_error(signal, stock.name)
                if error_cat:
                    signal.error_category = error_cat

            signal.verified_at = now
            stats["verified"] += 1
            updated = True

        if updated:
            stats["updated"] += 1

    db.commit()
    logger.info(f"Signal verification: {stats}")
    return stats


async def fast_verify(db: Session) -> dict:
    """장중 빠른 검증: 6h/12h 경과 시그널의 가격 기록 및 손절가 이탈 감지.

    한국 주식시장 개장 시간(09:00-15:30 KST)에만 동작한다.

    Returns:
        {"checked": 확인 수, "early_warnings": 손절가 이탈 수}
    """
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(kst)

    # 장중 시간 확인 (09:00-15:30 KST, 평일만)
    if now_kst.weekday() >= 5:  # 토/일
        return {"checked": 0, "early_warnings": 0}
    market_open = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    if not (market_open <= now_kst <= market_close):
        return {"checked": 0, "early_warnings": 0}

    now = datetime.now(timezone.utc)
    stats: dict[str, int] = {"checked": 0, "early_warnings": 0}

    # 아직 최종 검증 안 된 buy/sell 시그널 중 6h+ 경과한 것
    candidates = (
        db.query(FundSignal)
        .filter(
            FundSignal.signal.in_(["buy", "sell"]),
            FundSignal.verified_at.is_(None),
            FundSignal.price_at_signal.isnot(None),
            FundSignal.created_at <= now - timedelta(hours=6),
        )
        .all()
    )

    if not candidates:
        return stats

    stock_ids = set(s.stock_id for s in candidates)
    stock_map: dict[int, Stock] = {}
    for stock in db.query(Stock).filter(Stock.id.in_(stock_ids)).all():
        stock_map[stock.id] = stock

    price_cache: dict[str, int | None] = {}

    for signal in candidates:
        stock = stock_map.get(signal.stock_id)
        if not stock:
            continue

        age_hours = (now - signal.created_at).total_seconds() / 3600

        if stock.stock_code not in price_cache:
            price_cache[stock.stock_code] = await _get_current_price(stock.stock_code)

        current_price = price_cache.get(stock.stock_code)
        if not current_price:
            continue

        updated = False

        # 6시간 후 가격 기록
        if age_hours >= 6 and signal.price_after_6h is None:
            signal.price_after_6h = current_price
            updated = True

        # 12시간 후 가격 기록
        if age_hours >= 12 and signal.price_after_12h is None:
            signal.price_after_12h = current_price
            updated = True

        # 손절가 이탈 감지
        if signal.stop_loss and current_price and signal.early_warning is None:
            if signal.signal == "buy" and current_price <= signal.stop_loss:
                signal.early_warning = True
                stats["early_warnings"] += 1
                logger.warning(
                    "Early warning: %s (signal=%s, stop_loss=%d, current=%d)",
                    stock.name, signal.signal, signal.stop_loss, current_price,
                )
                updated = True
            elif signal.signal == "sell" and current_price >= signal.stop_loss:
                signal.early_warning = True
                stats["early_warnings"] += 1
                updated = True

        if updated:
            stats["checked"] += 1

    db.commit()
    logger.info("Fast verify: %s", stats)
    return stats


def get_accuracy_stats(db: Session, days: int = 30) -> dict:
    """최근 N일간 시그널 적중률 통계를 산출한다.

    Returns:
        {
            "total": 전체 검증 시그널 수,
            "correct": 적중 수,
            "accuracy": 적중률 (%),
            "avg_return": 평균 수익률 (%),
            "buy_accuracy": 매수 시그널 적중률,
            "sell_accuracy": 매도 시그널 적중률,
            "by_confidence": {상/중/하 신뢰도별 적중률},
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    verified = (
        db.query(FundSignal)
        .filter(
            FundSignal.verified_at.isnot(None),
            FundSignal.created_at >= cutoff,
        )
        .all()
    )

    if not verified:
        return {
            "total": 0, "correct": 0, "accuracy": 0.0,
            "avg_return": 0.0, "buy_accuracy": 0.0, "sell_accuracy": 0.0,
            "by_confidence": {},
        }

    total = len(verified)
    correct = sum(1 for s in verified if s.is_correct)
    returns = [s.return_pct for s in verified if s.return_pct is not None]

    buy_signals = [s for s in verified if s.signal == "buy"]
    sell_signals = [s for s in verified if s.signal == "sell"]

    buy_correct = sum(1 for s in buy_signals if s.is_correct)
    sell_correct = sum(1 for s in sell_signals if s.is_correct)

    # 신뢰도 구간별 적중률
    confidence_buckets = {"high": [], "medium": [], "low": []}
    for s in verified:
        if s.confidence >= 0.7:
            confidence_buckets["high"].append(s.is_correct)
        elif s.confidence >= 0.4:
            confidence_buckets["medium"].append(s.is_correct)
        else:
            confidence_buckets["low"].append(s.is_correct)

    by_confidence = {}
    for level, results in confidence_buckets.items():
        if results:
            by_confidence[level] = {
                "total": len(results),
                "accuracy": round(sum(1 for r in results if r) / len(results) * 100, 1),
            }

    # REQ-AI-003: 오류 패턴 분포
    error_distribution: dict[str, int] = {}
    failed = [s for s in verified if s.is_correct is False and s.error_category]
    for s in failed:
        error_distribution[s.error_category] = error_distribution.get(s.error_category, 0) + 1

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0.0,
        "avg_return": round(sum(returns) / len(returns), 2) if returns else 0.0,
        "buy_accuracy": round(buy_correct / len(buy_signals) * 100, 1) if buy_signals else 0.0,
        "sell_accuracy": round(sell_correct / len(sell_signals) * 100, 1) if sell_signals else 0.0,
        "by_confidence": by_confidence,
        "error_distribution": error_distribution,
    }


def calibrate_confidence(raw_confidence: float, accuracy_stats: dict) -> float:
    """과거 적중률 기반 Bayesian 신뢰도 보정.

    AI가 출력한 원시 신뢰도를 과거 적중률 데이터로 보정하여
    과신/과소평가를 교정한다.

    Args:
        raw_confidence: AI가 출력한 원시 신뢰도 (0.0~1.0)
        accuracy_stats: get_accuracy_stats()의 반환값

    Returns:
        보정된 신뢰도 (0.1~0.95)
    """
    by_confidence = accuracy_stats.get("by_confidence", {})
    overall_accuracy = accuracy_stats.get("accuracy", 0.0)

    # 과거 데이터가 없으면 원시 신뢰도 그대로 반환
    if not by_confidence or accuracy_stats.get("total", 0) == 0:
        return raw_confidence

    # 신뢰도 구간 결정 (high: 0.7+, medium: 0.4~0.7, low: ~0.4)
    if raw_confidence >= 0.7:
        bucket_key = "high"
    elif raw_confidence >= 0.4:
        bucket_key = "medium"
    else:
        bucket_key = "low"

    bucket = by_confidence.get(bucket_key)
    if not bucket:
        # 해당 구간에 과거 데이터가 없으면 원시 신뢰도 반환
        return raw_confidence

    bucket_accuracy = bucket["accuracy"]  # 백분율 (0~100)

    # Bayesian 보정 공식
    # calibrated = raw * (bucket_accuracy / 100) + (1 - raw) * overall_accuracy / 100
    calibrated = (
        raw_confidence * (bucket_accuracy / 100.0)
        + (1.0 - raw_confidence) * (overall_accuracy / 100.0)
    )

    # [0.1, 0.95] 범위로 클램핑
    return max(0.1, min(0.95, calibrated))
