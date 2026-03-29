"""시장 컨텍스트 분석 모듈.

SPEC-AI-002 REQ-AI-020: 시장 변동성 기반 포지션 사이징.
KOSPI 20일 표준편차로 변동성 레벨을 계산하고,
변동성에 따라 투자 비중과 confidence를 조정한다.
"""

import logging
import math
import time

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
