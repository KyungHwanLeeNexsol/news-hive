"""시장 컨텍스트 분석 모듈.

SPEC-AI-002 REQ-AI-020: 시장 변동성 기반 포지션 사이징.
SPEC-AI-002 REQ-AI-024: 원자재 연관 종목 크로스 검증.

KOSPI 20일 표준편차로 변동성 레벨을 계산하고,
변동성에 따라 투자 비중과 confidence를 조정한다.
원자재 관련 섹터 시그널 시 원자재 가격 5일 추세를 확인하여
역행 경고(commodity_divergence)를 생성한다.
"""

import logging
import math
import time

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 시장 변동성 캐시 (동일 브리핑 사이클 내 중복 HTTP 방지)
_volatility_cache: dict = {"data": None, "timestamp": 0.0}
_VOLATILITY_CACHE_TTL = 300  # 5분

# 변동성 레벨 기준 (KOSPI 20일 일간수익률 표준편차, %)
VOLATILITY_THRESHOLDS = {
    "low": 1.0,       # < 1%
    "normal": 2.0,    # 1% ~ 2%
    "high": 3.0,      # 2% ~ 3%
    # >= 3% → extreme
}


def calculate_volatility_level(daily_returns: list[float]) -> dict:
    """KOSPI 20일 일간수익률 표준편차 기반 변동성 레벨 계산.

    Args:
        daily_returns: 최근 20일 일간수익률 리스트 (%, 최신순)
                       예: [0.5, -1.2, 0.3, ...]

    Returns:
        {
            "volatility_level": "low" | "normal" | "high" | "extreme",
            "volatility_pct": float,  # 표준편차 (%)
            "weight_multiplier": float,  # 투자비중 배수 (1.0=기본)
            "confidence_adjustment": float,  # confidence 보정값
            "tags": list[str],  # 추가 태그 (예: ["high_volatility_warning"])
        }
    """
    if not daily_returns or len(daily_returns) < 5:
        # 데이터 부족 시 기본값 반환 (graceful degradation)
        logger.warning("변동성 계산에 필요한 수익률 데이터 부족 (%d일)", len(daily_returns) if daily_returns else 0)
        return {
            "volatility_level": "normal",
            "volatility_pct": 0.0,
            "weight_multiplier": 1.0,
            "confidence_adjustment": 0.0,
            "tags": [],
        }

    # 최대 20일 데이터 사용
    returns = daily_returns[:20]
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / n
    std_dev = math.sqrt(variance)

    # 변동성 레벨 분류
    if std_dev < VOLATILITY_THRESHOLDS["low"]:
        level = "low"
    elif std_dev < VOLATILITY_THRESHOLDS["normal"]:
        level = "normal"
    elif std_dev < VOLATILITY_THRESHOLDS["high"]:
        level = "high"
    else:
        level = "extreme"

    # 포지션 사이징 조정
    weight_multiplier = 1.0
    confidence_adj = 0.0
    tags: list[str] = []

    if level == "high":
        weight_multiplier = 0.7  # 기본 비중의 70%
        tags.append("high_volatility_caution")
    elif level == "extreme":
        weight_multiplier = 0.5  # 기본 비중의 50%
        confidence_adj = -0.15
        tags.append("high_volatility_warning")

    return {
        "volatility_level": level,
        "volatility_pct": round(std_dev, 2),
        "weight_multiplier": weight_multiplier,
        "confidence_adjustment": confidence_adj,
        "tags": tags,
    }


async def get_market_volatility() -> dict:
    """KOSPI 지수 데이터로부터 시장 변동성 레벨을 계산한다.

    5분 TTL 캐시 적용 — 동일 브리핑 사이클 내 중복 HTTP 호출 방지.

    Returns:
        calculate_volatility_level()의 반환값과 동일한 구조.
        데이터 수집 실패 시 기본값(normal) 반환.
    """
    # 캐시 유효성 확인
    now = time.time()
    if _volatility_cache["data"] is not None and (now - _volatility_cache["timestamp"]) < _VOLATILITY_CACHE_TTL:
        return _volatility_cache["data"]

    try:
        from app.services.naver_finance import fetch_stock_price_history

        # KOSPI 인덱스 = 코드 "KOSPI" 대신 KODEX 200 (069500) 사용
        # 네이버 금융에서 KOSPI 지수는 개별 종목과 다른 형식이므로
        # 대표 ETF로 변동성 추정
        history = await fetch_stock_price_history("069500", pages=3)  # ~30일

        if not history or len(history) < 5:
            logger.warning("KOSPI 변동성 계산용 가격 데이터 부족")
            return calculate_volatility_level([])

        # 일간수익률 계산 (최신순)
        closes = [p.close for p in history if p.close > 0]
        if len(closes) < 5:
            return calculate_volatility_level([])

        daily_returns = []
        for i in range(len(closes) - 1):
            ret = (closes[i] - closes[i + 1]) / closes[i + 1] * 100
            daily_returns.append(ret)

        result = calculate_volatility_level(daily_returns)

        # 캐시 저장
        _volatility_cache["data"] = result
        _volatility_cache["timestamp"] = now

        return result

    except Exception as e:
        logger.error("시장 변동성 계산 실패: %s", e)
        return calculate_volatility_level([])


