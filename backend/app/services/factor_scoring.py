"""다중 팩터 스코어링 엔진.

4개 독립 팩터(뉴스 감성, 기술적 분석, 수급, 밸류에이션)를 각각 0-100 점수로 산출하고,
가중 합산하여 composite_score를 계산한다.
"""
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 기본 팩터 가중치 (균등)
DEFAULT_WEIGHTS: dict[str, float] = {
    "news_sentiment": 0.25,
    "technical": 0.25,
    "supply_demand": 0.25,
    "valuation": 0.25,
}


def compute_news_sentiment_score(
    news_data: list[dict],
    impact_stats: dict | None = None,
) -> int:
    """뉴스 감성 기반 점수 (0-100).

    Args:
        news_data: _gather_stock_news() 결과 리스트
        impact_stats: 섹터별 뉴스 임팩트 통계 (REQ-AI-009)
    """
    if not news_data:
        return 50  # 뉴스 없으면 중립

    score = 50.0
    for news in news_data:
        sentiment = news.get("sentiment", "neutral")
        weight = news.get("weight", 0.5)
        if sentiment == "positive":
            score += 10 * weight
        elif sentiment == "negative":
            score -= 10 * weight

    # REQ-AI-009: 뉴스 임팩트 통계 가산
    if impact_stats:
        avg_return = impact_stats.get("avg_return_5d", 0)
        # 긍정적 과거 반응이면 가산, 부정적이면 감산
        if avg_return > 0:
            score += min(15, avg_return * 3)  # 최대 +15
        elif avg_return < 0:
            score += max(-15, avg_return * 3)  # 최대 -15

    return max(0, min(100, int(score)))


def analyze_multi_timeframe(market_data: dict) -> dict:
    """REQ-AI-014: 5일/20일/60일 멀티 타임프레임 추세 분석.

    Args:
        market_data: 기술적 지표 데이터
            - sma_5_slope: 5일 이동평균 기울기 (%)
            - rsi: RSI(14)
            - sma_20_slope: 20일 이동평균 기울기 (%)
            - macd_signal: MACD 신호 (golden_cross / dead_cross)
            - price_vs_sma60: 현재가와 60일 이동평균 대비 비율 (%, 양수=위, 음수=아래)

    Returns:
        {"trend_alignment": "aligned"|"divergent"|"mixed",
         "score_adjustment": int,
         "confidence_adjustment": float,
         "short_term": "up"|"down"|"neutral",
         "mid_term": "up"|"down"|"neutral",
         "long_term": "up"|"down"|"neutral"}
    """
    result = {
        "trend_alignment": "mixed",
        "score_adjustment": 0,
        "confidence_adjustment": 0.0,
        "short_term": "neutral",
        "mid_term": "neutral",
        "long_term": "neutral",
    }

    # 단기 (5일): 5일 MA 기울기 + RSI(14)
    sma_5_slope = market_data.get("sma_5_slope")
    rsi = market_data.get("rsi")
    if sma_5_slope is not None and sma_5_slope > 0:
        result["short_term"] = "up"
    elif sma_5_slope is not None and sma_5_slope < 0:
        result["short_term"] = "down"
    # RSI가 있으면 보조 확인
    if rsi is not None:
        if rsi < 30:
            # 과매도 → 반등 기대 → 상승으로 보정
            result["short_term"] = "up"
        elif rsi > 70:
            result["short_term"] = "down"

    # 중기 (20일): 20일 MA 기울기 + MACD 신호
    sma_20_slope = market_data.get("sma_20_slope")
    macd_sig = market_data.get("macd_signal")
    if sma_20_slope is not None and sma_20_slope > 0:
        result["mid_term"] = "up"
    elif sma_20_slope is not None and sma_20_slope < 0:
        result["mid_term"] = "down"
    # MACD 보조 확인
    if macd_sig == "golden_cross":
        result["mid_term"] = "up"
    elif macd_sig == "dead_cross":
        result["mid_term"] = "down"

    # 장기 (60일): 현재가 vs 60일 MA 위치
    price_vs_sma60 = market_data.get("price_vs_sma60")
    if price_vs_sma60 is not None and price_vs_sma60 > 0:
        result["long_term"] = "up"
    elif price_vs_sma60 is not None and price_vs_sma60 < 0:
        result["long_term"] = "down"

    # 추세 정렬 판단
    directions = [result["short_term"], result["mid_term"], result["long_term"]]
    non_neutral = [d for d in directions if d != "neutral"]

    if len(non_neutral) >= 2 and all(d == non_neutral[0] for d in non_neutral):
        # 2개 이상 동일 방향 (neutral 제외) → aligned
        result["trend_alignment"] = "aligned"
        result["score_adjustment"] = 15
    elif (result["short_term"] == "up" and result["long_term"] == "down") or \
         (result["short_term"] == "down" and result["long_term"] == "up"):
        # 단기와 장기가 반대 → divergent
        result["trend_alignment"] = "divergent"
        result["confidence_adjustment"] = -0.1
    else:
        result["trend_alignment"] = "mixed"

    return result


