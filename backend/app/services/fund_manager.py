"""AI 펀드매니저 서비스.

수집된 뉴스, 공시, 시세, 재무제표 데이터를 종합 분석하여
전문 펀드매니저 수준의 투자 시그널, 데일리 브리핑, 포트폴리오 분석을 제공한다.
"""

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.daily_briefing import DailyBriefing
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.macro_alert import MacroAlert
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.portfolio_report import PortfolioReport
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AI helper (OpenRouter primary + Gemini fallback)
# ---------------------------------------------------------------------------

from app.services.ai_client import ask_ai as _ask_ai


def _parse_json_response(text: str) -> dict | None:
    """Extract JSON from a Gemini response that may include markdown code blocks."""
    if not text:
        return None
    # Strip markdown code block
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse JSON from Gemini response: {cleaned[:200]}")
        return None


# ---------------------------------------------------------------------------
# Data gathering helpers
# ---------------------------------------------------------------------------

def _gather_sentiment_trend(db: Session, stock_id: int | None = None, sector_id: int | None = None) -> dict:
    """최근 7일 센티먼트 추이를 3일/7일 구간으로 비교한다.

    Returns:
        {"recent_3d": {"positive": N, "negative": N, "neutral": N},
         "prev_4d": {"positive": N, "negative": N, "neutral": N},
         "trend": "improving" | "worsening" | "stable",
         "score_3d": float, "score_7d": float}
    """
    now = datetime.now(timezone.utc)
    cutoff_3d = now - timedelta(days=3)
    cutoff_7d = now - timedelta(days=7)

    query = db.query(NewsArticle.sentiment, NewsArticle.published_at)
    if stock_id:
        query = (
            query.join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
            .filter(NewsStockRelation.stock_id == stock_id)
        )
    elif sector_id:
        query = (
            query.join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
            .filter(NewsStockRelation.sector_id == sector_id)
        )

    articles = query.filter(NewsArticle.published_at >= cutoff_7d).all()

    recent_3d = {"positive": 0, "negative": 0, "neutral": 0}
    prev_4d = {"positive": 0, "negative": 0, "neutral": 0}

    for sentiment, pub_at in articles:
        s = sentiment or "neutral"
        if s not in recent_3d:
            continue
        if pub_at and pub_at >= cutoff_3d:
            recent_3d[s] += 1
        else:
            prev_4d[s] += 1

    def _score(counts: dict) -> float:
        total = sum(counts.values())
        if total == 0:
            return 0.0
        return round((counts["positive"] - counts["negative"]) / total * 100, 1)

    score_3d = _score(recent_3d)
    score_7d = _score({k: recent_3d[k] + prev_4d[k] for k in recent_3d})
    score_prev = _score(prev_4d)

    # 추세 판단: 최근 3일 점수 vs 이전 4일 점수
    diff = score_3d - score_prev
    if diff > 10:
        trend = "improving"
    elif diff < -10:
        trend = "worsening"
    else:
        trend = "stable"

    return {
        "recent_3d": recent_3d,
        "prev_4d": prev_4d,
        "trend": trend,
        "score_3d": score_3d,
        "score_prev": score_prev,
    }


