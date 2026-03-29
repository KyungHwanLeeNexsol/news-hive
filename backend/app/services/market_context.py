"""시장 컨텍스트 분석 모듈.

SPEC-AI-002 REQ-AI-020: 시장 변동성 기반 포지션 사이징.
SPEC-AI-002 REQ-AI-022: 과거 유사 시장 패턴 매칭.
SPEC-AI-002 REQ-AI-024: 원자재 연관 종목 크로스 검증.

KOSPI 20일 표준편차로 변동성 레벨을 계산하고,
변동성에 따라 투자 비중과 confidence를 조정한다.
과거 유사 시장 상황의 시그널 적중률을 참조 정보로 제공한다.
원자재 관련 섹터 시그널 시 원자재 가격 5일 추세를 확인하여
역행 경고(commodity_divergence)를 생성한다.
"""

import logging
import math
import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func as sa_func
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

    # 인메모리 미스 시 Redis 복구 시도
    if _volatility_cache["data"] is None:
        try:
            from app.cache import cache_get
            redis_data = await cache_get("market:volatility")
            if redis_data and isinstance(redis_data, dict):
                _volatility_cache["data"] = redis_data
                _volatility_cache["timestamp"] = now
                return redis_data
        except Exception:
            pass

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
        # Redis write-through (TTL=300초)
        try:
            from app.cache import cache_set
            await cache_set("market:volatility", result, ttl=300)
        except Exception:
            pass

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


# ---------------------------------------------------------------------------
# REQ-AI-022: 과거 유사 시장 패턴 매칭
# ---------------------------------------------------------------------------

# 유사도 판정 기준
PATTERN_RETURN_TOLERANCE = 1.0  # KOSPI 5일 수익률 차이 허용 범위 (%p)
PATTERN_MIN_HISTORY_DAYS = 30  # 최소 이력 일수


def find_similar_market_patterns(
    db: Session,
    current_kospi_return_5d: float | None,
    current_volatility_level: str | None,
    current_momentum_sector_ids: list[int] | None = None,
) -> dict:
    """현재 시장 상황과 유사한 과거 시점을 탐색하고 시그널 적중률을 반환한다.

    유사도 기준:
    - KOSPI 5일 수익률 차이 1%p 이내
    - 변동성 레벨 동일
    - 모멘텀 섹터 1개 이상 겹침

    Args:
        db: DB 세션
        current_kospi_return_5d: 현재 KOSPI 5일 수익률 (%)
        current_volatility_level: 현재 변동성 레벨 (low/normal/high/extreme)
        current_momentum_sector_ids: 현재 모멘텀 태그가 붙은 섹터 ID 리스트

    Returns:
        {
            "has_matches": bool,
            "match_count": int,          # 매칭된 과거 시점 수
            "signal_count": int,         # 해당 시점들의 총 시그널 수
            "accuracy_pct": float | None,  # 적중률 (%)
            "avg_return_pct": float | None,  # 평균 수익률 (%)
            "matched_dates": list[str],  # 매칭된 날짜 리스트 (최근 5개)
            "sample_sufficient": bool,   # 충분한 이력 여부 (30일+)
        }
    """
    from app.models.fund_signal import FundSignal

    default_result = {
        "has_matches": False,
        "match_count": 0,
        "signal_count": 0,
        "accuracy_pct": None,
        "avg_return_pct": None,
        "matched_dates": [],
        "sample_sufficient": False,
    }

    # 기본 입력 검증
    if current_kospi_return_5d is None or current_volatility_level is None:
        logger.info("패턴 매칭에 필요한 시장 데이터 부족")
        return default_result

    # 최소 이력 일수 확인
    total_signal_days = (
        db.query(sa_func.count(sa_func.distinct(sa_func.date(FundSignal.created_at))))
        .filter(FundSignal.is_correct.isnot(None))
        .scalar()
    ) or 0

    if total_signal_days < PATTERN_MIN_HISTORY_DAYS:
        logger.info("시그널 이력 부족 (%d일 < %d일 최소 요구)", total_signal_days, PATTERN_MIN_HISTORY_DAYS)
        return {**default_result, "sample_sufficient": False}

    default_result["sample_sufficient"] = True

    # 1단계: volatility_level 동일 + 검증 완료된 시그널 조회
    past_signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.volatility_level == current_volatility_level,
            FundSignal.is_correct.isnot(None),
        )
        .all()
    )

    if not past_signals:
        logger.info("동일 변동성 레벨(%s)의 검증된 시그널 없음", current_volatility_level)
        return default_result

    # 2단계: 날짜별로 시그널 그룹핑
    signals_by_date: dict[date, list] = defaultdict(list)
    for sig in past_signals:
        sig_date = sig.created_at.date() if sig.created_at else None
        if sig_date:
            signals_by_date[sig_date].append(sig)

    # 3단계: 각 날짜에 대해 KOSPI 5일 수익률 유사도 확인
    # fund_signals에 직접 KOSPI 수익률은 없으므로,
    # PortfolioSnapshot의 daily_return을 5일 합산하거나,
    # 해당 날짜의 시그널들의 return_pct 분포로 시장 환경 추정
    # → sector_momentum 테이블의 전체 섹터 avg_return_5d 평균을 KOSPI 대리변수로 사용
    from app.models.sector_momentum import SectorMomentum

    matched_dates: list[date] = []

    for sig_date, sigs in signals_by_date.items():
        # KOSPI 5일 수익률 추정: 해당 날짜의 전 섹터 avg_return_5d 평균
        sector_returns = (
            db.query(sa_func.avg(SectorMomentum.avg_return_5d))
            .filter(SectorMomentum.date == sig_date)
            .scalar()
        )

        if sector_returns is None:
            continue

        # 수익률 차이 1%p 이내 확인
        if abs(sector_returns - current_kospi_return_5d) > PATTERN_RETURN_TOLERANCE:
            continue

        # 모멘텀 섹터 겹침 확인 (current_momentum_sector_ids가 없으면 스킵)
        if current_momentum_sector_ids:
            past_momentum_ids = {
                row[0]
                for row in db.query(SectorMomentum.sector_id)
                .filter(
                    SectorMomentum.date == sig_date,
                    SectorMomentum.momentum_tag == "momentum_sector",
                )
                .all()
            }
            if not past_momentum_ids.intersection(set(current_momentum_sector_ids)):
                continue

        matched_dates.append(sig_date)

    if not matched_dates:
        logger.info("유사 패턴 매칭 결과 없음")
        return default_result

    # 4단계: 매칭된 날짜들의 시그널 성과 통계
    matched_signals = []
    for d in matched_dates:
        matched_signals.extend(signals_by_date[d])

    total_signals = len(matched_signals)
    correct_count = sum(1 for s in matched_signals if s.is_correct is True)
    returns = [s.return_pct for s in matched_signals if s.return_pct is not None]

    accuracy = (correct_count / total_signals * 100) if total_signals > 0 else None
    avg_return = (sum(returns) / len(returns)) if returns else None

    # 최근 5개 날짜만 표시
    sorted_dates = sorted(matched_dates, reverse=True)[:5]

    return {
        "has_matches": True,
        "match_count": len(matched_dates),
        "signal_count": total_signals,
        "accuracy_pct": round(accuracy, 1) if accuracy is not None else None,
        "avg_return_pct": round(avg_return, 2) if avg_return is not None else None,
        "matched_dates": [d.isoformat() for d in sorted_dates],
        "sample_sufficient": True,
    }