def compute_technical_score(market_data: dict) -> int:
    """기술적 지표 기반 점수 (0-100).

    Args:
        market_data: KIS/Naver Finance 데이터 (SMA, RSI, MACD 등)
    """
    score = 50.0

    # RSI (30 이하 과매도=매수기회, 70 이상 과매수=위험)
    rsi = market_data.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 20
        elif rsi < 40:
            score += 10
        elif rsi > 70:
            score -= 20
        elif rsi > 60:
            score -= 10

    # MACD 크로스
    macd_signal = market_data.get("macd_signal")
    if macd_signal == "golden_cross":
        score += 15
    elif macd_signal == "dead_cross":
        score -= 15

    # 이동평균 정배열/역배열
    sma_alignment = market_data.get("sma_alignment")
    if sma_alignment == "bullish":
        score += 15
    elif sma_alignment == "bearish":
        score -= 15

    # 5일 추세
    trend_5d = market_data.get("price_5d_trend", 0)
    if trend_5d > 5:
        score += 10
    elif trend_5d > 0:
        score += 5
    elif trend_5d < -5:
        score -= 10
    elif trend_5d < 0:
        score -= 5

    # 볼린저 밴드 위치
    bollinger_pos = market_data.get("bollinger_position")
    if bollinger_pos == "below_lower":
        score += 10  # 하한 이탈 = 반등 기대
    elif bollinger_pos == "above_upper":
        score -= 10  # 상한 이탈 = 조정 기대

    # REQ-AI-014: 멀티 타임프레임 추세 정렬 가산
    mtf = analyze_multi_timeframe(market_data)
    score += mtf["score_adjustment"]

    return max(0, min(100, int(score)))


def detect_volume_spike(market_data: dict) -> dict:
    """REQ-AI-015: 거래량 급증 감지.

    일간 거래량이 20일 평균의 2배 이상이면 volume_spike = True.
    volume_spike + 가격 상승 → supply_demand 점수 +10.

    Args:
        market_data: volume_ratio, price_5d_trend 포함

    Returns:
        {"volume_spike": bool, "score_adjustment": int}
    """
    volume_ratio = market_data.get("volume_ratio", 1.0)
    price_trend = market_data.get("price_5d_trend", 0)

    volume_spike = volume_ratio >= 2.0
    score_adj = 0

    if volume_spike and price_trend > 0:
        # 거래량 급증 + 가격 상승 → 강한 수급 신호
        score_adj = 10

    return {"volume_spike": volume_spike, "score_adjustment": score_adj}


def compute_supply_demand_score(market_data: dict) -> int:
    """수급 기반 점수 (0-100).

    Args:
        market_data: 외국인/기관 순매수 데이터
    """
    score = 50.0

    # 외국인 순매수 (5일)
    foreign_5d = market_data.get("foreign_net_5d", 0)
    if foreign_5d > 0:
        score += min(15, foreign_5d / 10000)  # 주 수 기반 가산
    elif foreign_5d < 0:
        score -= min(15, abs(foreign_5d) / 10000)

    # 기관 순매수 (5일)
    inst_5d = market_data.get("institution_net_5d", 0)
    if inst_5d > 0:
        score += min(15, inst_5d / 10000)
    elif inst_5d < 0:
        score -= min(15, abs(inst_5d) / 10000)

    # 수급 모멘텀 (연속 매수일수)
    momentum = market_data.get("supply_momentum")
    if momentum == "strong_buy":
        score += 10
    elif momentum == "strong_sell":
        score -= 10

    # REQ-AI-015: 거래량 급증 감지 (기존 volume_ratio 가산을 통합)
    vs = detect_volume_spike(market_data)
    if vs["volume_spike"]:
        score += 10  # 거래량 2배 이상 기본 가산
        score += vs["score_adjustment"]  # 가격 상승 시 추가 +10

    return max(0, min(100, int(score)))


