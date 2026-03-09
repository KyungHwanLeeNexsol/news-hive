"""시그널 적중률 검증 서비스.

과거 발행된 FundSignal의 시그널 방향(buy/sell)이 실제 주가 변동과
일치하는지 검증하고, 적중률 통계를 산출한다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock

logger = logging.getLogger(__name__)


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

            signal.verified_at = now
            stats["verified"] += 1
            updated = True

        if updated:
            stats["updated"] += 1

    db.commit()
    logger.info(f"Signal verification: {stats}")
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

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0.0,
        "avg_return": round(sum(returns) / len(returns), 2) if returns else 0.0,
        "buy_accuracy": round(buy_correct / len(buy_signals) * 100, 1) if buy_signals else 0.0,
        "sell_accuracy": round(sell_correct / len(sell_signals) * 100, 1) if sell_signals else 0.0,
        "by_confidence": by_confidence,
    }