def format_volatility_for_briefing(volatility_info: dict) -> str:
    """데일리 브리핑에 표시할 변동성 레벨 텍스트 생성.

    Args:
        volatility_info: calculate_volatility_level() 결과

    Returns:
        브리핑 상단에 삽입할 변동성 정보 문자열
    """
    level = volatility_info.get("volatility_level", "normal")
    pct = volatility_info.get("volatility_pct", 0.0)
    weight = volatility_info.get("weight_multiplier", 1.0)
    tags = volatility_info.get("tags", [])

    level_labels = {
        "low": "낮음 (안정적)",
        "normal": "보통",
        "high": "높음 (주의)",
        "extreme": "매우 높음 (경고)",
    }

    label = level_labels.get(level, "보통")
    text = f"시장 변동성: {label} (20일 표준편차: {pct:.2f}%)"

    if weight < 1.0:
        text += f"\n  - 권장 투자비중: 기본 대비 {weight*100:.0f}%"

    if "high_volatility_warning" in tags:
        text += "\n  - [경고] 극단적 변동성 구간 — 신규 진입 최소화, confidence 하향 조정 적용"
    elif "high_volatility_caution" in tags:
        text += "\n  - [주의] 높은 변동성 구간 — 보수적 비중 권장"

    return text


# ---------------------------------------------------------------------------
# REQ-AI-024: 원자재 연관 종목 크로스 검증
# ---------------------------------------------------------------------------

# 원자재 5일 연속 하락 시 divergence 판정
COMMODITY_DIVERGENCE_DAYS = 5
COMMODITY_DIVERGENCE_CONFIDENCE_PENALTY = -0.1

# 원자재 관련 섹터 카테고리 (참고용 — 실제 매핑은 SectorCommodityRelation 테이블 사용)
_COMMODITY_SECTOR_CATEGORIES = {"철강", "정유", "화학", "비철금속", "에너지"}


def get_commodity_trend(db: Session, sector_id: int, days: int = 5) -> list[dict]:
    """특정 섹터에 연관된 원자재의 최근 가격 추세를 조회한다.

    SectorCommodityRelation 테이블을 통해 섹터에 매핑된 원자재를 찾고,
    CommodityPrice에서 최근 N일 가격 데이터를 반환한다.

    Args:
        db: DB 세션
        sector_id: 섹터 ID
        days: 조회할 일수 (기본 5일)

    Returns:
        원자재별 가격 추세 리스트
        예: [{"commodity_name": "WTI 원유", "symbol": "CL=F",
              "prices": [{"change_pct": -1.2}, ...], "consecutive_decline": 3}]
    """
    from app.models.commodity import Commodity, CommodityPrice, SectorCommodityRelation

    # 섹터에 매핑된 원자재 조회
    relations = (
        db.query(SectorCommodityRelation)
        .filter(SectorCommodityRelation.sector_id == sector_id)
        .all()
    )

    if not relations:
        return []

    results = []
    for rel in relations:
        commodity = db.query(Commodity).get(rel.commodity_id)
        if not commodity:
            continue

        # 최근 N일 가격 데이터 (최신순)
        prices = (
            db.query(CommodityPrice)
            .filter(CommodityPrice.commodity_id == commodity.id)
            .order_by(CommodityPrice.recorded_at.desc())
            .limit(days)
            .all()
        )

        if not prices:
            continue

        # 연속 하락일수 계산
        consecutive_decline = 0
        for p in prices:
            if p.change_pct is not None and p.change_pct < 0:
                consecutive_decline += 1
            else:
                break

        price_data = [
            {
                "change_pct": p.change_pct,
                "price": p.price,
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
            }
            for p in prices
        ]

        results.append({
            "commodity_id": commodity.id,
            "commodity_name": commodity.name_ko,
            "symbol": commodity.symbol,
            "correlation_type": rel.correlation_type,
            "prices": price_data,
            "consecutive_decline": consecutive_decline,
        })

    return results