def compute_valuation_score(financials: dict) -> int:
    """밸류에이션 기반 점수 (0-100).

    Args:
        financials: PER, PBR, ROE, 업종 평균 등
    """
    score = 50.0

    # PER vs 업종 평균
    per = financials.get("per")
    industry_per = financials.get("industry_per")
    if per and industry_per and industry_per > 0:
        ratio = per / industry_per
        if ratio < 0.7:
            score += 20  # 업종 대비 30% 이상 저평가
        elif ratio < 1.0:
            score += 10
        elif ratio > 1.5:
            score -= 20  # 업종 대비 50% 이상 고평가
        elif ratio > 1.2:
            score -= 10

    # PBR
    pbr = financials.get("pbr")
    if pbr is not None:
        if pbr < 0.7:
            score += 15
        elif pbr < 1.0:
            score += 5
        elif pbr > 3.0:
            score -= 10

    # ROE
    roe = financials.get("roe")
    if roe is not None:
        if roe > 15:
            score += 15
        elif roe > 10:
            score += 10
        elif roe > 5:
            score += 5
        elif roe < 0:
            score -= 15

    # 배당수익률
    div_yield = financials.get("dividend_yield", 0)
    if div_yield > 4:
        score += 10
    elif div_yield > 2:
        score += 5

    return max(0, min(100, int(score)))


def compute_composite_score(
    factor_scores: dict[str, int],
    weights: dict[str, float] | None = None,
) -> float:
    """가중 합산 점수 계산.

    Args:
        factor_scores: {"news_sentiment": 70, "technical": 60, ...}
        weights: 팩터별 가중치 (기본 균등 0.25)

    Returns:
        0.0~100.0 composite score
    """
    w = weights or DEFAULT_WEIGHTS
    total = 0.0
    for factor, score in factor_scores.items():
        weight = w.get(factor, 0.25)
        total += score * weight
    return round(total, 1)


def build_factor_scores_json(
    news_data: list[dict],
    market_data: dict,
    financials: dict,
    impact_stats: dict | None = None,
    weights: dict[str, float] | None = None,
    stock_id: int | None = None,
    db: "Session | None" = None,
) -> tuple[str, float]:
    """전체 팩터 점수를 JSON 문자열과 composite_score로 반환.

    Args:
        stock_id: 지주사 할인 적용 여부 확인용 (optional)
        db: DB 세션 (stock_id와 함께 전달 시 지주사 판별 쿼리 실행)

    Returns:
        (factor_scores_json, composite_score)
    """
    scores = {
        "news_sentiment": compute_news_sentiment_score(news_data, impact_stats),
        "technical": compute_technical_score(market_data),
        "supply_demand": compute_supply_demand_score(market_data),
        "valuation": compute_valuation_score(financials),
    }

    # composite_score는 4-factor 점수만으로 계산 (mtf/volume_spike는 이미 내부에서 반영됨)
    composite = compute_composite_score(scores, weights)

    # SPEC-AI-011: 지주사 할인 적용 (-5). 운영 실체 대비 지주사 랭킹 하향 유도.
    if stock_id is not None and db is not None:
        from app.models.stock_relation import StockRelation  # 순환 임포트 방지를 위한 지연 임포트
        is_holding = (
            db.query(StockRelation)
            .filter(
                StockRelation.target_stock_id == stock_id,
                StockRelation.relation_type == "holding_company",
            )
            .first()
        ) is not None
        if is_holding:
            composite = max(0.0, round(composite - 5.0, 1))
            scores["holding_company_discount"] = -5

    # REQ-AI-014: 멀티 타임프레임 분석 결과 포함 (compute_technical_score 내부와 동일 결과 재사용)
    mtf = analyze_multi_timeframe(market_data)
    scores["trend_alignment"] = mtf["trend_alignment"]
    scores["short_term"] = mtf["short_term"]
    scores["mid_term"] = mtf["mid_term"]
    scores["long_term"] = mtf["long_term"]

    # REQ-AI-015: 거래량 급증 감지 결과 포함
    vs = detect_volume_spike(market_data)
    scores["volume_spike"] = vs["volume_spike"]
    return json.dumps(scores), composite