def _gather_stock_news(db: Session, stock_id: int, days: int = 3) -> list[dict]:
    """Gather recent news related to a stock (본문 포함, 토큰 절약)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    relations = (
        db.query(NewsStockRelation, NewsArticle)
        .join(NewsArticle, NewsStockRelation.news_id == NewsArticle.id)
        .filter(
            NewsStockRelation.stock_id == stock_id,
            NewsArticle.collected_at >= cutoff,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(10)
        .all()
    )
    results = []
    for rel, article in relations:
        entry = {
            "title": article.title,
            "sentiment": article.sentiment or "neutral",
            "date": article.published_at.strftime("%m/%d") if article.published_at else "",
            "relevance": rel.relevance or "direct",
        }
        # 본문 핵심 내용 포함 (토큰 절약: 200자로 제한)
        if article.content:
            entry["content"] = article.content[:200]
        elif article.ai_summary:
            entry["content"] = article.ai_summary[:150]
        results.append(entry)
    return results


def _gather_sector_news(db: Session, sector_id: int, days: int = 3) -> list[dict]:
    """Gather recent news related to a sector (본문 포함, 토큰 절약)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    relations = (
        db.query(NewsStockRelation, NewsArticle)
        .join(NewsArticle, NewsStockRelation.news_id == NewsArticle.id)
        .filter(
            NewsStockRelation.sector_id == sector_id,
            NewsArticle.collected_at >= cutoff,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(5)
        .all()
    )
    results = []
    for rel, article in relations:
        entry = {
            "title": article.title,
            "sentiment": article.sentiment or "neutral",
        }
        if article.content:
            entry["content"] = article.content[:200]
        elif article.ai_summary:
            entry["content"] = article.ai_summary[:150]
        results.append(entry)
    return results


def _gather_disclosures(db: Session, stock_id: int, days: int = 7) -> list[dict]:
    """Gather recent DART disclosures for a stock."""
    cutoff_str = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    disclosures = (
        db.query(Disclosure)
        .filter(
            Disclosure.stock_id == stock_id,
            Disclosure.rcept_dt >= cutoff_str,
        )
        .order_by(Disclosure.rcept_dt.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "report_name": d.report_name,
            "report_type": d.report_type,
            "date": d.rcept_dt,
            "summary": d.ai_summary[:200] if d.ai_summary else None,
        }
        for d in disclosures
    ]


def _gather_macro_alerts(db: Session) -> list[dict]:
    """Gather active macro risk alerts."""
    alerts = db.query(MacroAlert).filter(MacroAlert.is_active == True).all()  # noqa: E712
    return [
        {
            "level": a.level,
            "keyword": a.keyword,
            "title": a.title,
            "article_count": a.article_count,
        }
        for a in alerts
    ]


async def _gather_market_data(stock_code: str) -> dict:
    """Gather market data from KIS API and Naver Finance."""
    from app.services.kis_api import fetch_kis_stock_price
    from app.services.naver_finance import fetch_stock_fundamentals, fetch_stock_price_history, fetch_investor_trading

    kis_data, fundamentals, price_history, investor_data = await asyncio.gather(
        fetch_kis_stock_price(stock_code),
        fetch_stock_fundamentals(stock_code),
        fetch_stock_price_history(stock_code, pages=3),
        fetch_investor_trading(stock_code, days=5),
        return_exceptions=True,
    )

    result = {}

    if kis_data and not isinstance(kis_data, Exception):
        result["current_price"] = kis_data.current_price
        result["change_rate"] = kis_data.change_rate
        result["volume"] = kis_data.volume
        result["per"] = kis_data.per
        result["pbr"] = kis_data.pbr
        result["eps"] = kis_data.eps
        result["high_52w"] = kis_data.high_52w
        result["low_52w"] = kis_data.low_52w
        result["market_cap"] = kis_data.market_cap
        result["foreign_ratio"] = kis_data.foreign_ratio
    elif fundamentals and not isinstance(fundamentals, Exception):
        result["current_price"] = fundamentals.current_price
        result["change_rate"] = fundamentals.change_rate
        result["volume"] = fundamentals.volume
        result["eps"] = fundamentals.eps
        result["bps"] = fundamentals.bps

    if price_history and not isinstance(price_history, Exception) and len(price_history) >= 5:
        # Recent 5-day and 20-day trend
        prices = [p.close for p in price_history[:20] if p.close > 0]
        if len(prices) >= 5:
            result["price_5d_trend"] = round((prices[0] - prices[4]) / prices[4] * 100, 2)
        if len(prices) >= 20:
            result["price_20d_trend"] = round((prices[0] - prices[19]) / prices[19] * 100, 2)
            result["avg_volume_20d"] = sum(p.volume for p in price_history[:20]) // 20
        # Volatility (standard deviation of daily returns)
        if len(prices) >= 10:
            returns = [(prices[i] - prices[i + 1]) / prices[i + 1] for i in range(min(len(prices) - 1, 19))]
            avg_ret = sum(returns) / len(returns)
            variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
            result["volatility"] = round(variance ** 0.5 * 100, 2)

    # 외국인/기관 수급 데이터
    if investor_data and not isinstance(investor_data, Exception) and investor_data:
        foreign_total = sum(t.foreign_net for t in investor_data)
        institution_total = sum(t.institution_net for t in investor_data)
        result["foreign_net_5d"] = foreign_total  # 최근 5일 외국인 순매수(주)
        result["institution_net_5d"] = institution_total  # 최근 5일 기관 순매수(주)
        # 수급 방향 요약
        if foreign_total > 0 and institution_total > 0:
            result["supply_demand"] = "외국인+기관 동반 매수 (강한 수급)"
        elif foreign_total > 0:
            result["supply_demand"] = "외국인 매수, 기관 매도"
        elif institution_total > 0:
            result["supply_demand"] = "기관 매수, 외국인 매도"
        elif foreign_total < 0 and institution_total < 0:
            result["supply_demand"] = "외국인+기관 동반 매도 (수급 악화)"
        else:
            result["supply_demand"] = "수급 중립"

    return result


async def _gather_financial_data(stock_code: str) -> dict:
    """Gather financial statement data from WiseReport."""
    from app.services.financial_scraper import fetch_stock_financials, fetch_stock_valuation

    financials, valuation = await asyncio.gather(
        fetch_stock_financials(stock_code),
        fetch_stock_valuation(stock_code),
        return_exceptions=True,
    )

    result = {}

    if valuation and not isinstance(valuation, Exception):
        result["per"] = valuation.per
        result["pbr"] = valuation.pbr
        result["dividend_yield"] = valuation.dividend_yield
        result["industry_per"] = valuation.industry_per

    if financials and not isinstance(financials, Exception):
        annual = financials.get("annual", [])
        if annual:
            latest = annual[-1]
            result["latest_period"] = latest.period
            result["revenue"] = latest.revenue
            result["operating_profit"] = latest.operating_profit
            result["operating_margin"] = latest.operating_margin
            result["net_income"] = latest.net_income
            result["roe"] = latest.roe
            result["is_estimate"] = latest.is_estimate

            # YoY growth if we have at least 2 periods
            if len(annual) >= 2:
                prev = annual[-2]
                if prev.revenue and latest.revenue and prev.revenue != 0:
                    result["revenue_growth"] = round(
                        (latest.revenue - prev.revenue) / abs(prev.revenue) * 100, 1
                    )
                if prev.operating_profit and latest.operating_profit and prev.operating_profit != 0:
                    result["op_profit_growth"] = round(
                        (latest.operating_profit - prev.operating_profit) / abs(prev.operating_profit) * 100, 1
                    )

        quarter = financials.get("quarter", [])
        if quarter:
            latest_q = quarter[-1]
            result["latest_quarter"] = latest_q.period
            result["q_revenue"] = latest_q.revenue
            result["q_operating_profit"] = latest_q.operating_profit
            result["q_operating_margin"] = latest_q.operating_margin

    return result


async def _gather_peer_comparison(db: Session, stock_id: int, sector_id: int) -> list[dict]:
    """같은 섹터 내 다른 종목들과의 비교 데이터 (최대 5개).

    시가총액 상위 종목 기준으로 현재가/등락률/PER 등을 수집한다.
    """
    peers = (
        db.query(Stock)
        .filter(Stock.sector_id == sector_id, Stock.id != stock_id)
        .order_by(Stock.market_cap.desc().nullslast())
        .limit(5)
        .all()
    )

    if not peers:
        return []

    from app.services.naver_finance import fetch_stock_fundamentals

    results = []
    for peer in peers:
        entry = {"name": peer.name, "code": peer.stock_code}
        try:
            fund = await fetch_stock_fundamentals(peer.stock_code)
            if fund:
                entry["price"] = fund.current_price
                entry["change_rate"] = fund.change_rate
                if hasattr(fund, "eps") and fund.eps:
                    entry["eps"] = fund.eps
        except Exception:
            pass

        # 센티먼트 요약 (최근 3일)
        st = _gather_sentiment_trend(db, stock_id=peer.id)
        entry["sentiment_score"] = st["score_3d"]
        entry["sentiment_trend"] = st["trend"]
        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------

async def analyze_stock(db: Session, stock_id: int) -> FundSignal | None:
    """종목 종합 분석 → 투자 시그널 생성.

    뉴스, 공시, 시세, 재무제표를 종합하여 AI가 펀드매니저처럼 판단한다.
    """
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        return None

    sector = db.query(Sector).filter(Sector.id == stock.sector_id).first()

    # Gather all data in parallel
    news = _gather_stock_news(db, stock_id)
    sector_news = _gather_sector_news(db, stock.sector_id) if sector else []
    disclosures = _gather_disclosures(db, stock_id)
    macro_alerts = _gather_macro_alerts(db)
    sentiment_trend = _gather_sentiment_trend(db, stock_id=stock_id)

    # Gather async data in parallel (market, financial, peer comparison)
    coros = [
        _gather_market_data(stock.stock_code),
        _gather_financial_data(stock.stock_code),
    ]
    if sector:
        coros.append(_gather_peer_comparison(db, stock_id, stock.sector_id))

    results = await asyncio.gather(*coros)
    market_data = results[0]
    financial_data = results[1]
    peers = results[2] if sector else []

    # 과거 시그널 적중률 조회
    from app.services.signal_verifier import get_accuracy_stats
    accuracy = get_accuracy_stats(db, days=30)
    accuracy_text = "아직 검증된 시그널 없음"
    if accuracy["total"] > 0:
        accuracy_text = (
            f"최근 30일 적중률: {accuracy['accuracy']}% "
            f"({accuracy['correct']}/{accuracy['total']}건), "
            f"매수 적중률: {accuracy['buy_accuracy']}%, "
            f"매도 적중률: {accuracy['sell_accuracy']}%, "
            f"평균 수익률: {accuracy['avg_return']}%"
        )

    # Pre-compute values that would break f-string syntax
    trend_label = {'improving': '개선 중', 'worsening': '악화 중', 'stable': '안정적'}.get(
        sentiment_trend.get('trend', 'stable'), '안정적'
    )

    # Build comprehensive prompt
    prompt = f"""당신은 하버드 MBA 출신의 20년 경력 전문 펀드매니저입니다.
아래 데이터를 종합적으로 분석하여 투자 판단을 내려주세요.
뉴스의 본문 내용(content 필드)이 제공된 경우, 제목만이 아닌 본문의 구체적 수치/사실/발언을 근거로 분석하세요.

## 분석 대상
- 종목명: {stock.name}
- 종목코드: {stock.stock_code}
- 섹터: {sector.name if sector else '미분류'}

## 0. 과거 시그널 성과 (자기 피드백)
{accuracy_text}
※ 적중률이 낮다면 더 보수적으로, 높다면 현재 전략을 유지하세요.

## 1. 최근 뉴스 동향 (최근 3일)
{json.dumps(news, ensure_ascii=False, indent=2) if news else '관련 뉴스 없음'}

## 1-1. 센티먼트 추이 (최근 3일 vs 이전 4일)
- 최근 3일: 긍정 {sentiment_trend['recent_3d']['positive']}건, 부정 {sentiment_trend['recent_3d']['negative']}건, 중립 {sentiment_trend['recent_3d']['neutral']}건 (점수: {sentiment_trend['score_3d']})
- 이전 4일: 긍정 {sentiment_trend['prev_4d']['positive']}건, 부정 {sentiment_trend['prev_4d']['negative']}건, 중립 {sentiment_trend['prev_4d']['neutral']}건 (점수: {sentiment_trend['score_prev']})
- 추세: {trend_label}
※ 센티먼트가 악화되고 있다면 매수에 신중하고, 개선 중이라면 긍정적으로 평가하세요.

## 2. 섹터 뉴스 동향
{json.dumps(sector_news, ensure_ascii=False, indent=2) if sector_news else '섹터 뉴스 없음'}

## 3. DART 공시 (최근 7일)
{json.dumps(disclosures, ensure_ascii=False, indent=2) if disclosures else '최근 공시 없음'}

## 4. 시세 + 수급 데이터
{json.dumps(market_data, ensure_ascii=False, indent=2) if market_data else '시세 데이터 없음'}
※ supply_demand, foreign_net_5d, institution_net_5d 필드는 외국인/기관 수급 동향입니다.
  외국인+기관 동반 매수는 강한 매수 시그널, 동반 매도는 경계 시그널로 반영하세요.

## 5. 재무제표 데이터
{json.dumps(financial_data, ensure_ascii=False, indent=2) if financial_data else '재무 데이터 없음'}

## 6. 매크로 리스크
{json.dumps(macro_alerts, ensure_ascii=False, indent=2) if macro_alerts else '현재 매크로 리스크 없음'}

## 7. 동종업계 비교
{json.dumps(peers, ensure_ascii=False, indent=2) if peers else '동종업계 비교 데이터 없음'}
※ 동종업계 대비 밸류에이션/센티먼트/주가 흐름을 비교하여 상대적 매력도를 평가하세요.
  섹터 전체가 하락 중인데 해당 종목만 상승하면 과열 경계, 섹터 반등 시 후발주자면 기회로 판단.

## 분석 요청
위 데이터를 기반으로 전문 펀드매니저의 관점에서 종합적으로 분석하고,
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.

{{
  "signal": "buy" 또는 "sell" 또는 "hold",
  "confidence": 0.0~1.0 사이의 확신도,
  "target_price": 목표가(숫자, 추정 불가시 null),
  "stop_loss": 손절가(숫자, 추정 불가시 null),
  "reasoning": "3-5문장의 종합적인 투자 판단 근거. 뉴스/공시/재무/시세 데이터를 구체적으로 인용하여 분석.",
  "news_summary": "뉴스 동향이 주가에 미칠 영향 요약 (2-3문장)",
  "financial_summary": "재무 상태 및 밸류에이션 평가 (2-3문장)",
  "market_summary": "기술적 분석 및 수급 동향 (2-3문장)"
}}

주의사항:
- confidence가 0.7 이상이어야 buy/sell 시그널을 내세요. 확신이 부족하면 hold.
- 데이터가 부족하면 그만큼 confidence를 낮추세요.
- 목표가/손절가는 현재가 대비 합리적인 범위 내에서 설정하세요.
- 투자 판단 근거는 구체적인 데이터를 인용하여 전문적으로 작성하세요.
"""

    response = await _ask_ai(prompt)
    parsed = _parse_json_response(response)
    if not parsed:
        return None

    # 시그널 발행 시점 주가 기록 (적중률 추적용)
    price_at_signal = market_data.get("current_price") if market_data else None

    signal = FundSignal(
        stock_id=stock_id,
        signal=parsed.get("signal", "hold"),
        confidence=min(max(float(parsed.get("confidence", 0.5)), 0.0), 1.0),
        target_price=parsed.get("target_price"),
        stop_loss=parsed.get("stop_loss"),
        reasoning=parsed.get("reasoning", "분석 실패"),
        news_summary=parsed.get("news_summary"),
        financial_summary=parsed.get("financial_summary"),
        market_summary=parsed.get("market_summary"),
        price_at_signal=price_at_signal,
    )

    db.add(signal)
    db.commit()
    db.refresh(signal)
    logger.info(f"Fund signal created: {stock.name} → {signal.signal} (confidence: {signal.confidence})")
    return signal


async def generate_daily_briefing(db: Session, *, regenerate: bool = False) -> DailyBriefing | None:
    """데일리 마켓 브리핑 생성.

    최근 뉴스, 섹터 동향, 매크로 리스크를 종합하여
    펀드매니저 스타일의 시장 브리핑을 AI가 작성한다.
    """
    today = date.today()

    # Check if today's briefing already exists
    existing = db.query(DailyBriefing).filter(DailyBriefing.briefing_date == today).first()
    if existing:
        if regenerate:
            db.delete(existing)
            db.flush()
        else:
            return existing

    # Gather data
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Recent news grouped by sentiment (본문 포함)
    recent_news = (
        db.query(NewsArticle)
        .filter(NewsArticle.collected_at >= cutoff)
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
        .all()
    )

    news_by_sentiment = {"positive": [], "negative": [], "neutral": []}
    # 토큰 절약: 긍정/부정 각 5개(본문 200자), 중립 3개(제목만)
    limits = {"positive": 5, "negative": 5, "neutral": 3}
    for article in recent_news:
        s = article.sentiment or "neutral"
        if s in news_by_sentiment and len(news_by_sentiment[s]) < limits[s]:
            entry = article.title
            # 중립 뉴스는 제목만, 긍정/부정만 본문 스니펫 포함
            if s != "neutral":
                content_snippet = ""
                if article.content:
                    content_snippet = article.content[:200]
                elif article.ai_summary:
                    content_snippet = article.ai_summary[:150]
                elif article.summary:
                    content_snippet = article.summary[:150]
                if content_snippet:
                    entry += f"\n  → 내용: {content_snippet}"
            news_by_sentiment[s].append(entry)

    # 전체 시장 센티먼트 추이
    market_sentiment = _gather_sentiment_trend(db)

    # Active macro alerts
    macro_alerts = _gather_macro_alerts(db)

    # Sector info
    sectors = db.query(Sector).all()
    sector_info = [{"name": s.name, "id": s.id} for s in sectors[:20]]

    # Recent disclosures (notable ones)
    recent_disc = (
        db.query(Disclosure)
        .filter(Disclosure.rcept_dt >= (datetime.now() - timedelta(days=1)).strftime("%Y%m%d"))
        .order_by(Disclosure.rcept_dt.desc())
        .limit(10)
        .all()
    )
    disc_list = [
        {"company": d.corp_name, "report": d.report_name, "type": d.report_type}
        for d in recent_disc
    ]

    market_trend_label = {'improving': '개선 중 ↑', 'worsening': '악화 중 ↓', 'stable': '안정적 →'}.get(
        market_sentiment.get('trend', 'stable'), '안정적 →'
    )

    prompt = f"""당신은 국내 최고 자산운용사의 CIO(최고투자책임자)입니다.
오늘 날짜: {today.strftime('%Y년 %m월 %d일')}

**중요: 반드시 한국어로만 응답하세요. 영어 사용 금지.**

아래 데이터를 기반으로 오늘의 시장 데일리 브리핑을 작성하세요.
각 뉴스의 제목과 본문 내용(→ 내용:)을 반드시 읽고, 구체적 사실을 인용하며 분석하세요.
제목만 보고 추측하지 말고, 본문에 담긴 수치/사실/발언을 근거로 전문적인 분석을 작성하세요.
일반론이 아닌, 실제 데이터에 근거한 구체적 분석을 작성하세요.

## 최근 24시간 주요 뉴스
### 긍정 뉴스:
{chr(10).join(f'- {t}' for t in news_by_sentiment['positive'][:5]) or '없음'}

### 부정 뉴스:
{chr(10).join(f'- {t}' for t in news_by_sentiment['negative'][:5]) or '없음'}

### 중립 뉴스:
{chr(10).join(f'- {t}' for t in news_by_sentiment['neutral'][:3]) or '없음'}

## 시장 센티먼트 추이
- 최근 3일: 긍정 {market_sentiment['recent_3d']['positive']}건, 부정 {market_sentiment['recent_3d']['negative']}건 (점수: {market_sentiment['score_3d']})
- 이전 4일: 긍정 {market_sentiment['prev_4d']['positive']}건, 부정 {market_sentiment['prev_4d']['negative']}건 (점수: {market_sentiment['score_prev']})
- 추세: {market_trend_label}

## 매크로 리스크 현황
{json.dumps(macro_alerts, ensure_ascii=False, indent=2) if macro_alerts else '현재 특이 리스크 없음'}

## 최근 주요 공시
{json.dumps(disc_list, ensure_ascii=False, indent=2) if disc_list else '주요 공시 없음'}

## 추적 중인 섹터
{', '.join(s['name'] for s in sector_info)}

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.
모든 내용은 반드시 한국어로 작성하세요.
각 필드에 제공된 뉴스 제목을 구체적으로 언급하며 분석하세요.
{{
  "market_overview": "오늘 시장의 전반적인 분위기와 핵심 이슈를 5-7문장으로 요약. 위에 제공된 뉴스 중 핵심 뉴스를 구체적으로 언급하며 CIO답게 거시적 관점에서 시장을 해석. 일반 텍스트로 작성.",
  "sector_highlights": [
    {{"sector": "섹터명", "sentiment": "positive 또는 negative 또는 neutral", "analysis": "해당 섹터에 대한 2-3문장 분석. 관련 뉴스를 인용하며 설명."}}
  ],
  "stock_picks": [
    {{"stock": "종목명", "reason": "해당 종목을 주목해야 하는 이유 2-3문장. 관련 뉴스/공시를 인용."}}
  ],
  "risk_assessment": "위 부정 뉴스와 매크로 리스크를 구체적으로 인용하며 리스크 요인과 대응 전략을 3-5문장으로 평가. 일반 텍스트로 작성.",
  "strategy": "위 분석을 종합한 오늘의 투자 전략 제안을 3-5문장으로 작성. 구체적인 액션 아이템 포함. 일반 텍스트로 작성."
}}
sector_highlights는 3-5개 섹터 배열, stock_picks는 3-5개 종목 배열로 작성하세요.
"""

    response = await _ask_ai(prompt)
    if not response:
        # Check which providers were configured
        from app.config import settings as _s
        configured = []
        if _s.OPENROUTER_API_KEY:
            configured.append(f"OpenRouter(key={_s.OPENROUTER_API_KEY[:8]}...)")
        if _s.GEMINI_API_KEY:
            configured.append(f"Gemini(key={_s.GEMINI_API_KEY[:8]}...)")
        raise RuntimeError(
            f"모든 AI 프로바이더가 실패했습니다. 설정된 프로바이더: {configured or '없음'}. "
            "서버 로그에서 상세 에러를 확인하세요."
        )
    parsed = _parse_json_response(response)
    if not parsed:
        raise RuntimeError(f"AI 응답 JSON 파싱 실패. 원본 응답(앞 500자): {response[:500]}")

    def _to_str(val) -> str | None:
        if val is None:
            return None
        if isinstance(val, str):
            return val
        return json.dumps(val, ensure_ascii=False)

    briefing = DailyBriefing(
        briefing_date=today,
        market_overview=_to_str(parsed.get("market_overview")) or "브리핑 생성 실패",
        sector_highlights=_to_str(parsed.get("sector_highlights")),
        stock_picks=_to_str(parsed.get("stock_picks")),
        risk_assessment=_to_str(parsed.get("risk_assessment")),
        strategy=_to_str(parsed.get("strategy")),
    )

    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    logger.info(f"Daily briefing generated for {today}")
    return briefing


async def analyze_portfolio(db: Session, stock_ids: list[int]) -> PortfolioReport | None:
    """포트폴리오 종합 분석 리포트 생성.

    관심종목(워치리스트) 기반으로 섹터 분산, 리스크, 리밸런싱을 분석한다.
    """
    if not stock_ids:
        return None

    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all()
    if not stocks:
        return None

    # Gather data for each stock
    portfolio_data = []
    for stock in stocks:
        sector = db.query(Sector).filter(Sector.id == stock.sector_id).first()
        news = _gather_stock_news(db, stock.id, days=3)
        market_data = await _gather_market_data(stock.stock_code)
        financial_data = await _gather_financial_data(stock.stock_code)

        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for n in news:
            s = n.get("sentiment", "neutral")
            if s in sentiment_counts:
                sentiment_counts[s] += 1

        portfolio_data.append({
            "name": stock.name,
            "code": stock.stock_code,
            "sector": sector.name if sector else "미분류",
            "market_data": market_data,
            "financial_data": financial_data,
            "news_sentiment": sentiment_counts,
            "recent_news_count": len(news),
        })

    macro_alerts = _gather_macro_alerts(db)

    # Build sector summary
    sector_counts: dict[str, list[str]] = {}
    for pd_item in portfolio_data:
        sec = pd_item["sector"]
        sector_counts.setdefault(sec, []).append(pd_item["name"])
    sector_summary = ", ".join(f"{s}({len(stocks)})" for s, stocks in sector_counts.items())

    prompt = f"""당신은 글로벌 자산운용사의 시니어 포트폴리오 매니저입니다.
아래 포트폴리오를 전문적으로 분석하고, 각 종목에 대한 구체적 의견과 리밸런싱 전략을 제시하세요.

## 포트폴리오 구성 ({len(portfolio_data)}종목, 섹터: {sector_summary})
{json.dumps(portfolio_data, ensure_ascii=False, indent=2)}

## 매크로 리스크 현황
{json.dumps(macro_alerts, ensure_ascii=False, indent=2) if macro_alerts else '없음'}

**중요: 반드시 한국어로 응답하세요.**

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.
각 필드는 마크다운 형식으로 작성하되, 종목명은 **종목명** 형식으로 볼드 처리하세요.
수치(PER, ROE, 등락률 등)는 반드시 포함하고, 추상적 표현 대신 데이터 기반으로 서술하세요.

{{
  "overall_assessment": "## 포트폴리오 개요\\n전체 구성에 대한 한 줄 요약.\\n\\n## 종목별 평가\\n각 종목의 현재 상태와 포트폴리오 내 역할을 **종목명**: 설명 형식으로 종목별로 줄바꿈하여 작성. 현재가, 등락률, PER, ROE 등 핵심 지표를 반드시 포함.\\n\\n## 강점\\n- 포트폴리오의 강점을 bullet point로 2-3개\\n\\n## 약점\\n- 포트폴리오의 약점을 bullet point로 2-3개",

  "risk_analysis": "## 집중 리스크\\n- 단일 종목/섹터 편중 위험을 bullet point로\\n\\n## 매크로 리스크\\n- 현재 매크로 환경이 포트폴리오에 미치는 영향을 bullet point로\\n\\n## 변동성 분석\\n- 각 종목의 최근 변동성을 수치와 함께 종목별로 bullet point로\\n\\n## 종합 리스크 등급\\n5단계(매우 낮음/낮음/보통/높음/매우 높음) 중 하나로 평가하고 근거 제시",

  "sector_balance": "## 현재 섹터 구성\\n섹터별 종목 수와 비중을 표 형식 또는 bullet point로\\n\\n## 분산도 평가\\n현재 분산이 잘 되어있는지 점수(10점 만점)와 함께 평가\\n\\n## 취약 섹터\\n- 노출이 부족하거나 과다한 섹터를 bullet point로\\n\\n## 추천 섹터\\n- 편입을 고려할 섹터를 이유와 함께 bullet point로",

  "rebalancing": "## 비중 축소 추천\\n- **종목명**: 축소 이유와 구체적 근거 (현재 지표 포함)\\n\\n## 비중 확대 추천\\n- **종목명**: 확대 이유와 구체적 근거\\n\\n## 신규 편입 고려\\n- 새로 편입할 섹터/종목 제안과 이유\\n\\n## 실행 우선순위\\n1. 가장 먼저 실행할 액션\\n2. 그 다음 액션\\n3. 중기적 액션"
}}
"""

    response = await _ask_ai(prompt)
    parsed = _parse_json_response(response)
    if not parsed:
        return None

    report = PortfolioReport(
        stock_ids=",".join(str(sid) for sid in stock_ids),
        overall_assessment=parsed.get("overall_assessment", "분석 실패"),
        risk_analysis=parsed.get("risk_analysis"),
        sector_balance=parsed.get("sector_balance"),
        rebalancing=parsed.get("rebalancing"),
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info(f"Portfolio report generated for {len(stock_ids)} stocks")
    return report