def format_historical_patterns_for_briefing(
    db: Session,
    current_kospi_return_5d: float | None = None,
    current_volatility_level: str | None = None,
    current_momentum_sector_ids: list[int] | None = None,
) -> str:
    """브리핑 프롬프트에 삽입할 과거 유사 패턴 매칭 텍스트를 생성한다.

    Args:
        db: DB 세션
        current_kospi_return_5d: 현재 KOSPI 5일 수익률 (%)
        current_volatility_level: 현재 변동성 레벨
        current_momentum_sector_ids: 현재 모멘텀 섹터 ID 리스트

    Returns:
        브리핑에 삽입할 패턴 매칭 정보 문자열 (빈 문자열이면 데이터 없음)
    """
    result = find_similar_market_patterns(
        db, current_kospi_return_5d, current_volatility_level, current_momentum_sector_ids
    )

    if not result["has_matches"]:
        if not result["sample_sufficient"]:
            return ""  # 이력 부족 시 조용히 스킵
        return ""  # 매칭 결과 없으면 표시 안 함

    lines = ["## 과거 유사 시장 패턴 분석 (REQ-022)"]

    accuracy = result["accuracy_pct"]
    if accuracy is not None:
        lines.append(
            f"- 현재와 유사한 과거 시장 상황에서의 시그널 적중률: {accuracy:.1f}%"
        )

    avg_ret = result["avg_return_pct"]
    if avg_ret is not None:
        lines.append(f"- 해당 시점 시그널 평균 수익률: {avg_ret:+.2f}%")

    lines.append(f"- 매칭된 과거 시점: {result['match_count']}건 (시그널 {result['signal_count']}개)")
    lines.append(f"- 최근 매칭 날짜: {', '.join(result['matched_dates'][:3])}")

    # 적중률 기반 참고 코멘트
    if accuracy is not None:
        if accuracy >= 70:
            lines.append("- [참고] 유사 환경에서 높은 적중률을 보였으므로 현재 시그널 신뢰도 보강 가능")
        elif accuracy <= 40:
            lines.append("- [주의] 유사 환경에서 적중률이 낮았으므로 보수적 접근 권장")

    return "\n".join(lines)
