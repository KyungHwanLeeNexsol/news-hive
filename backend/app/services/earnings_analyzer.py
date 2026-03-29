"""어닝 서프라이즈 예측 분석 모듈.

SPEC-AI-002 REQ-AI-018: DART 실적 공시 예정(D-5) 시점에
어닝 프리뷰 분석을 생성하고, 공시 후 정확도를 추적한다.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# 실적 관련 공시 report_type
_EARNINGS_REPORT_TYPES = {"정기공시", "실적변동"}

# 실적 관련 키워드 (report_name에서 매칭)
_EARNINGS_KEYWORDS = [
    "사업보고서",
    "반기보고서",
    "분기보고서",
    "매출액또는손익구조",
    "실적",
    "영업이익",
    "당기순이익",
]

# 서프라이즈 확률 임계값 (이상이면 confidence +0.1)
SURPRISE_CONFIDENCE_THRESHOLD = 0.6
SURPRISE_CONFIDENCE_BOOST = 0.1


def get_upcoming_earnings(db: Session, days_ahead: int = 5) -> list[dict]:
    """실적 공시 예정(D-5 이내) 종목을 조회한다.

    DART 공시 중 실적 관련 공시가 최근 등록된 종목을 찾아
    D-5 이내에 실적 발표가 예상되는 종목 리스트를 반환한다.

    Args:
        db: DB 세션
        days_ahead: 앞으로 며칠 이내의 공시를 조회할지 (기본 5일)

    Returns:
        실적 공시 예정 종목 정보 리스트
    """
    # 최근 실적 관련 공시를 조회하여 향후 실적 발표 예상 종목 파악
    # DART는 실적 공시 전에 사전 공시(정정, 예고 등)가 올라오는 패턴
    cutoff_dt = (datetime.now() - timedelta(days=days_ahead)).strftime("%Y%m%d")
    future_dt = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y%m%d")

    # 최근 실적 관련 공시가 있는 종목 조회
    disclosures = (
        db.query(Disclosure)
        .filter(
            Disclosure.stock_id.isnot(None),
            Disclosure.report_type.in_(_EARNINGS_REPORT_TYPES),
            Disclosure.rcept_dt >= cutoff_dt,
        )
        .order_by(Disclosure.rcept_dt.desc())
        .all()
    )

    if not disclosures:
        return []

    # 종목별 최신 실적 공시 그룹핑
    seen_stocks: set[int] = set()
    results: list[dict] = []

    for disc in disclosures:
        if disc.stock_id in seen_stocks:
            continue
        seen_stocks.add(disc.stock_id)

        stock = db.query(Stock).get(disc.stock_id)
        if not stock:
            continue

        results.append({
            "stock_id": disc.stock_id,
            "stock_name": stock.name,
            "stock_code": stock.stock_code,
            "sector_id": stock.sector_id,
            "disclosure_date": disc.rcept_dt,
            "report_name": disc.report_name,
            "report_type": disc.report_type,
        })

    logger.info("어닝 프리뷰 대상 종목 %d개 발견", len(results))
    return results


def analyze_earnings_preview(db: Session, stock_id: int) -> dict:
    """종목의 어닝 프리뷰 분석을 생성한다.

    과거 실적 서프라이즈 패턴, 동종 섹터 실적 동향, 뉴스 감성을 종합한다.

    Args:
        db: DB 세션
        stock_id: 분석 대상 종목 ID

    Returns:
        어닝 프리뷰 분석 결과 딕셔너리
    """
    stock = db.query(Stock).get(stock_id)
    if not stock:
        return {"status": "error", "message": "종목을 찾을 수 없습니다"}

    # 1) 과거 실적 서프라이즈 패턴 분석
    past_pattern = _analyze_past_earnings_pattern(db, stock_id)

    # 2) 동종 섹터 실적 동향
    sector_trend = _analyze_sector_earnings_trend(db, stock.sector_id, stock_id)

    # 3) 최근 뉴스 감성 분석
    news_sentiment = _analyze_recent_news_sentiment(db, stock_id)

    # 4) 서프라이즈 확률 계산
    surprise_prob = calculate_surprise_probability(db, stock_id)

    return {
        "stock_id": stock_id,
        "stock_name": stock.name,
        "past_pattern": past_pattern,
        "sector_trend": sector_trend,
        "news_sentiment": news_sentiment,
        "surprise_probability": surprise_prob,
        "confidence_adjustment": (
            SURPRISE_CONFIDENCE_BOOST if surprise_prob >= SURPRISE_CONFIDENCE_THRESHOLD else 0.0
        ),
        "status": "ok",
    }


def _analyze_past_earnings_pattern(db: Session, stock_id: int) -> dict:
    """과거 실적 공시 후 시그널 적중률로 서프라이즈 패턴을 분석한다.

    Args:
        db: DB 세션
        stock_id: 종목 ID

    Returns:
        과거 서프라이즈 패턴 요약
    """
    # 과거 실적 관련 시그널 중 검증 완료된 것 조회
    past_signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.stock_id == stock_id,
            FundSignal.is_correct.isnot(None),
        )
        .order_by(FundSignal.created_at.desc())
        .limit(10)
        .all()
    )

    if not past_signals:
        return {
            "total_signals": 0,
            "correct_count": 0,
            "hit_rate": 0.0,
            "avg_return": 0.0,
            "pattern": "insufficient_data",
        }

    correct = sum(1 for s in past_signals if s.is_correct)
    returns = [s.return_pct for s in past_signals if s.return_pct is not None]
    avg_return = sum(returns) / len(returns) if returns else 0.0

    # 패턴 분류
    hit_rate = correct / len(past_signals)
    if hit_rate >= 0.7:
        pattern = "consistently_positive"
    elif hit_rate >= 0.5:
        pattern = "mixed"
    else:
        pattern = "weak"

    return {
        "total_signals": len(past_signals),
        "correct_count": correct,
        "hit_rate": round(hit_rate, 2),
        "avg_return": round(avg_return, 2),
        "pattern": pattern,
    }


def _analyze_sector_earnings_trend(
    db: Session, sector_id: int, exclude_stock_id: int
) -> dict:
    """동종 섹터 내 다른 종목의 최근 실적 공시 동향을 분석한다.

    Args:
        db: DB 세션
        sector_id: 섹터 ID
        exclude_stock_id: 제외할 종목 ID (분석 대상 종목)

    Returns:
        섹터 실적 동향 요약
    """
    # 같은 섹터 내 다른 종목들의 최근 실적 공시
    sector_stocks = (
        db.query(Stock)
        .filter(Stock.sector_id == sector_id, Stock.id != exclude_stock_id)
        .all()
    )

    if not sector_stocks:
        return {
            "peer_count": 0,
            "recent_disclosures": 0,
            "trend": "no_peers",
        }

    peer_ids = [s.id for s in sector_stocks]
    cutoff_dt = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    # 동종 섹터 실적 공시 조회
    peer_disclosures = (
        db.query(Disclosure)
        .filter(
            Disclosure.stock_id.in_(peer_ids),
            Disclosure.report_type.in_(_EARNINGS_REPORT_TYPES),
            Disclosure.rcept_dt >= cutoff_dt,
        )
        .all()
    )

    # 동종 섹터 최근 시그널 성과
    peer_signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.stock_id.in_(peer_ids),
            FundSignal.is_correct.isnot(None),
        )
        .order_by(FundSignal.created_at.desc())
        .limit(20)
        .all()
    )

    peer_correct = sum(1 for s in peer_signals if s.is_correct) if peer_signals else 0
    peer_hit_rate = peer_correct / len(peer_signals) if peer_signals else 0.0

    # 섹터 트렌드 판단
    if peer_hit_rate >= 0.6:
        trend = "positive"
    elif peer_hit_rate >= 0.4:
        trend = "neutral"
    else:
        trend = "negative"

    return {
        "peer_count": len(sector_stocks),
        "recent_disclosures": len(peer_disclosures),
        "peer_hit_rate": round(peer_hit_rate, 2),
        "trend": trend,
    }


def _analyze_recent_news_sentiment(db: Session, stock_id: int) -> dict:
    """최근 7일 뉴스 감성을 분석한다.

    Args:
        db: DB 세션
        stock_id: 종목 ID

    Returns:
        뉴스 감성 요약
    """
    cutoff = datetime.utcnow() - timedelta(days=7)

    # 종목 관련 뉴스 조회
    news_ids = [
        r.news_id for r in
        db.query(NewsStockRelation.news_id)
        .filter(NewsStockRelation.stock_id == stock_id)
        .all()
    ]

    if not news_ids:
        return {
            "total_news": 0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "sentiment_score": 0.0,
        }

    articles = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.id.in_(news_ids),
            NewsArticle.published_at >= cutoff,
        )
        .all()
    )

    positive = sum(1 for a in articles if a.sentiment == "positive")
    negative = sum(1 for a in articles if a.sentiment == "negative")
    neutral = len(articles) - positive - negative

    # 감성 점수: -1.0 ~ +1.0
    total = len(articles)
    if total > 0:
        sentiment_score = (positive - negative) / total
    else:
        sentiment_score = 0.0

    return {
        "total_news": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "sentiment_score": round(sentiment_score, 2),
    }


def calculate_surprise_probability(db: Session, stock_id: int) -> float:
    """긍정적 어닝 서프라이즈 확률을 추정한다.

    3가지 팩터를 가중 합산하여 확률을 계산:
    - 과거 실적 적중률 (40%)
    - 동종 섹터 동향 (30%)
    - 뉴스 감성 (30%)

    Args:
        db: DB 세션
        stock_id: 종목 ID

    Returns:
        긍정적 서프라이즈 확률 (0.0 ~ 1.0)
    """
    stock = db.query(Stock).get(stock_id)
    if not stock:
        return 0.5  # 기본값

    # 1) 과거 패턴 점수 (0.0 ~ 1.0)
    past = _analyze_past_earnings_pattern(db, stock_id)
    past_score = past["hit_rate"] if past["total_signals"] > 0 else 0.5

    # 2) 섹터 동향 점수
    sector = _analyze_sector_earnings_trend(db, stock.sector_id, stock_id)
    sector_map = {"positive": 0.7, "neutral": 0.5, "negative": 0.3, "no_peers": 0.5}
    sector_score = sector_map.get(sector["trend"], 0.5)

    # 3) 뉴스 감성 점수 (-1~+1 → 0~1)
    news = _analyze_recent_news_sentiment(db, stock_id)
    news_score = (news["sentiment_score"] + 1.0) / 2.0

    # 가중 합산
    probability = (past_score * 0.4) + (sector_score * 0.3) + (news_score * 0.3)

    return round(min(max(probability, 0.0), 1.0), 2)


def apply_earnings_confidence_adjustment(
    confidence: float, surprise_prob: float
) -> float:
    """어닝 서프라이즈 확률에 따라 confidence를 조정한다.

    긍정적 서프라이즈 확률이 60% 이상이면 confidence +0.1.

    Args:
        confidence: 현재 confidence 값
        surprise_prob: 서프라이즈 확률

    Returns:
        조정된 confidence (최대 1.0)
    """
    if surprise_prob >= SURPRISE_CONFIDENCE_THRESHOLD:
        return min(confidence + SURPRISE_CONFIDENCE_BOOST, 1.0)
    return confidence


def track_earnings_accuracy(db: Session, stock_id: int) -> dict:
    """실적 공시 후 예측 vs 실제를 비교하여 정확도를 추적한다.

    최근 검증 완료된 시그널을 기반으로 어닝 관련 예측 정확도를 계산한다.

    Args:
        db: DB 세션
        stock_id: 종목 ID

    Returns:
        정확도 추적 결과
    """
    # 검증 완료된 시그널 조회
    verified_signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.stock_id == stock_id,
            FundSignal.is_correct.isnot(None),
            FundSignal.verified_at.isnot(None),
        )
        .order_by(FundSignal.created_at.desc())
        .limit(20)
        .all()
    )

    if not verified_signals:
        return {
            "status": "insufficient_data",
            "total_predictions": 0,
            "accuracy": 0.0,
        }

    correct = sum(1 for s in verified_signals if s.is_correct)
    returns = [s.return_pct for s in verified_signals if s.return_pct is not None]

    return {
        "status": "tracked",
        "total_predictions": len(verified_signals),
        "correct_predictions": correct,
        "accuracy": round(correct / len(verified_signals), 2),
        "avg_return": round(sum(returns) / len(returns), 2) if returns else 0.0,
    }


def format_earnings_for_briefing(previews: list[dict]) -> str:
    """어닝 프리뷰 정보를 브리핑 프롬프트용 텍스트로 변환한다.

    Args:
        previews: analyze_earnings_preview() 결과 리스트

    Returns:
        브리핑 프롬프트에 삽입할 텍스트
    """
    if not previews:
        return ""

    lines = ["## 어닝 프리뷰 (실적 공시 예정 종목)"]
    for p in previews:
        if p.get("status") != "ok":
            continue

        stock_name = p.get("stock_name", "알 수 없음")
        prob = p.get("surprise_probability", 0.0)
        adj = p.get("confidence_adjustment", 0.0)

        past = p.get("past_pattern", {})
        hit_rate = past.get("hit_rate", 0.0)
        avg_return = past.get("avg_return", 0.0)

        sector = p.get("sector_trend", {})
        sector_trend_label = {
            "positive": "긍정적", "neutral": "중립", "negative": "부정적", "no_peers": "비교 불가"
        }.get(sector.get("trend", "neutral"), "중립")

        news = p.get("news_sentiment", {})
        news_score = news.get("sentiment_score", 0.0)

        line = f"- {stock_name}: 긍정적 서프라이즈 확률 {prob*100:.0f}%"
        if adj > 0:
            line += f" (confidence +{adj})"
        line += f"\n  과거 적중률: {hit_rate*100:.0f}% (평균수익률 {avg_return:+.1f}%)"
        line += f", 섹터 동향: {sector_trend_label}"
        line += f", 뉴스 감성: {news_score:+.2f}"

        lines.append(line)

    return "\n".join(lines)