def check_commodity_divergence(
    db: Session, sector_id: int, signal_direction: str
) -> dict:
    """매수 시그널과 원자재 가격 추세의 역행 여부를 확인한다.

    매수 시그널인데 관련 원자재가 5일 연속 하락 중이면
    commodity_divergence 경고를 반환한다.

    Args:
        db: DB 세션
        sector_id: 섹터 ID
        signal_direction: 시그널 방향 ("buy", "sell", "hold")

    Returns:
        역행 검사 결과
        예: {"divergence": True, "warning": "commodity_divergence",
             "confidence_adjustment": -0.1, "details": [...]}
    """
    # 매수 시그널이 아니면 역행 검사 불필요
    if signal_direction not in ("buy", "적극매수"):
        return {"divergence": False, "confidence_adjustment": 0.0}

    trends = get_commodity_trend(db, sector_id, days=COMMODITY_DIVERGENCE_DAYS)

    if not trends:
        # 원자재 데이터 없음 → 역행 검사 불가, 경고 없이 통과
        return {"divergence": False, "confidence_adjustment": 0.0}

    divergent_commodities = []
    for trend in trends:
        # positive 상관관계에서 매수 + 원자재 하락 = 역행
        # negative 상관관계에서 매수 + 원자재 상승 = 역행 (역상관)
        if trend["correlation_type"] == "positive":
            if trend["consecutive_decline"] >= COMMODITY_DIVERGENCE_DAYS:
                divergent_commodities.append({
                    "name": trend["commodity_name"],
                    "symbol": trend["symbol"],
                    "consecutive_decline": trend["consecutive_decline"],
                })
        elif trend["correlation_type"] == "negative":
            # 역상관: 원자재가 연속 상승이면 역행
            consecutive_rise = 0
            for p in trend["prices"]:
                if p["change_pct"] is not None and p["change_pct"] > 0:
                    consecutive_rise += 1
                else:
                    break
            if consecutive_rise >= COMMODITY_DIVERGENCE_DAYS:
                divergent_commodities.append({
                    "name": trend["commodity_name"],
                    "symbol": trend["symbol"],
                    "consecutive_rise": consecutive_rise,
                })

    if divergent_commodities:
        return {
            "divergence": True,
            "warning": "commodity_divergence",
            "confidence_adjustment": COMMODITY_DIVERGENCE_CONFIDENCE_PENALTY,
            "details": divergent_commodities,
        }

    return {"divergence": False, "confidence_adjustment": 0.0}


def apply_commodity_adjustment(confidence: float, divergence_result: dict) -> float:
    """원자재 역행 검사 결과에 따라 confidence를 조정한다.

    Args:
        confidence: 현재 confidence 값
        divergence_result: check_commodity_divergence() 결과

    Returns:
        조정된 confidence (최소 0.0)
    """
    adj = divergence_result.get("confidence_adjustment", 0.0)
    return max(confidence + adj, 0.0)


def format_commodity_context_for_briefing(db: Session, sector_ids: list[int]) -> str:
    """브리핑 프롬프트에 삽입할 원자재 컨텍스트 텍스트를 생성한다.

    Args:
        db: DB 세션
        sector_ids: 분석 대상 섹터 ID 리스트

    Returns:
        원자재 컨텍스트 텍스트 (빈 문자열이면 관련 데이터 없음)
    """
    if not sector_ids:
        return ""

    from app.models.sector import Sector

    all_trends: list[str] = []
    seen_commodities: set[int] = set()  # 중복 원자재 방지

    for sector_id in sector_ids:
        sector = db.query(Sector).get(sector_id)
        if not sector:
            continue

        trends = get_commodity_trend(db, sector_id)
        if not trends:
            continue

        for trend in trends:
            cid = trend["commodity_id"]
            if cid in seen_commodities:
                continue
            seen_commodities.add(cid)

            prices = trend["prices"]
            if not prices:
                continue

            # 최근 가격과 추세 요약
            latest_price = prices[0]["price"] if prices else None
            changes = [p["change_pct"] for p in prices if p["change_pct"] is not None]
            avg_change = sum(changes) / len(changes) if changes else 0.0

            decline_days = trend["consecutive_decline"]
            direction = "하락" if avg_change < 0 else "상승"

            line = (
                f"- {trend['commodity_name']}({trend['symbol']}): "
                f"현재 ${latest_price:.2f}, "
                f"5일 평균 변동률 {avg_change:+.2f}% ({direction})"
            )
            if decline_days >= COMMODITY_DIVERGENCE_DAYS:
                line += f" [경고: {decline_days}일 연속 하락]"

            all_trends.append(line)

    if not all_trends:
        return ""

    return "## 원자재 가격 동향\n" + "\n".join(all_trends)
