"""뉴스-가격 반응 추적 서비스.

뉴스 기사 발행 시점의 주가 스냅샷을 캡처하고,
이후 1일/5일 가격 변동을 backfill하여 뉴스→가격 영향을 분석한다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.news_price_impact import NewsPriceImpact
from app.models.stock import Stock

logger = logging.getLogger(__name__)


# @MX:ANCHOR: [AUTO] 뉴스 크롤러에서 호출되는 핵심 스냅샷 캡처 함수
# @MX:REASON: news_crawler.py, scheduler.py 등 다수 호출처에서 사용
async def capture_price_snapshots(
    db: Session,
    article_stock_pairs: list[tuple[int, int, int | None]],
) -> int:
    """뉴스-종목 관계가 생성된 직후 가격 스냅샷을 캡처한다.

    Args:
        db: SQLAlchemy 세션
        article_stock_pairs: list of (news_id, stock_id, relation_id)
            - stock_id가 None인 항목(섹터 전용 관계)은 건너뜀 (REQ-NPI-005)

    Returns:
        캡처 성공 건수
    """
    from app.services.naver_finance import fetch_stock_fundamentals_batch

    # REQ-NPI-005: stock_id가 있는 것만 필터
    valid_pairs = [(nid, sid, rid) for nid, sid, rid in article_stock_pairs if sid]
    if not valid_pairs:
        return 0

    # 종목코드 조회
    stock_ids = list(set(sid for _, sid, _ in valid_pairs))
    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all()
    stock_map: dict[int, Stock] = {s.id: s for s in stocks}

    # 배치 가격 조회
    stock_codes = [s.stock_code for s in stocks if s.stock_code]
    prices: dict[str, object] = {}
    if stock_codes:
        try:
            prices = await fetch_stock_fundamentals_batch(stock_codes)
        except Exception as e:
            logger.error(f"가격 배치 조회 실패: {e}")
            return 0

    captured = 0
    for news_id, stock_id, relation_id in valid_pairs:
        stock = stock_map.get(stock_id)
        if not stock:
            continue

        fund = prices.get(stock.stock_code)
        current_price = fund.current_price if fund and fund.current_price else None

        # REQ-NPI-003: 장외 시간에도 마지막 종가 사용
        if not current_price:
            # REQ-NPI-004: 개별 종목 실패 시 skip하고 계속 진행
            logger.warning(f"가격 조회 실패 (stock_id={stock_id}, code={stock.stock_code}), skip")
            continue

        try:
            impact = NewsPriceImpact(
                news_id=news_id,
                stock_id=stock_id,
                relation_id=relation_id,
                price_at_news=float(current_price),
            )
            db.add(impact)
            captured += 1
        except Exception as e:
            # REQ-NPI-004: 개별 종목 실패 시 skip
            logger.error(f"스냅샷 저장 실패 (news_id={news_id}, stock_id={stock_id}): {e}")

    if captured:
        db.commit()
        logger.info(f"가격 스냅샷 {captured}건 캡처 완료")

    return captured


async def backfill_prices(db: Session) -> dict:
    """1일/5일 후 가격 반응 데이터를 backfill한다.

    REQ-NPI-006: 매일 18:30 KST에 실행
    REQ-NPI-007: 1일 경과 레코드 → price_after_1d + return_1d_pct
    REQ-NPI-008: 5일 경과 레코드 → price_after_5d + return_5d_pct
    REQ-NPI-009: API 실패 시 3회 재시도, 실패 시 null 유지

    Returns:
        {"updated_1d": N, "updated_5d": N}
    """
    from app.services.naver_finance import fetch_stock_fundamentals_batch

    now = datetime.now(timezone.utc)
    stats = {"updated_1d": 0, "updated_5d": 0}

    # 1일 이상 경과 + price_after_1d가 null인 레코드
    pending_1d = (
        db.query(NewsPriceImpact)
        .filter(
            NewsPriceImpact.price_after_1d.is_(None),
            NewsPriceImpact.captured_at <= now - timedelta(days=1),
        )
        .all()
    )

    # 5일 이상 경과 + price_after_5d가 null인 레코드
    pending_5d = (
        db.query(NewsPriceImpact)
        .filter(
            NewsPriceImpact.price_after_5d.is_(None),
            NewsPriceImpact.captured_at <= now - timedelta(days=5),
        )
        .all()
    )

    # 모든 대상 레코드의 stock_id 수집
    all_records = list(pending_1d) + list(pending_5d)
    if not all_records:
        logger.info("backfill 대상 레코드 없음")
        return stats

    stock_ids = set(r.stock_id for r in all_records)
    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all()
    stock_map: dict[int, Stock] = {s.id: s for s in stocks}

    # 가격 조회 (REQ-NPI-009: 3회 재시도)
    stock_codes = [s.stock_code for s in stocks if s.stock_code]
    prices: dict[str, object] = {}
    for attempt in range(3):
        try:
            prices = await fetch_stock_fundamentals_batch(stock_codes)
            break
        except Exception as e:
            logger.warning(f"backfill 가격 조회 재시도 {attempt + 1}/3: {e}")
            if attempt == 2:
                logger.error("backfill 가격 조회 3회 실패, null 유지")
                return stats

    # 1일 backfill
    for record in pending_1d:
        stock = stock_map.get(record.stock_id)
        if not stock:
            continue
        fund = prices.get(stock.stock_code)
        if not fund or not fund.current_price:
            continue

        record.price_after_1d = float(fund.current_price)
        record.return_1d_pct = round(
            (fund.current_price - record.price_at_news) / record.price_at_news * 100, 2
        )
        record.backfill_1d_at = now
        stats["updated_1d"] += 1

    # 5일 backfill
    for record in pending_5d:
        stock = stock_map.get(record.stock_id)
        if not stock:
            continue
        fund = prices.get(stock.stock_code)
        if not fund or not fund.current_price:
            continue

        record.price_after_5d = float(fund.current_price)
        record.return_5d_pct = round(
            (fund.current_price - record.price_at_news) / record.price_at_news * 100, 2
        )
        record.backfill_5d_at = now
        stats["updated_5d"] += 1

    db.commit()
    logger.info(f"backfill 완료: {stats}")
    return stats


async def get_news_impact(db: Session, news_id: int) -> list[dict]:
    """특정 뉴스 기사의 가격 반응 데이터를 조회한다 (REQ-NPI-010).

    Returns:
        가격 반응 레코드 리스트
    """
    impacts = (
        db.query(NewsPriceImpact)
        .filter(NewsPriceImpact.news_id == news_id)
        .all()
    )

    results = []
    # 종목명 조회
    stock_ids = [i.stock_id for i in impacts]
    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all() if stock_ids else []
    stock_map = {s.id: s for s in stocks}

    for impact in impacts:
        stock = stock_map.get(impact.stock_id)
        results.append({
            "id": impact.id,
            "stock_id": impact.stock_id,
            "stock_name": stock.name if stock else None,
            "stock_code": stock.stock_code if stock else None,
            "price_at_news": impact.price_at_news,
            "price_after_1d": impact.price_after_1d,
            "return_1d_pct": impact.return_1d_pct,
            "price_after_5d": impact.price_after_5d,
            "return_5d_pct": impact.return_5d_pct,
            "captured_at": impact.captured_at.isoformat() if impact.captured_at else None,
            "backfill_1d_at": impact.backfill_1d_at.isoformat() if impact.backfill_1d_at else None,
            "backfill_5d_at": impact.backfill_5d_at.isoformat() if impact.backfill_5d_at else None,
        })

    return results


# @MX:ANCHOR: [AUTO] API + 브리핑에서 호출되는 통계 집계 함수
# @MX:REASON: routers/stocks.py, fund_manager.py 등 다수 호출처에서 사용
async def get_stock_impact_stats(db: Session, stock_id: int, days: int = 30) -> dict:
    """종목의 뉴스-가격 반응 통계를 집계한다 (REQ-NPI-011).

    Args:
        db: SQLAlchemy 세션
        stock_id: 종목 ID
        days: 통계 집계 기간 (기본 30일)

    Returns:
        {
            "status": "sufficient" | "insufficient",
            "count": 완료된 레코드 수,
            "avg_1d": 평균 1일 수익률,
            "avg_5d": 평균 5일 수익률,
            "win_rate_1d": 1일 승률 (양수 수익률 비율),
            "win_rate_5d": 5일 승률,
            "max_return_5d": 최대 5일 수익률,
            "min_return_5d": 최소 5일 수익률,
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    completed = (
        db.query(NewsPriceImpact)
        .filter(
            NewsPriceImpact.stock_id == stock_id,
            NewsPriceImpact.captured_at >= cutoff,
            NewsPriceImpact.return_5d_pct.isnot(None),  # 5일 backfill 완료된 것만
        )
        .all()
    )

    # REQ-NPI-013: 데이터 없으면 insufficient 상태 반환
    if not completed:
        return {
            "status": "insufficient",
            "count": 0,
            "avg_1d": None,
            "avg_5d": None,
            "win_rate_1d": None,
            "win_rate_5d": None,
            "max_return_5d": None,
            "min_return_5d": None,
        }

    returns_1d = [r.return_1d_pct for r in completed if r.return_1d_pct is not None]
    returns_5d = [r.return_5d_pct for r in completed if r.return_5d_pct is not None]

    count = len(completed)
    avg_1d = round(sum(returns_1d) / len(returns_1d), 2) if returns_1d else None
    avg_5d = round(sum(returns_5d) / len(returns_5d), 2) if returns_5d else None

    win_1d = sum(1 for r in returns_1d if r > 0)
    win_5d = sum(1 for r in returns_5d if r > 0)

    return {
        "status": "sufficient",
        "count": count,
        "avg_1d": avg_1d,
        "avg_5d": avg_5d,
        "win_rate_1d": round(win_1d / len(returns_1d) * 100, 1) if returns_1d else None,
        "win_rate_5d": round(win_5d / len(returns_5d) * 100, 1) if returns_5d else None,
        "max_return_5d": round(max(returns_5d), 2) if returns_5d else None,
        "min_return_5d": round(min(returns_5d), 2) if returns_5d else None,
    }


async def cleanup_old_impacts(db: Session) -> int:
    """90일 이상 된 impact 레코드를 삭제한다 (REQ-NPI-016).

    Returns:
        삭제 건수
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    deleted = (
        db.query(NewsPriceImpact)
        .filter(NewsPriceImpact.created_at < cutoff)
        .delete(synchronize_session=False)
    )

    if deleted:
        db.commit()
        logger.info(f"90일 초과 impact 레코드 {deleted}건 삭제")

    return deleted
