"""원자재 가격 수집 서비스.

yfinance를 사용하여 원자재 선물 가격을 수집하고,
급격한 변동 시 MacroAlert를 생성한다.
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.commodity import Commodity, CommodityPrice, SectorCommodityRelation
from app.models.macro_alert import MacroAlert

logger = logging.getLogger(__name__)

# 3% 이상 변동 시 MacroAlert 생성 기준
ALERT_THRESHOLD_PCT = 3.0

# 히스토리 인메모리 캐시: {cache_key: (timestamp, data)}
# 장기 기간(2y+)은 1시간, 단기는 10분 TTL
_history_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SHORT = 600   # 10분 (1y 이하)
_CACHE_TTL_LONG = 3600   # 1시간 (2y 이상)


def fetch_commodity_prices(db: Session) -> int:
    """모든 원자재의 최신 가격을 수집하여 DB에 저장.

    Returns:
        업데이트된 원자재 수.
    """
    import yfinance as yf

    commodities = db.query(Commodity).all()
    if not commodities:
        logger.warning("원자재 데이터가 없음 — 시드를 먼저 실행하세요")
        return 0

    symbols = [c.symbol for c in commodities]
    symbol_map = {c.symbol: c for c in commodities}

    updated = 0
    try:
        # yfinance 배치 다운로드 (1일 데이터)
        data = yf.download(symbols, period="1d", progress=False)

        if data.empty:
            logger.warning("yfinance 다운로드 결과 없음")
            return 0

        for symbol in symbols:
            commodity = symbol_map[symbol]
            try:
                # yfinance 1.x: MultiIndex columns (Price, Ticker)
                if len(symbols) == 1:
                    # 단일 심볼: columns = ['Close', 'High', ...]
                    close_price = float(data["Close"].iloc[-1])
                    open_price = float(data["Open"].iloc[-1])
                    high_price = float(data["High"].iloc[-1])
                    low_price = float(data["Low"].iloc[-1])
                    vol = data["Volume"].iloc[-1]
                else:
                    # 다중 심볼: columns = MultiIndex (Price, Ticker)
                    if symbol not in data["Close"].columns:
                        logger.debug(f"{symbol}: 데이터 없음")
                        continue
                    col = data["Close"][symbol]
                    if col.dropna().empty:
                        logger.debug(f"{symbol}: 데이터 없음 (거래일 아닌 경우)")
                        continue
                    close_price = float(col.iloc[-1])
                    open_price = float(data["Open"][symbol].iloc[-1])
                    high_price = float(data["High"][symbol].iloc[-1])
                    low_price = float(data["Low"][symbol].iloc[-1])
                    vol = data["Volume"][symbol].iloc[-1]

                volume = int(vol) if vol and vol > 0 else None

                # 전일 대비 변동률 계산
                change_pct = None
                if open_price and open_price > 0:
                    change_pct = round((close_price - open_price) / open_price * 100, 2)

                price_record = CommodityPrice(
                    commodity_id=commodity.id,
                    price=round(close_price, 4),
                    change_pct=change_pct,
                    open_price=round(open_price, 4) if open_price else None,
                    high_price=round(high_price, 4) if high_price else None,
                    low_price=round(low_price, 4) if low_price else None,
                    volume=volume,
                    source="yfinance",
                )
                db.add(price_record)
                updated += 1

            except Exception as e:
                logger.warning(f"{symbol} 가격 처리 실패: {e}")
                continue

        if updated:
            db.commit()
            logger.info(f"원자재 가격 수집 완료: {updated}/{len(symbols)}개 업데이트")

    except Exception as e:
        logger.error(f"원자재 가격 일괄 수집 실패: {e}")
        db.rollback()

    return updated


def fetch_commodity_history(symbol: str, period: str = "1mo") -> list[dict]:
    """원자재 과거 가격 데이터 조회 (OHLCV).

    Args:
        symbol: yfinance 심볼 (예: CL=F)
        period: 조회 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max)

    Returns:
        날짜별 OHLCV 리스트.
    """
    import yfinance as yf

    # 단기: 일봉, 장기(2y+): 주봉으로 데이터 포인트 수 절감
    _long_periods = {"2y", "5y", "10y", "max"}
    valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y"} | _long_periods
    if period not in valid_periods:
        period = "1mo"

    interval = "1wk" if period in _long_periods else "1d"
    cache_key = f"{symbol}:{period}:{interval}"
    ttl = _CACHE_TTL_LONG if period in _long_periods else _CACHE_TTL_SHORT

    # 캐시 확인
    cached = _history_cache.get(cache_key)
    if cached:
        ts, data = cached
        if time.time() - ts < ttl:
            logger.debug(f"{cache_key} 캐시 히트")
            return data

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)

        if hist.empty:
            return []

        result = []
        for date_idx, row in hist.iterrows():
            result.append({
                "date": date_idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 4) if row["Open"] else None,
                "high": round(float(row["High"]), 4) if row["High"] else None,
                "low": round(float(row["Low"]), 4) if row["Low"] else None,
                "close": round(float(row["Close"]), 4) if row["Close"] else None,
                "volume": int(row["Volume"]) if row["Volume"] > 0 else None,
            })

        # 캐시 저장
        _history_cache[cache_key] = (time.time(), result)
        return result

    except Exception as e:
        logger.error(f"{symbol} 히스토리 조회 실패: {e}")
        return []


def check_commodity_alerts(db: Session) -> list[MacroAlert]:
    """3% 이상 일일 변동 원자재에 대해 MacroAlert를 생성한다.

    관련 섹터 정보를 포함하여 투자자에게 원자재 급변 알림을 제공한다.

    Returns:
        생성된 MacroAlert 리스트.
    """
    commodities = db.query(Commodity).all()
    alerts_created = []

    for commodity in commodities:
        # 최신 가격 레코드 조회
        latest = (
            db.query(CommodityPrice)
            .filter(CommodityPrice.commodity_id == commodity.id)
            .order_by(CommodityPrice.recorded_at.desc())
            .first()
        )

        if not latest or latest.change_pct is None:
            continue

        abs_change = abs(latest.change_pct)
        if abs_change < ALERT_THRESHOLD_PCT:
            continue

        # 관련 섹터 조회
        relations = (
            db.query(SectorCommodityRelation)
            .filter(SectorCommodityRelation.commodity_id == commodity.id)
            .all()
        )
        sector_names = []
        for rel in relations:
            sector = db.query(Commodity).get(rel.sector_id)
            # sector 이름은 Sector 테이블에서 가져와야 함
            from app.models.sector import Sector
            sec = db.query(Sector).get(rel.sector_id)
            if sec:
                sector_names.append(sec.name)

        direction = "급등" if latest.change_pct > 0 else "급락"
        level = "critical" if abs_change >= 5.0 else "warning"

        title = f"{commodity.name_ko} {direction} ({latest.change_pct:+.1f}%)"
        description = f"{commodity.name_en}({commodity.symbol}) 가격이 {latest.change_pct:+.1f}% 변동했습니다."
        if sector_names:
            description += f" 영향 섹터: {', '.join(sector_names[:5])}"

        alert = MacroAlert(
            level=level,
            keyword=commodity.symbol,
            title=title,
            description=description,
            article_count=0,
            is_active=True,
        )
        db.add(alert)
        alerts_created.append(alert)

    if alerts_created:
        db.commit()
        logger.info(f"원자재 급변 알림 생성: {len(alerts_created)}개")

    return alerts_created
