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
# Gemini helper
# ---------------------------------------------------------------------------

async def _ask_gemini(prompt: str, max_retries: int = 3) -> str | None:
    """Send a prompt to Gemini and return the response text."""
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured — skipping AI analysis")
        return None

    from google import genai

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_rate_limit and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                logger.info(f"Gemini rate limited, retrying in {wait}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Gemini API error: {e}")
                return None
    return None


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

def _gather_stock_news(db: Session, stock_id: int, days: int = 3) -> list[dict]:
    """Gather recent news related to a stock."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    relations = (
        db.query(NewsStockRelation, NewsArticle)
        .join(NewsArticle, NewsStockRelation.news_id == NewsArticle.id)
        .filter(
            NewsStockRelation.stock_id == stock_id,
            NewsArticle.collected_at >= cutoff,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(15)
        .all()
    )
    return [
        {
            "title": article.title,
            "sentiment": article.sentiment or "neutral",
            "date": article.published_at.strftime("%m/%d") if article.published_at else "",
            "relevance": rel.relevance or "direct",
        }
        for rel, article in relations
    ]


def _gather_sector_news(db: Session, sector_id: int, days: int = 3) -> list[dict]:
    """Gather recent news related to a sector."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    relations = (
        db.query(NewsStockRelation, NewsArticle)
        .join(NewsArticle, NewsStockRelation.news_id == NewsArticle.id)
        .filter(
            NewsStockRelation.sector_id == sector_id,
            NewsArticle.collected_at >= cutoff,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "title": article.title,
            "sentiment": article.sentiment or "neutral",
        }
        for rel, article in relations
    ]


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
    from app.services.naver_finance import fetch_stock_fundamentals, fetch_stock_price_history

    kis_data, fundamentals, price_history = await asyncio.gather(
        fetch_kis_stock_price(stock_code),
        fetch_stock_fundamentals(stock_code),
        fetch_stock_price_history(stock_code, pages=3),
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

    market_data, financial_data = await asyncio.gather(
        _gather_market_data(stock.stock_code),
        _gather_financial_data(stock.stock_code),
    )

    # Build comprehensive prompt
    prompt = f"""당신은 하버드 MBA 출신의 20년 경력 전문 펀드매니저입니다.
아래 데이터를 종합적으로 분석하여 투자 판단을 내려주세요.

## 분석 대상
- 종목명: {stock.name}
- 종목코드: {stock.stock_code}
- 섹터: {sector.name if sector else '미분류'}

## 1. 최근 뉴스 동향 (최근 3일)
{json.dumps(news, ensure_ascii=False, indent=2) if news else '관련 뉴스 없음'}

## 2. 섹터 뉴스 동향
{json.dumps(sector_news, ensure_ascii=False, indent=2) if sector_news else '섹터 뉴스 없음'}

## 3. DART 공시 (최근 7일)
{json.dumps(disclosures, ensure_ascii=False, indent=2) if disclosures else '최근 공시 없음'}

## 4. 시세 데이터
{json.dumps(market_data, ensure_ascii=False, indent=2) if market_data else '시세 데이터 없음'}

## 5. 재무제표 데이터
{json.dumps(financial_data, ensure_ascii=False, indent=2) if financial_data else '재무 데이터 없음'}

## 6. 매크로 리스크
{json.dumps(macro_alerts, ensure_ascii=False, indent=2) if macro_alerts else '현재 매크로 리스크 없음'}

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

    response = await _ask_gemini(prompt)
    parsed = _parse_json_response(response)
    if not parsed:
        return None

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
    )

    db.add(signal)
    db.commit()
    db.refresh(signal)
    logger.info(f"Fund signal created: {stock.name} → {signal.signal} (confidence: {signal.confidence})")
    return signal


async def generate_daily_briefing(db: Session) -> DailyBriefing | None:
    """데일리 마켓 브리핑 생성.

    최근 뉴스, 섹터 동향, 매크로 리스크를 종합하여
    펀드매니저 스타일의 시장 브리핑을 AI가 작성한다.
    """
    today = date.today()

    # Check if today's briefing already exists
    existing = db.query(DailyBriefing).filter(DailyBriefing.briefing_date == today).first()
    if existing:
        return existing

    # Gather data
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Recent news grouped by sentiment
    recent_news = (
        db.query(NewsArticle)
        .filter(NewsArticle.collected_at >= cutoff)
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
        .all()
    )

    news_by_sentiment = {"positive": [], "negative": [], "neutral": []}
    for article in recent_news:
        s = article.sentiment or "neutral"
        if s in news_by_sentiment and len(news_by_sentiment[s]) < 10:
            news_by_sentiment[s].append(article.title)

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

    prompt = f"""당신은 국내 최고 자산운용사의 CIO(최고투자책임자)입니다.
오늘 날짜: {today.strftime('%Y년 %m월 %d일')}

아래 데이터를 기반으로 오늘의 시장 데일리 브리핑을 작성하세요.

## 최근 24시간 주요 뉴스
### 긍정 뉴스:
{chr(10).join(f'- {t}' for t in news_by_sentiment['positive'][:8]) or '없음'}

### 부정 뉴스:
{chr(10).join(f'- {t}' for t in news_by_sentiment['negative'][:8]) or '없음'}

### 중립 뉴스:
{chr(10).join(f'- {t}' for t in news_by_sentiment['neutral'][:5]) or '없음'}

## 매크로 리스크 현황
{json.dumps(macro_alerts, ensure_ascii=False, indent=2) if macro_alerts else '현재 특이 리스크 없음'}

## 최근 주요 공시
{json.dumps(disc_list, ensure_ascii=False, indent=2) if disc_list else '주요 공시 없음'}

## 추적 중인 섹터
{', '.join(s['name'] for s in sector_info)}

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.
{{
  "market_overview": "오늘 시장의 전반적인 분위기와 핵심 이슈를 5-7문장으로 요약. CIO답게 거시적 관점에서 시장을 해석.",
  "sector_highlights": "오늘 주목해야 할 섹터 3-5개와 그 이유를 각 2-3문장으로 설명.",
  "stock_picks": "뉴스/공시 기반으로 오늘 특히 주목할 종목 3-5개와 이유. 각 종목별 2-3문장.",
  "risk_assessment": "현재 시장의 리스크 요인과 대응 전략을 3-5문장으로 평가.",
  "strategy": "오늘의 투자 전략 제안을 3-5문장으로 작성. 구체적인 액션 아이템 포함."
}}
"""

    response = await _ask_gemini(prompt)
    parsed = _parse_json_response(response)
    if not parsed:
        return None

    briefing = DailyBriefing(
        briefing_date=today,
        market_overview=parsed.get("market_overview", "브리핑 생성 실패"),
        sector_highlights=parsed.get("sector_highlights"),
        stock_picks=parsed.get("stock_picks"),
        risk_assessment=parsed.get("risk_assessment"),
        strategy=parsed.get("strategy"),
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

    prompt = f"""당신은 글로벌 자산운용사의 포트폴리오 매니저입니다.
아래 포트폴리오를 전문적으로 분석하고 리밸런싱 전략을 제시하세요.

## 포트폴리오 구성 ({len(portfolio_data)}종목)
{json.dumps(portfolio_data, ensure_ascii=False, indent=2)}

## 매크로 리스크 현황
{json.dumps(macro_alerts, ensure_ascii=False, indent=2) if macro_alerts else '없음'}

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.
{{
  "overall_assessment": "포트폴리오 전체 평가. 강점/약점을 5-7문장으로 분석. 각 종목의 역할과 포트폴리오 내 위치 평가.",
  "risk_analysis": "집중 리스크, 매크로 리스크 노출도, 변동성 등을 4-6문장으로 분석.",
  "sector_balance": "섹터 분산도 평가. 특정 섹터에 편중되어 있는지, 분산이 잘 되어 있는지 3-5문장으로 분석.",
  "rebalancing": "구체적인 리밸런싱 제안. 비중을 늘릴 종목, 줄일 종목, 새로 편입할 섹터 등을 5-7문장으로 제안."
}}
"""

    response = await _ask_gemini(prompt)
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
