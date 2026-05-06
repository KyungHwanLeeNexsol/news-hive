"""AI 펀드매니저 서비스.

수집된 뉴스, 공시, 시세, 재무제표 데이터를 종합 분석하여
전문 펀드매니저 수준의 투자 시그널, 데일리 브리핑, 포트폴리오 분석을 제공한다.
"""

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median

from sqlalchemy.orm import Session, selectinload

from app.models.daily_briefing import DailyBriefing
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.krx_short_selling import KrxShortSelling
from app.models.macro_alert import MacroAlert
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.portfolio_report import PortfolioReport
from app.models.sector import Sector
from app.models.securities_report import SecuritiesReport
from app.models.stock import Stock
from app.models.stock_relation import StockRelation
from app.services.ai_client import ask_ai_free as _ask_ai, ask_ai_with_openai_fallback as _ask_ai_with_model

logger = logging.getLogger(__name__)

# @MX:NOTE: confidence 임계값 단일 소스 — 프롬프트 지시/코드 가드/거래 실행 3개 레이어가 이 상수를 참조
# @MX:SPEC: SPEC-AI-007 (REQ-AI-007-001)
MIN_ACTION_CONFIDENCE: float = 0.55

# 시장 데이터 TTL 캐시: analyze_stock/선행탐지 간 1시간 내 중복 API 호출 방지
_MARKET_DATA_CACHE: dict[str, tuple[float, dict]] = {}
_MARKET_DATA_CACHE_TTL: float = 3600.0  # 1시간(초)


def _parse_json_response(text: str) -> dict | None:
    """Extract JSON from a Gemini response that may include markdown code blocks."""
    if not text:
        return None
    cleaned = text.strip()
    # 마크다운 코드블록에서 JSON 추출 (닫는 ``` 뒤에 추가 텍스트가 있어도 처리)
    code_block = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", cleaned)
    if code_block:
        candidate = code_block.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # 코드블록 없으면 직접 파싱 시도
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # JSON 오브젝트만 추출 시도
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning(f"Failed to parse JSON from Gemini response: {cleaned[:200]}")
    return None


# ---------------------------------------------------------------------------
# REQ-023: Chain-of-Thought 프롬프트 검증
# ---------------------------------------------------------------------------

# CoT 5단계 분석에서 기대하는 STEP 키워드 목록
COT_REQUIRED_STEPS = ["STEP 1", "STEP 2", "STEP 3", "STEP 4", "STEP 5"]


def validate_cot_steps(ai_response_text: str | None) -> dict:
    """AI 응답에서 CoT 5단계(STEP 1~5) 존재 여부를 검증한다.

    Args:
        ai_response_text: AI가 반환한 원본 텍스트 (JSON 포함 가능)

    Returns:
        {"complete": bool, "missing_steps": list[str], "found_steps": list[str]}
    """
    if not ai_response_text:
        return {
            "complete": False,
            "missing_steps": list(COT_REQUIRED_STEPS),
            "found_steps": [],
        }

    found = [step for step in COT_REQUIRED_STEPS if step in ai_response_text]
    missing = [step for step in COT_REQUIRED_STEPS if step not in ai_response_text]

    return {
        "complete": len(missing) == 0,
        "missing_steps": missing,
        "found_steps": found,
    }


def apply_cot_penalty(
    parsed_data: dict,
    cot_result: dict,
) -> dict:
    """CoT 검증 결과에 따라 stock_picks의 confidence를 감산하고 태그를 부여한다.

    STEP 1~5 중 하나라도 누락되면:
    - 각 stock_pick의 confidence를 0.1 감산 (최소 0.0)
    - parsed_data에 "incomplete_analysis" 태그 부여

    Args:
        parsed_data: 파싱된 AI 응답 dict
        cot_result: validate_cot_steps()의 결과

    Returns:
        수정된 parsed_data (원본 dict를 변경함)
    """
    if cot_result["complete"]:
        return parsed_data

    # 불완전 분석 태그 부여
    parsed_data["_cot_validation"] = {
        "status": "incomplete_analysis",
        "missing_steps": cot_result["missing_steps"],
        "found_steps": cot_result["found_steps"],
    }

    # stock_picks 내 각 종목의 confidence 감산은 시그널 생성 시 적용
    # (브리핑의 stock_picks는 JSON 텍스트이므로 여기서는 태그만 부여)
    logger.warning(
        "CoT 불완전 분석: 누락된 단계 %s", cot_result["missing_steps"]
    )

    return parsed_data


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


def _calculate_news_time_weight(published_at: datetime | None) -> float:
    """발행 시간 기반 뉴스 가중치 계산.

    - 0~24시간: 가중치 1.0
    - 24~48시간: 가중치 0.7
    - 48~72시간: 가중치 0.4
    - 72시간 초과: 0.0 (프롬프트에서 제외)
    """
    if not published_at:
        return 0.4  # 발행일 불명 시 기본 가중치
    now = datetime.now(timezone.utc)
    # tzinfo 불일치 방지: 양쪽 모두 naive 또는 aware로 맞춤
    if now.tzinfo is None and published_at.tzinfo is not None:
        # now가 naive (테스트 mock 등)인 경우 published_at도 naive로 변환
        published_at = published_at.replace(tzinfo=None)
    elif now.tzinfo is not None and published_at.tzinfo is None:
        # published_at이 naive이면 UTC로 간주
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours_ago = (now - published_at).total_seconds() / 3600
    if hours_ago <= 24:
        return 1.0
    elif hours_ago <= 48:
        return 0.7
    elif hours_ago <= 72:
        return 0.4
    else:
        return 0.0


def _gather_stock_news(db: Session, stock_id: int, days: int = 3) -> list[dict]:
    """종목 관련 최근 뉴스 수집 (시간 가중치 적용, 본문 포함, 토큰 절약)."""
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
        weight = _calculate_news_time_weight(article.published_at)
        # 72시간 초과 뉴스는 프롬프트에서 제외
        if weight <= 0.0:
            continue
        entry = {
            "title": f"[가중치: {weight}] {article.title}",
            "sentiment": article.sentiment or "neutral",
            "date": article.published_at.strftime("%m/%d") if article.published_at else "",
            "relevance": rel.relevance or "direct",
            "weight": weight,
        }
        # 본문 핵심 내용 포함 (토큰 절약: 200자로 제한)
        if article.content:
            entry["content"] = article.content[:200]
        elif article.ai_summary:
            entry["content"] = article.ai_summary[:150]
        results.append(entry)
    # 가중치 높은 순으로 정렬
    results.sort(key=lambda x: x["weight"], reverse=True)
    return results


def _gather_sector_news(db: Session, sector_id: int, days: int = 3) -> list[dict]:
    """섹터 관련 최근 뉴스 수집 (시간 가중치 적용, 본문 포함, 토큰 절약)."""
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
        weight = _calculate_news_time_weight(article.published_at)
        # 72시간 초과 뉴스는 프롬프트에서 제외
        if weight <= 0.0:
            continue
        entry = {
            "title": f"[가중치: {weight}] {article.title}",
            "sentiment": article.sentiment or "neutral",
            "weight": weight,
        }
        if article.content:
            entry["content"] = article.content[:200]
        elif article.ai_summary:
            entry["content"] = article.ai_summary[:150]
        results.append(entry)
    # 가중치 높은 순으로 정렬
    results.sort(key=lambda x: x["weight"], reverse=True)
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


def _gather_short_selling_data(db: Session, stock_id: int, days: int = 10) -> dict | None:
    """최근 공매도 잔고 추이 수집.

    공매도 잔고 급증은 기관의 하락 베팅 강화, 잔고 감소는 숏커버링(반등 가능성)을 시사한다.
    최근 N일 데이터를 집계하여 추이 방향(증가/감소/횡보)을 반환한다.
    """
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    records = (
        db.query(KrxShortSelling)
        .filter(
            KrxShortSelling.stock_id == stock_id,
            KrxShortSelling.trade_date >= cutoff,
        )
        .order_by(KrxShortSelling.trade_date.asc())
        .all()
    )
    if not records:
        return None

    # 최신 vs 5일 전 잔고 비교로 추이 판단
    latest = records[-1]
    oldest = records[0]
    balance_change_pct: float | None = None
    if oldest.short_balance and oldest.short_balance > 0 and latest.short_balance is not None:
        balance_change_pct = round(
            (latest.short_balance - oldest.short_balance) / oldest.short_balance * 100, 2
        )

    trend = "데이터 부족"
    if balance_change_pct is not None:
        if balance_change_pct >= 10:
            trend = "급증 (하락 베팅 강화)"
        elif balance_change_pct >= 3:
            trend = "증가"
        elif balance_change_pct <= -10:
            trend = "급감 (숏커버링, 반등 가능성)"
        elif balance_change_pct <= -3:
            trend = "감소"
        else:
            trend = "횡보"

    return {
        "latest_date": latest.trade_date.strftime("%Y-%m-%d"),
        "short_ratio": latest.short_ratio,          # 공매도 비율 (%)
        "short_balance": latest.short_balance,       # 최신 잔고 주수
        "balance_change_pct": balance_change_pct,    # N일 전 대비 변화율 (%)
        "trend": trend,
        "data_days": len(records),
    }


def _gather_securities_reports(db: Session, stock_id: int, days: int = 14) -> list[dict]:
    """최근 증권사 리포트 수집 (목표주가, 투자의견, 핵심 내용 포함).

    애널리스트 목표주가 상향/하향은 단기 주가에 직접 영향을 주므로
    analyze_stock() 프롬프트에 포함하여 AI가 컨센서스와 비교 판단할 수 있게 한다.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    reports = (
        db.query(SecuritiesReport)
        .filter(
            SecuritiesReport.stock_id == stock_id,
            SecuritiesReport.published_at >= cutoff,
        )
        .order_by(SecuritiesReport.published_at.desc())
        .limit(5)
        .all()
    )
    return [
        {
            "securities_firm": r.securities_firm,
            "title": r.title,
            "opinion": r.opinion,
            "target_price": r.target_price,
            "published_at": r.published_at.strftime("%Y-%m-%d") if r.published_at else None,
            "summary": r.content[:300] if r.content else None,
        }
        for r in reports
    ]


def _gather_forum_sentiment(db: Session, stock_id: int) -> dict | None:
    """
    # @MX:NOTE — 종토방 역발상 지표 조회. 직접 매수/매도 신호 아님 (weight: 0.2)
    StockForumHourly 테이블에서 최근 종토방 집계 데이터를 조회합니다.
    SPEC-AI-008이 배포되지 않은 경우 None 반환 (graceful fallback).
    """
    try:
        from app.models.stock_forum import StockForumHourly
    except ImportError:
        return None

    try:
        # 최근 2시간 이내 가장 최신 집계 레코드
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        record = (
            db.query(StockForumHourly)
            .filter(
                StockForumHourly.stock_id == stock_id,
                StockForumHourly.aggregated_at >= cutoff,
            )
            .order_by(StockForumHourly.aggregated_at.desc())
            .first()
        )
        if record is None:
            return None
        neutral_ratio = (record.neutral_count / record.total_posts) if record.total_posts > 0 else 0.0
        return {
            "total_posts": record.total_posts,
            "bullish_ratio": record.bullish_ratio,
            "bearish_ratio": 1.0 - record.bullish_ratio - neutral_ratio,
            "comment_volume": record.comment_volume,
            "avg_7d_volume": record.avg_7d_volume,
            "volume_surge": record.volume_surge,
            "overheating_alert": record.overheating_alert,
            "aggregated_at": record.aggregated_at.isoformat() if record.aggregated_at else None,
        }
    except Exception:
        # 테이블 미존재 시 (SPEC-AI-008 미배포) graceful fallback
        return None


# @MX:ANCHOR: analyze_stock()에서 호출되는 핵심 함수. 증권사 컨센서스 집계
# @MX:REASON: 높은 fan_in — analyze_stock()은 스케줄러/브리핑/API 모두에서 호출됨
# @MX:SPEC: SPEC-AI-009
def _gather_securities_consensus(
    db: Session,
    stock_id: int,
    current_price: int | None,
) -> dict:
    """증권사 리포트 기반 컨센서스 집계 (최근 90일).

    여러 증권사의 투자의견과 목표주가를 정규화하여 컨센서스 지표를 계산한다.
    buy_ratio, avg_target_price, premium_pct 등을 종합해 consensus_signal을 결정한다.
    """
    _EMPTY: dict = {
        "report_count": 0,
        "consensus_signal": "insufficient",
        "avg_target_price": None,
        "median_target_price": None,
        "price_range": None,
        "buy_ratio": 0.0,
        "hold_ratio": 0.0,
        "sell_ratio": 0.0,
        "premium_pct": None,
        "target_price_trend": "stable",
        "firms": [],
    }

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    reports = (
        db.query(SecuritiesReport)
        .filter(
            SecuritiesReport.stock_id == stock_id,
            SecuritiesReport.published_at >= cutoff,
        )
        .order_by(SecuritiesReport.published_at.desc())
        .all()
    )

    if not reports:
        return _EMPTY

    # 투자의견 정규화 (한국 증권사 표기 포함)
    BUY_OPINIONS = {"매수", "비중확대", "강력매수", "적극매수", "buy", "strong buy", "outperform", "overweight"}
    SELL_OPINIONS = {"매도", "비중축소", "sell", "underperform", "underweight"}

    buy_count = 0
    hold_count = 0
    sell_count = 0
    for r in reports:
        raw = (r.opinion or "").strip().lower()
        if raw in BUY_OPINIONS:
            buy_count += 1
        elif raw in SELL_OPINIONS:
            sell_count += 1
        else:
            # 미분류(HOLD_OPINIONS 및 unknown) 모두 hold로 처리
            hold_count += 1

    total = len(reports)
    buy_ratio = round(buy_count / total, 4)
    hold_ratio = round(hold_count / total, 4)
    sell_ratio = round(sell_count / total, 4)

    # 목표주가 계산
    target_prices = [r.target_price for r in reports if r.target_price is not None]
    avg_target_price: int | None = None
    median_target_price: int | None = None
    price_range: dict | None = None
    premium_pct: float | None = None

    if target_prices:
        avg_target_price = int(mean(target_prices))
        median_target_price = int(median(target_prices))
        price_range = {"min": min(target_prices), "max": max(target_prices)}
        if current_price and current_price > 0:
            premium_pct = round((avg_target_price - current_price) / current_price * 100, 1)

    # consensus_signal 결정 (우선순위 순)
    if total < 2:
        consensus_signal = "insufficient"
    elif sell_ratio >= 0.5 or (premium_pct is not None and premium_pct < 0):
        consensus_signal = "caution"
    elif total >= 3 and buy_ratio >= 0.7 and premium_pct is not None and premium_pct >= 15:
        consensus_signal = "strong_buy"
    elif buy_ratio >= 0.6 and (premium_pct is None or premium_pct >= 5):
        consensus_signal = "buy"
    else:
        consensus_signal = "neutral"

    # 목표주가 트렌드: 최근 30일 vs 31-90일 평균 비교
    now_utc = datetime.now(timezone.utc)
    recent_cutoff = now_utc - timedelta(days=30)
    old_cutoff = now_utc - timedelta(days=90)

    recent_prices = [
        r.target_price
        for r in reports
        if r.target_price is not None and r.published_at is not None and r.published_at >= recent_cutoff
    ]
    old_prices = [
        r.target_price
        for r in reports
        if r.target_price is not None
        and r.published_at is not None
        and old_cutoff <= r.published_at < recent_cutoff
    ]

    target_price_trend = "stable"
    if recent_prices and old_prices:
        recent_avg = mean(recent_prices)
        old_avg = mean(old_prices)
        if old_avg > 0:
            diff = recent_avg - old_avg
            if diff > old_avg * 0.03:
                target_price_trend = "rising"
            elif diff < old_avg * -0.03:
                target_price_trend = "falling"

    # 최근순으로 중복 없는 증권사 목록 (최대 5개)
    seen: set[str] = set()
    firms: list[str] = []
    for r in reports:
        firm = r.securities_firm
        if firm not in seen:
            seen.add(firm)
            firms.append(firm)
        if len(firms) >= 5:
            break

    return {
        "report_count": total,
        "consensus_signal": consensus_signal,
        "avg_target_price": avg_target_price,
        "median_target_price": median_target_price,
        "price_range": price_range,
        "buy_ratio": buy_ratio,
        "hold_ratio": hold_ratio,
        "sell_ratio": sell_ratio,
        "premium_pct": premium_pct,
        "target_price_trend": target_price_trend,
        "firms": firms,
    }


# ---------------------------------------------------------------------------
# SPEC-AI-003: 선행 매수 신호 탐지 (Pre-emptive Buy Signal Detection)
# ---------------------------------------------------------------------------

# @MX:ANCHOR: SPEC-AI-003 선행 탐지 파이프라인의 진입점. 5개 서브 함수가 이 흐름에 의존.
# @MX:REASON: _scan_market_stocks, _detect_* 4개 함수가 이 캐시 구조를 공유.
# @MX:SPEC: SPEC-AI-003

# 선행 신호 가중치 테이블 (REQ-AI-040)
_LEADING_SIGNAL_WEIGHTS: dict[str, int] = {
    "quiet_accumulation": 30,
    "news_divergence": 25,
    "bb_compression": 20,
    "sector_laggard": 25,
}
_LEADING_SIGNAL_STRONG_BONUS: dict[str, int] = {
    "quiet_accumulation": 15,
    "news_divergence": 15,
    "bb_compression": 10,
    "sector_laggard": 10,
}
_MULTI_SIGNAL_BONUS: int = 10


async def _scan_market_stocks(db: Session) -> list[dict]:
    """KOSPI/KOSDAQ 전종목 스캔 후 1차 필터링.

    REQ-AI-030: +3% 초과 / -5% 미만 종목 제외 (후행 추격 방지).
    시가총액 1,000억 미만 제외 (유동성 리스크).

    Args:
        db: SQLAlchemy 세션 (현재 미사용, 향후 DB 필터링 확장 대비)

    Returns:
        필터링된 종목 목록 [{stock_code, name, current_price, change_rate, market_cap, volume}]
    """
    from app.services.naver_finance import fetch_naver_stock_list

    all_items = []

    # KOSPI 1-2페이지 + KOSDAQ 1페이지 (총 약 150종목, 타임아웃 방지)
    fetch_tasks = [
        fetch_naver_stock_list("KOSPI", 1),
        fetch_naver_stock_list("KOSPI", 2),
        fetch_naver_stock_list("KOSDAQ", 1),
    ]

    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            logger.warning("[선행탐지] 전종목 스캔 페이지 조회 실패: %s", res)
            continue
        items, _ = res
        all_items.extend(items)

    # 1차 필터링
    scanned = []
    for item in all_items:
        # REQ-AI-030: 등락률 필터 (+3% 초과 OR -5% 미만 제외)
        if item.change_rate > 3.0 or item.change_rate < -5.0:
            continue
        # 시가총액 하한: 1,000억 미만 제외
        if item.market_cap < 1000:
            continue

        scanned.append({
            "stock_code": item.stock_code,
            "name": item.name,
            "current_price": item.current_price,
            "change_rate": item.change_rate,
            "market_cap": item.market_cap,
            "volume": item.volume,
        })

    logger.info("[선행탐지] 전종목 스캔: %d종목 필터링 통과 (전체 %d종목)", len(scanned), len(all_items))
    return scanned


async def _detect_quiet_accumulation(
    scanned_stocks: list[dict],
    market_data_cache: dict[str, dict],
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """조용한 수급 축적 탐지 (REQ-AI-032, REQ-AI-033).

    외국인+기관 동시 순매수 중이나 가격 미반영 (-2% ~ +2%) 종목을 탐지.

    Args:
        scanned_stocks: _scan_market_stocks 결과
        market_data_cache: 공유 시장 데이터 캐시 (중복 API 호출 방지)

    Returns:
        탐지된 후보 목록 (leading_signals 포함)
    """
    results = []

    async def _process(stock: dict) -> dict | None:
        # REQ-AI-032: -2% <= change_rate <= +2% 필터
        change_rate = stock.get("change_rate", 0.0)
        if not (-2.0 <= change_rate <= 2.0):
            return None

        stock_code = stock["stock_code"]

        # 캐시 우선 조회
        if stock_code not in market_data_cache:
            async with semaphore:
                try:
                    data = await _gather_market_data(stock_code)
                    market_data_cache[stock_code] = data
                except Exception as e:
                    logger.warning("[선행탐지] %s 시장데이터 조회 실패: %s", stock_code, e)
                    return None

        data = market_data_cache.get(stock_code, {})
        foreign_net = data.get("foreign_net_5d", 0) or 0
        institution_net = data.get("institution_net_5d", 0) or 0

        # REQ-AI-032: 외국인 OR 기관 중 하나 이상 순매수 (AND → OR로 완화, 하락장 대응)
        # strong: 둘 다 순매수, moderate: 하나만 순매수
        both_buying = foreign_net > 0 and institution_net > 0
        one_buying = foreign_net > 0 or institution_net > 0
        if not one_buying:
            return None

        # REQ-AI-033: 신호 강도 판단
        avg_volume = data.get("avg_volume_20d", 1) or 1
        net_buy_total = foreign_net + institution_net
        ratio = net_buy_total / avg_volume if avg_volume > 0 else 0

        strength = "strong" if both_buying and ratio >= 0.1 else "moderate"
        detail = (
            f"외국인 5일 순매수 {foreign_net:,}주 + 기관 {institution_net:,}주 "
            f"(거래량 대비 {ratio:.1%}), 등락률 {change_rate:.1f}%"
        )

        return {
            "stock_code": stock_code,
            "name": stock["name"],
            "current_price": stock.get("current_price"),
            "change_rate": change_rate,
            "market_cap": stock.get("market_cap"),
            "volume": stock.get("volume"),
            "leading_signals": [
                {"type": "quiet_accumulation", "strength": strength, "detail": detail}
            ],
        }

    tasks = [_process(s) for s in scanned_stocks]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("[선행탐지] quiet_accumulation 처리 오류: %s", outcome)
        elif outcome is not None:
            results.append(outcome)

    logger.info("[선행탐지] quiet_accumulation: %d개 감지", len(results))
    return results


async def _get_technical_multiplier(stock_code: str) -> float:
    """기술적 지표 상태를 confidence 승수로 변환한다 (C안: 정보 우위 스코어링).

    KS200의 Stochastic Slow + Disparity Index를 '트리거'가 아닌 '승수'로 활용.
    - 뉴스 시그널이 트리거, 기술적 지표가 진입 품질을 보강/억제.
    - 과매도 상태 = KS200과 같은 방향 진입 → confidence 증폭
    - 과매수 상태 = 이미 오른 종목 진입 차단 → confidence 억제

    Returns: 1.0 (중립), 1.3 (과매도), 0.75 (과매수), 1.15 / 0.88 (부분)
    """
    from app.services.naver_finance import fetch_stock_price_history
    from app.services.ks200_signal import (
        calculate_stochastics_slow,
        calculate_disparity,
        STOCH_LOWER,
        STOCH_UPPER,
        DISP_LOWER,
        DISP_UPPER,
    )

    try:
        prices = await fetch_stock_price_history(stock_code, pages=3)
        if not prices or len(prices) < 21:
            return 1.0

        curr_stoch, _ = calculate_stochastics_slow(prices)
        curr_disp, _ = calculate_disparity(prices)

        if curr_stoch is None or curr_disp is None:
            return 1.0

        # 두 지표 모두 과매수: 진입 품질 낮음 → 25% 억제 (상승장 강제 차단 방지)
        if curr_stoch > STOCH_UPPER and curr_disp > DISP_UPPER:
            return 0.75
        # 두 지표 모두 과매도: 진입 품질 우수 (KS200 진입 조건과 일치) → 30% 증폭
        if curr_stoch < STOCH_LOWER and curr_disp < DISP_LOWER:
            return 1.3
        # 한 지표만 과매수
        if curr_stoch > STOCH_UPPER or curr_disp > DISP_UPPER:
            return 0.88
        # 한 지표만 과매도
        if curr_stoch < STOCH_LOWER or curr_disp < DISP_LOWER:
            return 1.15

        return 1.0
    except Exception:
        # 지표 계산 실패 시 중립값 반환 — 시그널 생성 중단 없음
        return 1.0


async def _detect_news_price_divergence(
    scanned_stocks: list[dict],
    db: Session,
    recent_news: list,
) -> list[dict]:
    """뉴스-가격 괴리 탐지 (REQ-AI-034, REQ-AI-035).

    최근 3시간 내 긍정 뉴스가 있으나 가격이 아직 미반응 (change_rate < 1%) 종목 탐지.

    Args:
        scanned_stocks: _scan_market_stocks 결과
        db: SQLAlchemy 세션
        recent_news: 최근 뉴스 목록 (현재 미사용, DB 직접 쿼리)

    Returns:
        탐지된 후보 목록 (leading_signals 포함)
    """
    from app.models.news_relation import NewsStockRelation
    from app.models.news import NewsArticle
    from datetime import datetime, timedelta, timezone

    # 최근 3시간 이내 긍정 감성 뉴스-종목 관계 조회
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    positive_sentiments = ("positive", "strong_positive")

    try:
        relations = (
            db.query(NewsStockRelation)
            .join(NewsArticle, NewsStockRelation.news_id == NewsArticle.id)
            .filter(
                NewsArticle.collected_at >= cutoff,
                NewsStockRelation.relation_sentiment.in_(positive_sentiments),
                NewsStockRelation.stock_id.isnot(None),
            )
            .all()
        )
    except Exception as e:
        logger.warning("[선행탐지] 뉴스-가격 괴리 DB 쿼리 실패: %s", e)
        return []

    # 종목코드 → 긍정 뉴스 수 집계 (stock 관계 통해 stock_code 획득)
    from app.models.stock import Stock as StockModel

    # stock_id → stock_code 매핑
    stock_ids = list({r.stock_id for r in relations if r.stock_id})
    if not stock_ids:
        return []

    stocks = db.query(StockModel).filter(StockModel.id.in_(stock_ids)).all()
    stock_id_to_code = {s.id: s.stock_code for s in stocks}

    news_count_by_code: dict[str, int] = {}
    for rel in relations:
        code = stock_id_to_code.get(rel.stock_id)
        if code:
            news_count_by_code[code] = news_count_by_code.get(code, 0) + 1

    # scanned_stocks와 교차 검증
    scanned_map = {s["stock_code"]: s for s in scanned_stocks}

    results = []
    for code, count in news_count_by_code.items():
        stock = scanned_map.get(code)
        if not stock:
            continue

        # REQ-AI-034: change_rate < 1% (가격 미반응)
        if stock.get("change_rate", 0) >= 1.0:
            continue

        # REQ-AI-035: 긍정 뉴스 2건 이상 → 강함
        strength = "strong" if count >= 2 else "moderate"
        detail = f"최근 3시간 내 긍정 뉴스 {count}건, 등락률 {stock.get('change_rate', 0):.1f}%"

        results.append({
            "stock_code": code,
            "name": stock["name"],
            "current_price": stock.get("current_price"),
            "change_rate": stock.get("change_rate"),
            "market_cap": stock.get("market_cap"),
            "volume": stock.get("volume"),
            "leading_signals": [
                {"type": "news_divergence", "strength": strength, "detail": detail}
            ],
        })

    logger.info("[선행탐지] news_divergence: %d개 감지", len(results))
    return results


async def _detect_bb_compression(
    scanned_stocks: list[dict],
    market_data_cache: dict[str, dict],
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """볼린저밴드 수축 탐지 (REQ-AI-036, REQ-AI-037).

    BB 폭이 20일 평균의 50% 미만 + 거래량 수축 + 상향 추세 종목 탐지.
    bb_compression은 항상 "moderate" 강도 (SPEC 명세).

    Args:
        scanned_stocks: _scan_market_stocks 결과
        market_data_cache: 공유 시장 데이터 캐시

    Returns:
        탐지된 후보 목록 (leading_signals 포함)
    """
    from app.services.naver_finance import fetch_stock_price_history
    import statistics

    results = []

    async def _process(stock: dict) -> dict | None:
        stock_code = stock["stock_code"]

        # 시장 데이터 캐시 조회 (없으면 수집)
        if stock_code not in market_data_cache:
            async with semaphore:
                try:
                    data = await _gather_market_data(stock_code)
                    market_data_cache[stock_code] = data
                except Exception as e:
                    logger.warning("[선행탐지] %s 시장데이터 조회 실패: %s", stock_code, e)
                    return None

        data = market_data_cache.get(stock_code, {})

        # REQ-AI-037: sma_20_slope < 0 → 하향 추세 제외
        sma_20_slope = data.get("sma_20_slope", 0.0) or 0.0
        if sma_20_slope < 0:
            return None

        volume_ratio = data.get("volume_ratio", 1.0) or 1.0
        # volume_ratio >= 0.9 → 거래량 수축 아님 (0.7 → 0.9로 완화)
        if volume_ratio >= 0.9:
            return None

        # 20일 평균 BB폭 계산 (가격 히스토리에서 슬라이딩 윈도우)
        try:
            async with semaphore:
                price_history = await fetch_stock_price_history(stock_code, pages=3)
        except Exception as e:
            logger.warning("[선행탐지] %s 가격 히스토리 조회 실패: %s", stock_code, e)
            return None

        # 20일 미만 히스토리 → 조용히 건너뜀
        closes = [p.close for p in price_history if p.close > 0]
        if len(closes) < 20:
            return None

        # 현재 BB폭 (캐시 데이터 우선, 없으면 계산)
        current_bb_width = data.get("bb_width")
        if current_bb_width is None:
            # 최근 20일로 BB폭 계산: stddev * 2 * 2 / sma_20
            recent_closes = closes[:20]
            sma_20 = sum(recent_closes) / 20
            if sma_20 > 0:
                std = statistics.stdev(recent_closes)
                current_bb_width = (std * 4) / sma_20
            else:
                return None

        # 20일 평균 BB폭: 슬라이딩 윈도우 20개 구간의 BB폭 평균
        bb_widths = []
        for i in range(min(20, len(closes) - 19)):
            window = closes[i : i + 20]
            sma = sum(window) / 20
            if sma > 0:
                std = statistics.stdev(window)
                bb_widths.append((std * 4) / sma)

        if not bb_widths:
            return None

        avg_20d_bb_width = sum(bb_widths) / len(bb_widths)

        # REQ-AI-036: 현재 BB폭 < 20일 평균의 70% (50% → 70%로 완화)
        if current_bb_width >= avg_20d_bb_width * 0.7:
            return None

        detail = (
            f"BB폭 {current_bb_width:.3f} (20일 평균 {avg_20d_bb_width:.3f}의 "
            f"{current_bb_width/avg_20d_bb_width:.0%}), "
            f"거래량비 {volume_ratio:.2f}"
        )

        return {
            "stock_code": stock_code,
            "name": stock["name"],
            "current_price": stock.get("current_price"),
            "change_rate": stock.get("change_rate"),
            "market_cap": stock.get("market_cap"),
            "volume": stock.get("volume"),
            "leading_signals": [
                # bb_compression은 항상 "moderate" (SPEC 4.4 명세)
                {"type": "bb_compression", "strength": "moderate", "detail": detail}
            ],
        }

    tasks = [_process(s) for s in scanned_stocks]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("[선행탐지] bb_compression 처리 오류: %s", outcome)
        elif outcome is not None:
            results.append(outcome)

    logger.info("[선행탐지] bb_compression: %d개 감지", len(results))
    return results


async def _detect_sector_laggards(
    scanned_stocks: list[dict],
    db: Session,
    market_data_cache: dict[str, dict],
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """섹터 로테이션 낙오자 탐지 (REQ-AI-038, REQ-AI-039).

    모멘텀 섹터 내 5일 수익률이 섹터 평균 미만인 종목을 탐지.

    Args:
        scanned_stocks: _scan_market_stocks 결과
        db: SQLAlchemy 세션
        market_data_cache: 공유 시장 데이터 캐시

    Returns:
        탐지된 후보 목록 (leading_signals 포함)
    """
    from app.services.sector_momentum import detect_momentum_sectors
    from app.models.stock import Stock as StockModel

    try:
        momentum_sectors = detect_momentum_sectors(db)
    except Exception as e:
        logger.warning("[선행탐지] 섹터 모멘텀 조회 실패: %s", e)
        return []

    if not momentum_sectors:
        return []

    # sector_id → avg_return 맵
    sector_avg_map = {s["sector_id"]: s["avg_return"] for s in momentum_sectors}
    sector_id_set = set(sector_avg_map.keys())

    # scanned_stocks 코드 집합
    scanned_codes = {s["stock_code"] for s in scanned_stocks}
    scanned_map = {s["stock_code"]: s for s in scanned_stocks}

    # 모멘텀 섹터 + scanned 종목 교집합만 조회 (DB 부하 최소화)
    scanned_codes_list = list(scanned_codes)
    try:
        stocks_in_sector = (
            db.query(StockModel)
            .filter(
                StockModel.sector_id.in_(sector_id_set),
                StockModel.stock_code.in_(scanned_codes_list),
            )
            .all()
        )
    except Exception as e:
        logger.warning("[선행탐지] 섹터 종목 조회 실패: %s", e)
        return []

    results = []

    async def _process(stock_obj) -> dict | None:
        code = stock_obj.stock_code
        if code not in scanned_codes:
            return None

        sector_avg = sector_avg_map.get(stock_obj.sector_id, 0.0)
        stock = scanned_map[code]

        # 캐시에서 5일 수익률 조회 (없으면 수집)
        if code not in market_data_cache:
            async with semaphore:
                try:
                    data = await _gather_market_data(code)
                    market_data_cache[code] = data
                except Exception as e:
                    logger.warning("[선행탐지] %s 시장데이터 조회 실패: %s", code, e)
                    return None

        data = market_data_cache.get(code, {})
        stock_5d_return = data.get("price_5d_trend", 0.0) or 0.0

        # REQ-AI-038: 종목 5일 수익률 < 섹터 평균
        if stock_5d_return >= sector_avg:
            return None

        # REQ-AI-039: 괴리 >= 3%p → 강함
        gap = sector_avg - stock_5d_return
        strength = "strong" if gap >= 3.0 else "moderate"
        detail = (
            f"섹터 5일 수익률 {sector_avg:.1f}% vs 종목 {stock_5d_return:.1f}% "
            f"(괴리 {gap:.1f}%p)"
        )

        return {
            "stock_code": code,
            "name": stock["name"],
            "current_price": stock.get("current_price"),
            "change_rate": stock.get("change_rate"),
            "market_cap": stock.get("market_cap"),
            "volume": stock.get("volume"),
            "leading_signals": [
                {"type": "sector_laggard", "strength": strength, "detail": detail}
            ],
        }

    tasks = [_process(s) for s in stocks_in_sector]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("[선행탐지] sector_laggard 처리 오류: %s", outcome)
        elif outcome is not None:
            results.append(outcome)

    logger.info("[선행탐지] sector_laggard: %d개 감지", len(results))
    return results


async def _gather_disclosure_candidates(db: Session) -> list[dict]:
    """공시 기반 미반영 호재 후보 수집 (SPEC-AI-004, REQ-DISC-007).

    unreflected_gap >= 15이고 최근 24시간 내 공시에서 FundSignal(signal_type="disclosure_impact")가
    생성된 종목을 후보로 반환. AI 브리핑에 공시 맥락을 주입하기 위한 데이터.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    try:
        # 최근 24시간 내 미반영 갭 공시
        disclosures = (
            db.query(Disclosure)
            .join(Stock, Disclosure.stock_id == Stock.id)
            .filter(
                Disclosure.impact_score >= 20,
                Disclosure.unreflected_gap >= 15,
                Disclosure.disclosed_at >= cutoff,
            )
            .order_by(Disclosure.unreflected_gap.desc())
            .limit(5)
            .all()
        )
    except Exception as e:
        logger.warning("[공시후보] DB 쿼리 실패: %s", e)
        return []

    if not disclosures:
        return []

    candidates = []
    for disc in disclosures:
        if not disc.stock_id:
            continue

        stock = db.query(Stock).filter(Stock.id == disc.stock_id).first()
        if not stock:
            continue

        # 시세 데이터 조회
        market_data: dict = {}
        if stock.stock_code:
            try:
                market_data = await _gather_market_data(stock.stock_code)
            except Exception:
                pass

        candidates.append({
            "name": stock.name,
            "code": stock.stock_code or "",
            "sector": stock.sector.name if stock.sector else "미분류",
            "news_count": 0,
            "disclosure_type": disc.report_type,
            "impact_score": disc.impact_score,
            "unreflected_gap": disc.unreflected_gap,
            "reflected_pct": disc.reflected_pct,
            "disclosure_summary": disc.report_name,
            "leading_signals": [
                {
                    "type": "disclosure_impact",
                    "strength": "strong" if (disc.unreflected_gap or 0) >= 25 else "moderate",
                    "detail": (
                        f"공시: {disc.report_name[:50]}, "
                        f"충격 {disc.impact_score:.0f}점, "
                        f"미반영 갭 {disc.unreflected_gap:.1f}점"
                    ),
                }
            ],
            **{k: v for k, v in market_data.items() if v is not None},
        })

    logger.info("[공시후보] %d개 후보 수집", len(candidates))
    return candidates


async def _gather_leading_candidates(
    db: Session,
    recent_news: list | None = None,
) -> list[dict]:
    """선행 매수 신호 탐지 오케스트레이터 (SPEC-AI-003).

    4개 선행 지표를 병렬 실행하여 후보를 수집, 점수 합산 후 상위 10개 반환.
    REQ-AI-040: 복수 지표 종목 가중 점수 합산.
    REQ-AI-041: 최대 10개 제한.
    REQ-AI-045: 부분 실패 시 성공한 지표 결과만 사용.

    Args:
        db: SQLAlchemy 세션
        recent_news: 최근 뉴스 목록 (news_divergence 탐지에 사용)

    Returns:
        기존 _gather_pick_candidates와 동일한 dict 구조 + leading_signals 필드
    """
    import time as _time

    if recent_news is None:
        recent_news = []

    t_start = _time.monotonic()

    # STEP 1: 전종목 스캔
    try:
        scanned_stocks = await _scan_market_stocks(db)
    except Exception as e:
        logger.warning("[선행탐지] 전종목 스캔 실패: %s", e)
        scanned_stocks = []

    if not scanned_stocks:
        logger.info("[선행탐지] 스캔된 종목 없음, 탐지 계속 진행 (news_divergence는 자체 DB 쿼리 사용)")

    # STEP 2: 시장 데이터 선 수집 (Pre-fetch) - 탐지기 병렬 실행 전 모든 종목 데이터 일괄 수집
    # 3개 탐지기가 동시에 같은 종목을 중복 요청하는 경쟁 조건 방지 (150 → 450 API 호출 문제 해결)
    market_data_cache: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(10)  # pre-fetch: pages=3이므로 동시성 10으로 향상

    async def _prefetch_one(code: str) -> None:
        async with semaphore:
            if code in market_data_cache:
                return
            try:
                # pre-fetch: BB압축(20일) + 조용한 축적(20일)에는 3페이지(30일)로 충분
                market_data_cache[code] = await _gather_market_data(code, pages=3)
            except Exception as _pfe:
                logger.debug("[선행탐지] pre-fetch 실패 %s: %s", code, _pfe)
                market_data_cache[code] = {}

    if scanned_stocks:
        await asyncio.gather(
            *[_prefetch_one(s["stock_code"]) for s in scanned_stocks],
            return_exceptions=True,
        )
        logger.info("[선행탐지] pre-fetch 완료: %d종목", len(market_data_cache))

    # STEP 3: 4개 탐지기 병렬 실행 (캐시 조회만 하므로 빠름, 60초 타임아웃)
    try:
        detection_results = await asyncio.wait_for(
            asyncio.gather(
                _detect_quiet_accumulation(scanned_stocks, market_data_cache, semaphore),
                _detect_news_price_divergence(scanned_stocks, db, recent_news),
                _detect_bb_compression(scanned_stocks, market_data_cache, semaphore),
                _detect_sector_laggards(scanned_stocks, db, market_data_cache, semaphore),
                return_exceptions=True,
            ),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[선행탐지] 탐지 타임아웃 (60초 초과)")
        detection_results = [[], [], [], []]

    # STEP 4: 실패한 탐지기는 빈 리스트로 처리 (REQ-AI-045)
    detector_names = ["quiet_accumulation", "news_divergence", "bb_compression", "sector_laggard"]
    cleaned_results = []
    for name, result in zip(detector_names, detection_results):
        if isinstance(result, Exception):
            logger.warning("[선행탐지] %s 실패: %s", name, result)
            cleaned_results.append([])
        else:
            cleaned_results.append(result)
            logger.info("[선행탐지] %s: %d개 감지", name, len(result))

    # STEP 5: 종목별 신호 병합 및 점수 계산
    stock_signals: dict[str, dict] = {}  # stock_code → {candidate, signals, score}

    for detector_results in cleaned_results:
        for candidate in detector_results:
            code = candidate.get("stock_code")
            if not code:
                continue

            if code not in stock_signals:
                stock_signals[code] = {
                    "candidate": dict(candidate),
                    "signals": list(candidate.get("leading_signals", [])),
                    "score": 0,
                }
            else:
                # 기존 후보에 신호 추가 (복수 지표)
                existing_signals = stock_signals[code]["signals"]
                for sig in candidate.get("leading_signals", []):
                    # 중복 타입 방지
                    if not any(s["type"] == sig["type"] for s in existing_signals):
                        existing_signals.append(sig)

    # STEP 6: 점수 계산
    for code, entry in stock_signals.items():
        signals = entry["signals"]
        score = 0

        for sig in signals:
            sig_type = sig.get("type", "")
            base = _LEADING_SIGNAL_WEIGHTS.get(sig_type, 0)
            score += base
            if sig.get("strength") == "strong":
                score += _LEADING_SIGNAL_STRONG_BONUS.get(sig_type, 0)

        # 복수 신호 가산 (2개 이상)
        if len(signals) > 1:
            score += _MULTI_SIGNAL_BONUS * (len(signals) - 1)

        entry["score"] = score

    # STEP 7: 점수 내림차순 정렬, 상위 10개
    sorted_entries = sorted(stock_signals.values(), key=lambda x: x["score"], reverse=True)
    top_entries = sorted_entries[:10]

    if not top_entries:
        return []

    # STEP 8: 기존 4-criteria 검증 적용 + 시세/재무 데이터 보강
    candidates = []
    for entry in top_entries:
        base_candidate = entry["candidate"]
        code = base_candidate.get("stock_code")
        if not code:
            continue

        try:
            market_data = market_data_cache.get(code)
            if not market_data:
                market_data, financial_data = await asyncio.gather(
                    _gather_market_data(code),
                    _gather_financial_data(code),
                    return_exceptions=True,
                )
            else:
                try:
                    financial_data = await _gather_financial_data(code)
                except Exception as _fe:
                    financial_data = _fe

            if isinstance(market_data, Exception):
                market_data = market_data_cache.get(code, {})
            if isinstance(financial_data, Exception):
                financial_data = {}

            # 기존 candidate dict 구조 구성
            from app.models.stock import Stock as StockModel
            from sqlalchemy.orm import joinedload

            stock_obj = (
                db.query(StockModel)
                .options(joinedload(StockModel.sector))
                .filter(StockModel.stock_code == code)
                .first()
            )

            candidate: dict = {
                "name": base_candidate.get("name", ""),
                "code": code,
                "sector": stock_obj.sector.name if stock_obj and stock_obj.sector else "미분류",
                "news_count": 0,
                "leading_signals": entry["signals"],
                "leading_score": entry["score"],
            }

            # 시세 데이터 병합
            if market_data:
                for field in (
                    "current_price", "change_rate", "volume", "price_5d_trend",
                    "price_20d_trend", "volatility", "supply_demand",
                    "foreign_net_5d", "institution_net_5d",
                    "per", "pbr", "market_cap", "foreign_ratio",
                    "high_52w", "low_52w",
                ):
                    val = market_data.get(field)
                    if val is not None:
                        candidate[field] = val

            # 재무 데이터 병합
            if financial_data:
                for field in (
                    "roe", "operating_margin", "revenue_growth",
                    "op_profit_growth", "dividend_yield", "industry_per",
                ):
                    val = financial_data.get(field)
                    if val is not None:
                        candidate[field] = val

            # None 값 제거
            candidate = {k: v for k, v in candidate.items() if v is not None}
            # leading_signals는 None이어도 유지
            if "leading_signals" not in candidate:
                candidate["leading_signals"] = entry["signals"]

            candidates.append(candidate)

        except Exception as e:
            logger.warning("[선행탐지] 후보 '%s' 데이터 보강 실패: %s", code, e)

    elapsed = _time.monotonic() - t_start
    logger.info(
        "[선행탐지] 완료: %d개 선행 후보 (%.1f초)",
        len(candidates),
        elapsed,
    )
    return candidates


async def _gather_pick_candidates(db: Session, recent_news: list) -> list[dict]:
    """뉴스에 언급된 종목들의 시세 + 밸류에이션 + 수급 + 재무 데이터를 수집.

    브리핑의 stock_picks가 실제 데이터에 기반한 전문적 매수 추천이 되도록
    후보 종목들의 종합 데이터를 AI에 제공한다.
    """
    from app.models.news_relation import NewsStockRelation

    # 최근 뉴스와 연결된 종목 ID 수집 (최대 10개)
    news_ids = [n.id for n in recent_news[:30]]
    if not news_ids:
        return []

    relations = (
        db.query(NewsStockRelation)
        .filter(
            NewsStockRelation.news_id.in_(news_ids),
            NewsStockRelation.stock_id.isnot(None),
        )
        .all()
    )

    # 종목별 뉴스 카운트로 정렬하여 상위 종목 선정
    stock_news_count: dict[int, int] = {}
    for r in relations:
        stock_news_count[r.stock_id] = stock_news_count.get(r.stock_id, 0) + 1

    top_stock_ids = sorted(stock_news_count, key=stock_news_count.get, reverse=True)[:10]
    if not top_stock_ids:
        return []

    # N+1 쿼리 방지: Stock과 Sector를 한번에 로드
    stocks = (
        db.query(Stock)
        .options(selectinload(Stock.sector))
        .filter(Stock.id.in_(top_stock_ids))
        .all()
    )
    stock_map = {s.id: s for s in stocks}

    # 시세 + 재무 데이터 병렬 수집
    candidates = []
    for sid in top_stock_ids:
        stock = stock_map.get(sid)
        if not stock:
            continue

        try:
            market_data, financial_data = await asyncio.gather(
                _gather_market_data(stock.stock_code),
                _gather_financial_data(stock.stock_code),
                return_exceptions=True,
            )

            if isinstance(market_data, Exception):
                market_data = {}
            if isinstance(financial_data, Exception):
                financial_data = {}

            # eager loading된 관계 사용 (루프 내 DB 쿼리 제거)
            sector = stock.sector

            candidate = {
                "name": stock.name,
                "code": stock.stock_code,
                "sector": sector.name if sector else "미분류",
                "news_count": stock_news_count.get(sid, 0),
            }

            # 시세 데이터
            if market_data:
                candidate["current_price"] = market_data.get("current_price")
                candidate["change_rate"] = market_data.get("change_rate")
                candidate["volume"] = market_data.get("volume")
                candidate["price_5d_trend"] = market_data.get("price_5d_trend")
                candidate["price_20d_trend"] = market_data.get("price_20d_trend")
                candidate["volatility"] = market_data.get("volatility")
                candidate["supply_demand"] = market_data.get("supply_demand")
                candidate["foreign_net_5d"] = market_data.get("foreign_net_5d")
                candidate["institution_net_5d"] = market_data.get("institution_net_5d")
                # KIS 밸류에이션
                candidate["per"] = market_data.get("per")
                candidate["pbr"] = market_data.get("pbr")
                candidate["market_cap"] = market_data.get("market_cap")
                candidate["foreign_ratio"] = market_data.get("foreign_ratio")
                candidate["high_52w"] = market_data.get("high_52w")
                candidate["low_52w"] = market_data.get("low_52w")

            # 재무 데이터
            if financial_data:
                candidate["roe"] = financial_data.get("roe")
                candidate["operating_margin"] = financial_data.get("operating_margin")
                candidate["revenue_growth"] = financial_data.get("revenue_growth")
                candidate["op_profit_growth"] = financial_data.get("op_profit_growth")
                candidate["dividend_yield"] = financial_data.get("dividend_yield")
                candidate["industry_per"] = financial_data.get("industry_per")

            # None 값 제거
            candidate = {k: v for k, v in candidate.items() if v is not None}
            candidates.append(candidate)

        except Exception as e:
            logger.warning(f"후보 종목 '{stock.name}' 데이터 수집 실패: {e}")

    return candidates


def _is_holding_company(
    db: Session,
    stock_id: int,
    cache: dict[int, bool] | None = None,
) -> bool:
    """stock_id가 지주사인지 확인한다.

    holding_company 관계에서 target_stock_id로 등록된 종목이 지주사임.
    """
    if cache is not None and stock_id in cache:
        return cache[stock_id]
    result = (
        db.query(StockRelation)
        .filter(
            StockRelation.target_stock_id == stock_id,
            StockRelation.relation_type == "holding_company",
        )
        .first()
    ) is not None
    if cache is not None:
        cache[stock_id] = result
    return result


def _get_subsidiaries(
    db: Session,
    holding_stock_ids: list[int],
) -> dict[int, list[int]]:
    """지주사 ID 목록에서 자회사 ID 목록을 반환한다.

    Returns:
        {holding_stock_id: [subsidiary_stock_id, ...]}
    """
    if not holding_stock_ids:
        return {}
    rows = (
        db.query(StockRelation.target_stock_id, StockRelation.source_stock_id)
        .filter(
            StockRelation.target_stock_id.in_(holding_stock_ids),
            StockRelation.relation_type == "holding_company",
            StockRelation.source_stock_id.isnot(None),
        )
        .all()
    )
    result: dict[int, list[int]] = {hid: [] for hid in holding_stock_ids}
    for target_id, source_id in rows:
        if target_id in result:
            result[target_id].append(source_id)
    return result


def _expand_candidates_with_subsidiaries(
    db: Session,
    candidate_data: list[dict],
    holding_company_cache: dict[int, bool] | None = None,
) -> tuple[list[dict], dict[int, list[int]]]:
    """지주사 후보 발견 시 자회사를 후보 풀에 추가한다.

    지주사가 뉴스에 언급된 경우 실제 사업 운영 주체인 자회사를
    후보 풀에 포함시켜 AI가 올바른 종목을 선택할 수 있게 한다.

    Returns:
        (expanded_candidates, {holding_stock_id: [subsidiary_stock_id, ...]})
    """
    if not candidate_data:
        return candidate_data, {}

    codes = [
        c.get("code") or c.get("stock_code")
        for c in candidate_data
        if c.get("code") or c.get("stock_code")
    ]
    if not codes:
        return candidate_data, {}

    stocks = (
        db.query(Stock)
        .options(selectinload(Stock.sector))
        .filter(Stock.stock_code.in_(codes))
        .all()
    )

    holding_ids = [
        s.id for s in stocks
        if _is_holding_company(db, s.id, holding_company_cache)
    ]
    if not holding_ids:
        return candidate_data, {}

    subsidiary_map = _get_subsidiaries(db, holding_ids)
    all_sub_ids = [sid for sids in subsidiary_map.values() for sid in sids]
    if not all_sub_ids:
        return candidate_data, {}

    sub_stocks = (
        db.query(Stock)
        .options(selectinload(Stock.sector))
        .filter(Stock.id.in_(all_sub_ids))
        .all()
    )
    sub_stock_map: dict[int, Stock] = {s.id: s for s in sub_stocks}

    existing_codes = {c.get("code") or c.get("stock_code") for c in candidate_data}
    expanded = list(candidate_data)
    for holding_id, sub_ids in subsidiary_map.items():
        for sub_id in sub_ids:
            sub = sub_stock_map.get(sub_id)
            if not sub or sub.stock_code in existing_codes:
                continue
            sector = sub.sector
            expanded.append({
                "name": sub.name,
                "code": sub.stock_code,
                "sector": sector.name if sector else "미분류",
                "news_count": 0,
                "holding_company_subsidiary": True,
            })
            existing_codes.add(sub.stock_code)
            logger.info(
                "[SPEC-AI-011] 지주사 %d의 자회사 %s(%s) 후보 풀 추가",
                holding_id, sub.name, sub.stock_code,
            )

    return expanded, subsidiary_map


def _gather_macro_alerts(db: Session) -> dict:
    """Gather active macro risk alerts + recent global macro news.

    Returns:
        dict with 'alerts' (원자재/거시 리스크 알림) and 'global_news' (해외 매크로 뉴스).
    """
    alerts = db.query(MacroAlert).filter(MacroAlert.is_active == True).all()  # noqa: E712
    alert_list = [
        {
            "level": a.level,
            "keyword": a.keyword,
            "title": a.title,
            "article_count": a.article_count,
        }
        for a in alerts
    ]

    # 최근 2일 내 해외 매크로 뉴스 (source='macro_global') 상위 5건
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    global_news = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.source == "macro_global",
            NewsArticle.collected_at >= cutoff,
        )
        .order_by(NewsArticle.collected_at.desc())
        .limit(5)
        .all()
    )
    global_news_list = [
        {
            "title": n.title,
            "published_at": n.published_at.strftime("%Y-%m-%d %H:%M") if n.published_at else None,
        }
        for n in global_news
    ]

    return {"alerts": alert_list, "global_news": global_news_list}


async def _gather_market_data(stock_code: str, *, pages: int = 10) -> dict:
    """Gather market data from KIS API and Naver Finance + technical indicators."""
    _cache_key = f"{stock_code}:{pages}"
    _cached = _MARKET_DATA_CACHE.get(_cache_key)
    if _cached:
        _ts, _data = _cached
        if datetime.now(timezone.utc).timestamp() - _ts < _MARKET_DATA_CACHE_TTL:
            return _data

    from app.services.kis_api import fetch_kis_stock_price
    from app.services.naver_finance import fetch_stock_fundamentals, fetch_stock_price_history, fetch_investor_trading
    from app.services.technical_indicators import calculate_technical_indicators, format_technical_for_prompt

    kis_data, fundamentals, price_history, investor_data = await asyncio.gather(
        fetch_kis_stock_price(stock_code),
        fetch_stock_fundamentals(stock_code),
        fetch_stock_price_history(stock_code, pages=pages),
        fetch_investor_trading(stock_code, days=20),
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

    # 기술적 지표 계산
    if price_history and not isinstance(price_history, Exception) and len(price_history) >= 5:
        price_dicts = [
            {"close": p.close, "open": p.open, "high": p.high, "low": p.low, "volume": p.volume}
            for p in price_history if p.close > 0
        ]
        current_price = result.get("current_price")
        ta = calculate_technical_indicators(price_dicts, current_price)
        result["technical_analysis"] = format_technical_for_prompt(ta, current_price)
        result["technical_score"] = ta.technical_score
        result["technical_summary"] = ta.summary

        # 기존 호환성 유지
        prices = [p.close for p in price_history[:20] if p.close > 0]
        if len(prices) >= 5:
            result["price_5d_trend"] = round((prices[0] - prices[4]) / prices[4] * 100, 2)
        if len(prices) >= 20:
            result["price_20d_trend"] = round((prices[0] - prices[19]) / prices[19] * 100, 2)
            result["avg_volume_20d"] = sum(p.volume for p in price_history[:20]) // 20
        if ta.volatility is not None:
            result["volatility"] = round(ta.volatility, 2)

        # REQ-AI-014: 멀티 타임프레임 분석용 추가 데이터
        # 5일 MA 기울기 (%)
        if ta.sma_5 is not None and len(prices) >= 6:
            sma_5_prev = sum(prices[1:6]) / 5
            result["sma_5_slope"] = round((ta.sma_5 - sma_5_prev) / sma_5_prev * 100, 4) if sma_5_prev else 0
        # 20일 MA 기울기 (%)
        all_prices = [p.close for p in price_history if p.close > 0]
        if ta.sma_20 is not None and len(all_prices) >= 21:
            sma_20_prev = sum(all_prices[1:21]) / 20
            result["sma_20_slope"] = round((ta.sma_20 - sma_20_prev) / sma_20_prev * 100, 4) if sma_20_prev else 0
        # 현재가 vs 60일 MA 비율 (%)
        if ta.sma_60 is not None and current_price:
            result["price_vs_sma60"] = round((current_price - ta.sma_60) / ta.sma_60 * 100, 2)
        # RSI 값 전달 (factor_scoring에서 사용)
        if ta.rsi_14 is not None:
            result["rsi"] = ta.rsi_14
        # MACD 크로스 전달
        if ta.macd_cross:
            macd_map = {"골든크로스": "golden_cross", "데드크로스": "dead_cross"}
            result["macd_signal"] = macd_map.get(ta.macd_cross, "")
        # SMA 배열 전달
        if ta.ma_alignment:
            align_map = {"정배열": "bullish", "역배열": "bearish"}
            result["sma_alignment"] = align_map.get(ta.ma_alignment, "")
        # 볼린저 밴드 위치 전달
        if ta.bb_position:
            bb_map = {"하단돌파": "below_lower", "상단돌파": "above_upper"}
            result["bollinger_position"] = bb_map.get(ta.bb_position, "")
        # 거래량 비율 전달
        if ta.volume_ratio is not None:
            result["volume_ratio"] = ta.volume_ratio

    # 외국인/기관 수급 데이터 (20일 → 5일/10일/20일 분석)
    if investor_data and not isinstance(investor_data, Exception) and investor_data:
        # 기간별 수급 합산
        foreign_5d = sum(t.foreign_net for t in investor_data[:5])
        foreign_10d = sum(t.foreign_net for t in investor_data[:10]) if len(investor_data) >= 10 else None
        foreign_20d = sum(t.foreign_net for t in investor_data[:20]) if len(investor_data) >= 20 else None
        institution_5d = sum(t.institution_net for t in investor_data[:5])
        institution_10d = sum(t.institution_net for t in investor_data[:10]) if len(investor_data) >= 10 else None
        institution_20d = sum(t.institution_net for t in investor_data[:20]) if len(investor_data) >= 20 else None

        result["foreign_net_5d"] = foreign_5d
        result["institution_net_5d"] = institution_5d
        if foreign_10d is not None:
            result["foreign_net_10d"] = foreign_10d
            result["institution_net_10d"] = institution_10d
        if foreign_20d is not None:
            result["foreign_net_20d"] = foreign_20d
            result["institution_net_20d"] = institution_20d

        # 수급 모멘텀: 최근 3일 vs 이전 3일 비교
        if len(investor_data) >= 6:
            recent_3d_foreign = sum(t.foreign_net for t in investor_data[:3])
            prev_3d_foreign = sum(t.foreign_net for t in investor_data[3:6])
            recent_3d_inst = sum(t.institution_net for t in investor_data[:3])
            prev_3d_inst = sum(t.institution_net for t in investor_data[3:6])

            momentum_parts = []
            if recent_3d_foreign > prev_3d_foreign and recent_3d_foreign > 0:
                momentum_parts.append("외국인 매수 가속")
            elif recent_3d_foreign < prev_3d_foreign and recent_3d_foreign > 0:
                momentum_parts.append("외국인 매수 감속")
            elif recent_3d_foreign < 0 and recent_3d_foreign < prev_3d_foreign:
                momentum_parts.append("외국인 매도 가속")

            if recent_3d_inst > prev_3d_inst and recent_3d_inst > 0:
                momentum_parts.append("기관 매수 가속")
            elif recent_3d_inst < prev_3d_inst and recent_3d_inst > 0:
                momentum_parts.append("기관 매수 감속")
            elif recent_3d_inst < 0 and recent_3d_inst < prev_3d_inst:
                momentum_parts.append("기관 매도 가속")

            result["supply_momentum"] = ", ".join(momentum_parts) if momentum_parts else "모멘텀 변화 없음"

        # 수급 연속성 (연속 매수/매도 일수)
        foreign_consecutive = 0
        foreign_direction = None
        for t in investor_data:
            if foreign_direction is None:
                foreign_direction = "buy" if t.foreign_net > 0 else "sell" if t.foreign_net < 0 else None
            if foreign_direction == "buy" and t.foreign_net > 0:
                foreign_consecutive += 1
            elif foreign_direction == "sell" and t.foreign_net < 0:
                foreign_consecutive += 1
            else:
                break
        if foreign_consecutive >= 3:
            result["foreign_streak"] = f"외국인 {foreign_consecutive}일 연속 {'순매수' if foreign_direction == 'buy' else '순매도'}"

        # 수급 방향 종합 판단
        if foreign_5d > 0 and institution_5d > 0:
            result["supply_demand"] = "외국인+기관 동반 매수 (강한 수급)"
        elif foreign_5d > 0:
            result["supply_demand"] = "외국인 매수, 기관 매도"
        elif institution_5d > 0:
            result["supply_demand"] = "기관 매수, 외국인 매도"
        elif foreign_5d < 0 and institution_5d < 0:
            result["supply_demand"] = "외국인+기관 동반 매도 (수급 악화)"
        else:
            result["supply_demand"] = "수급 중립"

        # 중장기 수급 방향 (5일 vs 20일 비교)
        if foreign_20d is not None:
            if foreign_5d > 0 and foreign_20d < 0:
                result["supply_trend"] = "외국인 단기 매수 전환 (중장기 매도 기조)"
            elif foreign_5d < 0 and foreign_20d > 0:
                result["supply_trend"] = "외국인 단기 매도 전환 (중장기 매수 기조에서 이탈)"
            elif foreign_5d > 0 and foreign_20d > 0:
                result["supply_trend"] = "외국인 지속 매수 (안정적 수급)"
            elif foreign_5d < 0 and foreign_20d < 0:
                result["supply_trend"] = "외국인 지속 매도 (수급 부담)"

    _MARKET_DATA_CACHE[_cache_key] = (datetime.now(timezone.utc).timestamp(), result)
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


def _format_briefing_hint(hint: dict | None) -> str:
    """브리핑 힌트를 AI 프롬프트용 텍스트로 변환."""
    if not hint:
        return "(독립 분석)"
    action = hint.get("action", "")
    reasoning = hint.get("reasoning", "")
    lines = [f"오늘 데일리 브리핑에서 이 종목의 판단: {action}"]
    if reasoning:
        lines.append(f"브리핑 근거: {reasoning}")
    lines.append("※ 이 판단은 같은 데이터를 기반으로 한 것이므로, 명확한 반대 근거가 없다면 일관성을 유지하세요.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] 최고 fan_in 함수. scheduler, daily_briefing, API 엔드포인트에서 모두 호출됨
# @MX:REASON: 이 함수를 수정하면 전체 AI 매수 시그널 생성 파이프라인에 영향
# @MX:SPEC: SPEC-AI-010
async def analyze_stock(
    db: Session, stock_id: int, briefing_hint: dict | None = None,
) -> FundSignal | None:
    """종목 종합 분석 → 투자 시그널 생성.

    뉴스, 공시, 시세, 재무제표를 종합하여 AI가 펀드매니저처럼 판단한다.

    Args:
        briefing_hint: 브리핑에서 전달된 힌트 (action, reasoning 등).
                       시그널과 브리핑 간 일관성을 위해 AI에게 참고 정보로 제공.
    """
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        return None

    # 오늘(KST) 이미 생성된 시그널 재사용 — 중복 API 호출/비용 방지
    # signal_type=None 인 일반 시그널만 체크 (공시 기반 시그널은 별도 흐름)
    _now_utc = datetime.now(timezone.utc)
    _kst_today_start_utc = (_now_utc + timedelta(hours=9)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(hours=9)
    _existing_today = (
        db.query(FundSignal)
        .filter(
            FundSignal.stock_id == stock_id,
            FundSignal.created_at >= _kst_today_start_utc,
            FundSignal.signal_type.is_(None),
        )
        .order_by(FundSignal.created_at.desc())
        .first()
    )
    if _existing_today:
        logger.info(
            "오늘 시그널 이미 존재: %s (id=%d, signal=%s) — 재생성 건너뜀",
            stock.name, _existing_today.id, _existing_today.signal,
        )
        return _existing_today

    sector = db.query(Sector).filter(Sector.id == stock.sector_id).first()

    # Gather all data in parallel
    news = _gather_stock_news(db, stock_id)
    sector_news = _gather_sector_news(db, stock.sector_id) if sector else []
    disclosures = _gather_disclosures(db, stock_id)
    macro_alerts = _gather_macro_alerts(db)
    sentiment_trend = _gather_sentiment_trend(db, stock_id=stock_id)
    forum_sentiment = _gather_forum_sentiment(db, stock_id)
    securities_reports = _gather_securities_reports(db, stock_id)
    # market_data는 비동기 수집 후 확정되므로 current_price=None으로 전달
    # @MX:NOTE — 증권사 컨센서스: 90일 윈도우 집계. strong_buy 시 AI 판단 긍정적으로 유도
    consensus = _gather_securities_consensus(db, stock_id, current_price=None)
    short_selling_data = _gather_short_selling_data(db, stock_id)

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
    from app.config import settings
    from app.services.signal_verifier import get_accuracy_stats, calibrate_confidence
    from app.services.factor_scoring import build_factor_scores_json
    from app.services.prompt_versioner import get_current_version, get_ab_versions
    from app.services.news_price_impact_service import get_sector_news_impact_stats
    from app.services.improvement_loop import get_active_factor_weights
    # REQ-AI-007-003: primary 모델(gemini-2.5-flash)로 필터링하여 오염 없는 적중률 전달.
    # ai_model_used는 _ask_ai_with_model() 호출 후 확정되므로, 설정된 primary 모델명을 사용.
    accuracy = get_accuracy_stats(db, days=30, ai_model=settings.GEMINI_MODEL)
    accuracy_text = "아직 검증된 시그널 없음"
    if accuracy.get("low_sample_warning"):
        accuracy_text = accuracy["low_sample_warning"]
    elif accuracy["total"] > 0:
        accuracy_text = (
            f"최근 30일 적중률: {accuracy['accuracy']}% "
            f"({accuracy['correct']}/{accuracy['total']}건), "
            f"매수 적중률: {accuracy['buy_accuracy']}%, "
            f"매도 적중률: {accuracy['sell_accuracy']}%, "
            f"평균 수익률: {accuracy['avg_return']}%"
        )

    # REQ-AI-003: 오류 패턴 분포 피드백
    error_dist = accuracy.get("error_distribution", {})
    error_text = ""
    if error_dist:
        error_parts = [f"{k} {v}건" for k, v in error_dist.items()]
        error_text = f"\n최근 오류 패턴: {', '.join(error_parts)}"
        error_text += "\n※ 위 오류 패턴을 참고하여 같은 실수를 반복하지 마세요."

    # REQ-AI-009: 섹터별 뉴스 임팩트 통계
    impact_stats = None
    impact_text = ""
    if sector:
        impact_stats = get_sector_news_impact_stats(db, stock.sector_id)
        if impact_stats.get("sample_sufficient"):
            impact_text = (
                f"\n\n## 섹터 뉴스 반응 통계 (최근 30일)\n"
                f"- 이 섹터 뉴스 발생 후 평균 5일 수익률: {impact_stats['avg_return_5d']}%\n"
                f"- 양수 수익률 비율: {impact_stats['win_rate']}%\n"
                f"- 분석 대상 기사 수: {impact_stats['total_articles']}건\n"
                f"※ 과거 통계를 참고하되, 현재 시장 상황이 다를 수 있음에 유의하세요."
            )

    # SPEC-AI-006: A/B 테스트 — stock_id 기반 대조군/실험군 분리
    # 짝수 stock_id → 대조군, 홀수 stock_id → 실험군
    _control_version, _treatment_version = get_ab_versions(db, template_key="signal")
    if _treatment_version and stock_id % 2 == 1:
        current_prompt_version = _treatment_version
    else:
        current_prompt_version = _control_version or get_current_version(db, template_key="signal")

    # SPEC-AI-006: 동적 팩터 가중치 로드 (DB 활성 가중치 우선, 없으면 기본값)
    _active_weights = get_active_factor_weights(db)

    # Pre-compute values that would break f-string syntax
    trend_label = {'improving': '개선 중', 'worsening': '악화 중', 'stable': '안정적'}.get(
        sentiment_trend.get('trend', 'stable'), '안정적'
    )

    # @MX:NOTE — 종토방 섹션: 직접 신호 아님, 역발상 참고 지표 (가중치 0.2). 단독 매수 금지
    if forum_sentiment:
        forum_section = (
            f"\n## 1-2. 종토방 감성 (역발상 지표, 가중치 0.2)\n"
            f"- 게시글 수: {forum_sentiment['total_posts']}건, 매수 비율: {forum_sentiment['bullish_ratio']*100:.0f}%\n"
            f"- 댓글 볼륨: {forum_sentiment['comment_volume']} (7일 평균: {forum_sentiment['avg_7d_volume']:.0f})"
        )
        if forum_sentiment.get('overheating_alert'):
            forum_section += "\n※ 종토방이 과열 상태입니다. 개인투자자 쏠림에 의한 고점 가능성을 고려하세요."
        if forum_sentiment.get('volume_surge'):
            forum_section += "\n※ 종토방 댓글 급증 감지: 시장 관심도 급등. 공시/뉴스와 교차 확인 필요."
        forum_section += "\n"
    else:
        forum_section = ""  # SPEC-AI-008 미배포 또는 데이터 없음

    # @MX:NOTE — 증권사 컨센서스: 90일 윈도우 집계. strong_buy 시 AI 판단 긍정적으로 유도
    if consensus and consensus.get('report_count', 0) >= 2:
        _signal_label = {
            "strong_buy": "강력매수",
            "buy": "매수",
            "neutral": "중립",
            "caution": "주의",
            "insufficient": "데이터 부족",
        }.get(consensus.get('consensus_signal', ''), '중립')
        _avg_tp = consensus.get('avg_target_price')
        _premium = consensus.get('premium_pct')
        _tp_text = (
            f"{_avg_tp:,}원 (현재가 대비 {_premium:+.1f}%)"
            if _avg_tp and _premium is not None
            else "N/A"
        )
        consensus_section = (
            f"\n## 9-1. 증권사 컨센서스\n"
            f"- 분석 리포트: {consensus['report_count']}건 (90일)\n"
            f"- 평균 목표주가: {_tp_text}\n"
            f"- 매수/중립/매도 비율: {consensus['buy_ratio']*100:.0f}%/{consensus['hold_ratio']*100:.0f}%/{consensus['sell_ratio']*100:.0f}%\n"
            f"- 컨센서스 신호: {_signal_label}\n"
            f"- 목표주가 추세: {consensus.get('target_price_trend', 'stable')}\n"
        )
        if consensus.get('consensus_signal') == 'strong_buy':
            consensus_section += "※ 증권사 다수가 강력 매수를 추천하며 현재가 대비 상당한 상승 여력이 있습니다.\n"
        elif consensus.get('consensus_signal') == 'caution':
            consensus_section += "※ 증권사 의견에 주의 신호가 있습니다. 추가 확인 후 신중하게 접근하세요.\n"
    else:
        consensus_section = ""  # 데이터 부족

    # Build comprehensive prompt
    prompt = f"""당신은 하버드 MBA 출신의 20년 경력 전문 펀드매니저입니다.
아래 데이터를 종합적으로 분석하여 투자 판단을 내려주세요.
뉴스의 본문 내용(content 필드)이 제공된 경우, 제목만이 아닌 본문의 구체적 수치/사실/발언을 근거로 분석하세요.

## 분석 대상
- 종목명: {stock.name}
- 종목코드: {stock.stock_code}
- 섹터: {sector.name if sector else '미분류'}

## 0. 과거 시그널 성과 (자기 피드백)
{accuracy_text}{error_text}
※ 적중률이 낮다면 더 보수적으로, 높다면 현재 전략을 유지하세요.

## 1. 최근 뉴스 동향 (최근 3일)
{json.dumps(news, ensure_ascii=False, indent=2) if news else '관련 뉴스 없음'}

## 1-1. 센티먼트 추이 (최근 3일 vs 이전 4일)
- 최근 3일: 긍정 {sentiment_trend['recent_3d']['positive']}건, 부정 {sentiment_trend['recent_3d']['negative']}건, 중립 {sentiment_trend['recent_3d']['neutral']}건 (점수: {sentiment_trend['score_3d']})
- 이전 4일: 긍정 {sentiment_trend['prev_4d']['positive']}건, 부정 {sentiment_trend['prev_4d']['negative']}건, 중립 {sentiment_trend['prev_4d']['neutral']}건 (점수: {sentiment_trend['score_prev']})
- 추세: {trend_label}
※ 센티먼트가 악화되고 있다면 매수에 신중하고, 개선 중이라면 긍정적으로 평가하세요.
{forum_section}
## 2. 섹터 뉴스 동향
{json.dumps(sector_news, ensure_ascii=False, indent=2) if sector_news else '섹터 뉴스 없음'}

## 3. DART 공시 (최근 7일)
{json.dumps(disclosures, ensure_ascii=False, indent=2) if disclosures else '최근 공시 없음'}

## 4. 시세 + 수급 데이터
{json.dumps({k: v for k, v in market_data.items() if k not in ('technical_analysis', 'technical_score', 'technical_summary')}, ensure_ascii=False, indent=2) if market_data else '시세 데이터 없음'}
※ 수급 데이터 해석 가이드:
  - supply_demand: 5일 기준 외국인/기관 수급 방향
  - supply_momentum: 최근 3일 vs 이전 3일 비교 (가속/감속 판단)
  - supply_trend: 단기(5일) vs 중장기(20일) 수급 방향 비교
  - foreign_streak: 외국인 연속 순매수/순매도 일수
  - 외국인+기관 동반 매수 가속 = 매우 강한 매수 시그널
  - 외국인 연속 5일 이상 순매수 = 추세적 매수 가능성
  - 단기 매수 전환이지만 중장기 매도 기조 = 반등 지속성에 의문

## 4-1. 기술적 분석 (SMA/RSI/MACD/볼린저밴드)
{market_data.get('technical_analysis', '기술적 분석 데이터 없음') if market_data else '기술적 분석 데이터 없음'}
※ 기술적 점수가 +30 이상이면 강한 매수 신호, -30 이하면 강한 매도 신호입니다.
  RSI 과매도 + MACD 골든크로스 조합은 강력한 반등 신호로 판단하세요.
  RSI 과매수 + 볼린저 상단 돌파 조합은 추세 지속 여부를 중심으로 판단하세요. 강한 상승 추세에서 과매수는 정상 상태이며, 수급·뉴스가 뒷받침된다면 추가 상승 여지가 있습니다. 조정 가능성은 confidence 값에 반영하세요.
  이동평균 정배열은 상승 추세 확인, 역배열은 하락 추세를 의미합니다.

## 5. 재무제표 데이터
{json.dumps(financial_data, ensure_ascii=False, indent=2) if financial_data else '재무 데이터 없음'}

## 6. 매크로 리스크 및 해외 거시경제 뉴스
### 6-1. 국내 매크로 리스크 알림
{json.dumps(macro_alerts.get("alerts"), ensure_ascii=False, indent=2) if macro_alerts.get("alerts") else '현재 매크로 리스크 없음'}
### 6-2. 해외 거시경제 동향 (최근 2일)
{json.dumps(macro_alerts.get("global_news"), ensure_ascii=False, indent=2) if macro_alerts.get("global_news") else '해외 거시경제 뉴스 없음'}
※ 연준 금리 인상/인하 시그널, 미국 CPI 예상치 초과, 반도체 공급망 이슈 등은 국내 증시에 직접 영향을 줍니다.

## 7. 동종업계 비교
{json.dumps(peers, ensure_ascii=False, indent=2) if peers else '동종업계 비교 데이터 없음'}
※ 동종업계 대비 밸류에이션/센티먼트/주가 흐름을 비교하여 상대적 매력도를 평가하세요.
  섹터 전체가 하락 중인데 해당 종목만 상승하면 과열 경계, 섹터 반등 시 후발주자면 기회로 판단.
{impact_text}

## 8. 공매도 잔고 추이 (최근 10일)
{json.dumps(short_selling_data, ensure_ascii=False, indent=2) if short_selling_data else '공매도 데이터 없음 (수집 전 또는 해당 없음)'}
※ 공매도 잔고 추이 해석:
  - 잔고 급증(+10% 이상): 기관/외국인이 하락에 베팅 중 → 매수 신중
  - 잔고 급감(-10% 이상): 숏커버링 발생 → 단기 반등 가능성
  - short_ratio가 5% 초과: 공매도 압력 높음, 주가 상승 저항 존재

## 9. 증권사 리포트 (최근 14일 애널리스트 분석)
{json.dumps(securities_reports, ensure_ascii=False, indent=2) if securities_reports else '최근 증권사 리포트 없음'}
※ 애널리스트 목표주가 상향은 강한 매수 근거, 하향은 경고 신호입니다.
  컨센서스 목표주가(여러 증권사 평균)와 현재가의 괴리가 클수록 상승 여력을 시사합니다.
  단, 리포트 발행일 이후 주가가 이미 목표가에 근접했다면 추가 상승 여력에 주의하세요.
{consensus_section}
## 10. 데일리 브리핑 판단 참고
{_format_briefing_hint(briefing_hint) if briefing_hint else '(독립 분석 — 브리핑 참고 정보 없음)'}

## 분석 요청 (5단계 사고 과정)
위 데이터를 아래 5단계로 사고한 뒤, JSON으로 응답하세요.

[STEP 1: 매크로/섹터 환경] 시장 변동성·섹터 뉴스·매크로 리스크가 이 종목에 유리/불리한지 판단
[STEP 2: 팩터 분석] 뉴스 센티먼트·기술적(RSI·MACD·BB)·수급(외국인·기관)·밸류에이션 4가지 강약점
[STEP 3: 리스크 평가] 공매도 잔고·종토방 과열·이평선 역배열·하락 추세 등 하방 리스크
[STEP 4: 시그널 결론] STEP 1~3 종합 → buy/sell/hold 및 confidence 결정 근거. 과매수 상태이더라도 추세와 수급이 강하면 buy 가능하며 confidence에 리스크를 반영하세요.
[STEP 5: TP/SL 설정] 기술적 지지/저항선 기반 target_price, stop_loss 산정

위 5단계 사고를 reasoning 필드에 요약하고, 반드시 아래 JSON 형식으로만 응답하세요.
다른 텍스트 없이 JSON만 출력하세요.

{{
  "signal": "buy" 또는 "sell" 또는 "hold",
  "confidence": 0.0~1.0 사이의 확신도,
  "target_price": 목표가(숫자, 반드시 설정. 현재가 대비 +5%~+20% 범위),
  "stop_loss": 손절가(숫자, 반드시 설정. 현재가 대비 -3%~-10% 범위),
  "reasoning": "3-5문장의 종합적인 투자 판단 근거. 뉴스/공시/재무/시세 데이터를 구체적으로 인용하여 분석.",
  "news_summary": "뉴스 동향이 주가에 미칠 영향 요약 (2-3문장)",
  "financial_summary": "재무 상태 및 밸류에이션 평가 (2-3문장)",
  "market_summary": "기술적 분석(SMA/RSI/MACD/볼린저) 및 수급 동향 종합 (2-3문장)"
}}

목표가/손절가 설정 예시 (반드시 구체적 정수로 기입):
- 예시1: 현재가 50,000원 → target_price: 55000, stop_loss: 47500
- 예시2: 현재가 12,300원 → target_price: 14000, stop_loss: 11500

주의사항:
- confidence가 0.55 이상이어야 buy/sell 시그널을 내세요. 확신이 부족하면 hold.
- 데이터가 부족하면 그만큼 confidence를 낮추세요.
- target_price와 stop_loss는 반드시 0이 아닌 구체적 정수로 기입. null/0 금지.
- 투자 판단 근거는 구체적인 데이터를 인용하여 전문적으로 작성하세요.
- 브리핑 판단 참고가 있다면, 동일한 데이터로 동일 시점에 분석한 결과이므로 특별한 반대 근거가 없는 한 브리핑의 방향성(매수/관망/회피)과 일관되게 판단하세요.
  예: 브리핑에서 "관망"이면 시그널도 "hold"가 기본. "회피"면 "sell" 또는 "hold". "적극매수"/"매수"면 "buy".
"""

    # 시그널 분석은 투자 의사결정 핵심이므로 유료 모델(Pro) 허용.
    # 무료 모델은 instruction-following이 약해 hold 치우침/낮은 confidence 경향.
    response, ai_model_used = await _ask_ai_with_model(prompt, free_only=False)
    parsed = _parse_json_response(response)
    if not parsed:
        return None

    # 시그널 발행 시점 주가 기록 (적중률 추적용)
    price_at_signal = market_data.get("current_price") if market_data else None

    confidence_val = min(max(float(parsed.get("confidence", 0.5)), 0.0), 1.0)

    # 코드 레벨 가드: AI가 프롬프트 지시(confidence >= MIN_ACTION_CONFIDENCE)를 무시하고
    # 낮은 confidence로 buy/sell을 출력하는 경우 강제로 hold 변환.
    # gpt-4o-mini 등 fallback 모델의 instruction-following 불완전성 대응.
    # REQ-AI-007-001: 모듈 레벨 MIN_ACTION_CONFIDENCE(0.55) 참조 — 로컬 상수 제거
    if parsed.get("signal") in ("buy", "sell") and confidence_val < MIN_ACTION_CONFIDENCE:
        logger.info(
            "낮은 confidence로 buy/sell 강제 hold 변환: %s (conf=%.2f < %.2f, signal=%s)",
            stock.name,
            confidence_val, MIN_ACTION_CONFIDENCE, parsed["signal"],
        )
        parsed["signal"] = "hold"

    # AI가 제공한 목표가/손절가 추출 (0 또는 None은 무효 처리)
    ai_target = parsed.get("target_price")
    ai_stop = parsed.get("stop_loss")
    ai_target = int(ai_target) if ai_target and int(ai_target) > 0 else None
    ai_stop = int(ai_stop) if ai_stop and int(ai_stop) > 0 else None

    # 현재가 대비 유효 범위 검증: 비정상 값 무효화 후 동적 계산으로 폴백
    if price_at_signal and ai_target:
        _target_pct = (ai_target - price_at_signal) / price_at_signal
        if not (0.01 <= _target_pct <= 0.30):
            logger.warning(
                "AI target_price 범위 오류 무효화: %s target=%d (%.1f%%), price=%d",
                stock.name, ai_target, _target_pct * 100, price_at_signal,
            )
            ai_target = None
    if price_at_signal and ai_stop:
        _stop_pct = (price_at_signal - ai_stop) / price_at_signal
        if not (0.01 <= _stop_pct <= 0.20):
            logger.warning(
                "AI stop_loss 범위 오류 무효화: %s stop=%d (%.1f%% downside), price=%d",
                stock.name, ai_stop, _stop_pct * 100, price_at_signal,
            )
            ai_stop = None

    # TP/SL 방식 결정: AI 제공 > 동적 계산
    tp_sl_method = "legacy_fixed"
    final_target = ai_target
    final_stop = ai_stop

    if ai_target and ai_stop:
        # AI가 유효한 값을 제공한 경우
        tp_sl_method = "ai_provided"
    elif price_at_signal:
        # AI 미제공 시 동적 계산으로 폴백
        try:
            from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl
            dynamic_result = await calculate_dynamic_tp_sl(
                stock_code=stock.stock_code,
                entry_price=price_at_signal,
                confidence=confidence_val,
                sector_id=stock.sector_id,
                db=db,
            )
            final_target = dynamic_result["target_price"]
            final_stop = dynamic_result["stop_loss"]
            tp_sl_method = dynamic_result["method"]
        except Exception as _e:
            # 동적 계산 실패 시 기존 고정 비율 사용
            import logging as _log
            _log.getLogger(__name__).warning("동적 TP/SL 계산 실패, 고정 비율 사용: %s", _e)
            final_target = int(price_at_signal * 1.10)
            final_stop = int(price_at_signal * 0.95)
            tp_sl_method = "legacy_fixed"

    # 종토방 과열 코드 레벨 가드: 커뮤니티 쏠림 고점 매수 방지 (-0.10)
    # 프롬프트 힌트만으로는 AI가 무시할 수 있으므로 코드에서 직접 보정
    if parsed.get("signal") == "buy" and forum_sentiment and forum_sentiment.get("overheating_alert"):
        confidence_val = max(0.0, confidence_val - 0.10)
        logger.info(
            "종토방 과열 가드 적용: %s confidence -0.10 → %.2f", stock.name, confidence_val,
        )

    signal = FundSignal(
        stock_id=stock_id,
        signal=parsed.get("signal", "hold"),
        confidence=confidence_val,
        target_price=final_target,
        stop_loss=final_stop,
        reasoning=parsed.get("reasoning", "분석 실패"),
        news_summary=parsed.get("news_summary"),
        financial_summary=parsed.get("financial_summary"),
        market_summary=parsed.get("market_summary"),
        price_at_signal=price_at_signal,
        ai_model=ai_model_used,
    )
    # SPEC-AI-005: TP/SL 방식 기록 (컬럼 없는 환경 대비 안전 처리)
    try:
        signal.tp_sl_method = tp_sl_method
    except Exception:
        pass

    # REQ-AI-004: Bayesian confidence 보정 (컬럼 없어도 안전)
    if accuracy["total"] >= 10:
        signal.confidence = calibrate_confidence(signal.confidence, accuracy)

    db.add(signal)
    db.commit()
    db.refresh(signal)

    # Phase B 필드 할당 (마이그레이션 미적용 시에도 안전하게 처리)
    try:
        # REQ-AI-006: 다중 팩터 스코어링 (SPEC-AI-006: 동적 가중치 적용)
        factor_json, comp_score = build_factor_scores_json(
            news_data=news,
            market_data=market_data or {},
            financials=financial_data or {},
            impact_stats=impact_stats,
            weights=_active_weights,
            stock_id=stock.id,
            db=db,
        )
        signal.factor_scores = factor_json
        signal.composite_score = comp_score
        # REQ-AI-008: 프롬프트 버전 기록
        signal.prompt_version = current_prompt_version

        # REQ-AI-014: 멀티 타임프레임 추세 정렬 저장
        from app.services.factor_scoring import analyze_multi_timeframe
        mtf = analyze_multi_timeframe(market_data or {})
        signal.trend_alignment = mtf["trend_alignment"]
        # REQ-AI-014: divergent 추세 시 confidence 감산
        if mtf["confidence_adjustment"] != 0:
            signal.confidence = max(0.0, min(1.0, signal.confidence + mtf["confidence_adjustment"]))

        # REQ-AI-020: 시장 변동성 레벨 저장
        try:
            from app.services.market_context import get_market_volatility
            vol_info = await get_market_volatility()
            signal.volatility_level = vol_info["volatility_level"]
            # 극단적 변동성 시 confidence 추가 감산
            if vol_info["confidence_adjustment"] != 0:
                signal.confidence = max(0.0, min(1.0, signal.confidence + vol_info["confidence_adjustment"]))
        except Exception as vol_e:
            logger.warning("시장 변동성 레벨 계산 실패 (시그널 생성 계속): %s", vol_e)

        # confidence floor 제거: 변동성/MTF 리스크 보정(-0.10/-0.15)이 실제로
        # 거래를 막을 수 있도록 0.0까지 내려가도록 허용.
        # 이전 floor(MIN_ACTION_CONFIDENCE - 0.05 = 0.50)는 paper_trading 실행 임계값과
        # 동일하여 리스크 보정이 사실상 무효화되었음.
        signal.confidence = max(0.0, signal.confidence)

        # C안: 기술적 타이밍 승수 적용 (뉴스=트리거, 기술적 지표=진입 품질 보강)
        # - 과매도 진입: KS200과 방향 일치 → confidence 증폭 (최대 30%)
        # - 과매수 진입: 이미 오른 종목 → confidence 억제 (최대 25%, 상승장 과차단 방지)
        try:
            tech_mult = await _get_technical_multiplier(stock.stock_code)
            if tech_mult != 1.0:
                pre_tech = signal.confidence
                signal.confidence = max(0.0, min(1.0, signal.confidence * tech_mult))
                logger.info(
                    "기술적 승수 적용: %s (mult=%.2f, conf %.2f→%.2f)",
                    stock.name, tech_mult, pre_tech, signal.confidence,
                )
        except Exception as tech_e:
            logger.warning("기술적 승수 계산 실패 (시그널 생성 계속): %s", tech_e)

        # 최종 confidence 미달 시 hold 변환 (Bayesian/MTF/변동성 보정 후 재체크)
        # 모든 감산 적용 후 실행 임계값 미달이면 DB에 "buy"로 저장하되 미체결되는
        # 좀비 시그널을 방지하고 정확한 시그널 통계를 유지한다.
        _exec_threshold = MIN_ACTION_CONFIDENCE - 0.05  # 0.50
        if signal.signal in ("buy", "sell") and signal.confidence < _exec_threshold:
            logger.info(
                "최종 confidence 미달 hold 변환: %s (conf=%.2f < %.2f, original_signal=%s)",
                stock.name, signal.confidence, _exec_threshold, signal.signal,
            )
            signal.signal = "hold"

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Phase B 필드 저장 실패 (마이그레이션 미적용 가능): %s", e)
    logger.info(f"Fund signal created: {stock.name} → {signal.signal} (confidence: {signal.confidence})")

    # WebSocket 브로드캐스트: 새 펀드 시그널 전파
    try:
        from app.event_bus import broadcast_event
        await broadcast_event("signals", {
            "type": "fund_signal",
            "id": signal.id,
            "stock_id": signal.stock_id,
            "signal": signal.signal,
            "confidence": signal.confidence,
            "created_at": str(signal.created_at),
        })
    except Exception:
        logger.debug("시그널 WebSocket 브로드캐스트 실패", exc_info=True)

    # REQ-AI-013: 페이퍼 트레이딩 체결은 09:05 KST 배치 작업(_run_fund_morning_execute)이 담당.
    # 신호 생성(08:30)과 체결(09:05)을 분리하여 실제 장 시작 시가 기준으로 체결.
    # paper_executed=False로 저장 → 09:05 스케줄러가 현재가 조회 후 체결 처리.

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

    # SPEC-AI-003 + SPEC-AI-004: 선행 매수 신호 후보 + 공시 기반 후보 병렬 수집
    leading_data: list[dict] = []
    try:
        leading_candidates, disclosure_candidates = await asyncio.gather(
            _gather_leading_candidates(db, recent_news),
            _gather_disclosure_candidates(db),
            return_exceptions=True,
        )
        if isinstance(leading_candidates, Exception):
            logger.warning("선행 매수 신호 탐지 실패: %s", leading_candidates)
            leading_candidates = []
        if isinstance(disclosure_candidates, Exception):
            logger.warning("공시 후보 탐지 실패: %s", disclosure_candidates)
            disclosure_candidates = []

        # 공시 후보를 선행 후보 앞에 배치 (미반영 갭 우선순위)
        seen_merge: set[str] = set()
        for c in disclosure_candidates:
            code = c.get("code") or c.get("stock_code")
            if code and code not in seen_merge:
                seen_merge.add(code)
                leading_data.append(c)
        for c in leading_candidates:
            code = c.get("code") or c.get("stock_code")
            if code and code not in seen_merge:
                seen_merge.add(code)
                leading_data.append(c)
    except Exception as _le:
        logger.warning("선행 매수 신호 탐지 실패 (브리핑 계속 진행): %s", _le)

    # 뉴스에 언급된 종목들의 실시간 시세 + 밸류에이션 데이터 수집
    news_candidate_data = await _gather_pick_candidates(db, recent_news)

    # REQ-AI-042: 선행 후보 우선 + 뉴스 후보 병합 (최대 10개, 중복 제거)
    seen_codes: set[str] = set()
    candidate_data: list[dict] = []

    for c in leading_data:
        code = c.get("code") or c.get("stock_code")
        if code and code not in seen_codes:
            seen_codes.add(code)
            candidate_data.append(c)

    for c in news_candidate_data:
        code = c.get("code") or c.get("stock_code")
        if code and code not in seen_codes:
            seen_codes.add(code)
            candidate_data.append(c)

    # SPEC-AI-011: 지주사 후보 발견 시 자회사를 후보 풀에 추가 ([:10] cap 이전에 수행)
    _holding_cache: dict[int, bool] = {}
    candidate_data, _subsidiary_map = _expand_candidates_with_subsidiaries(
        db, candidate_data, _holding_cache
    )

    candidate_data = candidate_data[:10]

    leading_count = len(leading_data)
    news_count = len(news_candidate_data)
    total_count = len(candidate_data)
    logger.info(
        "[선행탐지] 최종 병합: 선행 %d개 + 뉴스 %d개 = %d개",
        leading_count, news_count, total_count,
    )

    candidate_text = json.dumps(candidate_data, ensure_ascii=False, indent=2) if candidate_data else '후보 종목 데이터 없음'

    # SPEC-AI-011: 지주사-자회사 컨텍스트 주입
    holding_context_text = ""
    if _subsidiary_map:
        all_holding_ids = list(_subsidiary_map.keys())
        all_sub_ids_flat = [sid for sids in _subsidiary_map.values() for sid in sids]
        _h_stocks = db.query(Stock).filter(Stock.id.in_(all_holding_ids)).all()
        _s_stocks = db.query(Stock).filter(Stock.id.in_(all_sub_ids_flat)).all()
        _hid_name = {s.id: s.name for s in _h_stocks}
        _sid_name = {s.id: s.name for s in _s_stocks}
        lines = ["## 지배구조 주의사항"]
        for hid, sub_ids in _subsidiary_map.items():
            hname = _hid_name.get(hid, f"지주사#{hid}")
            sub_names = [_sid_name.get(s, f"자회사#{s}") for s in sub_ids]
            lines.append(
                f"- {hname}은(는) 지주회사입니다. "
                f"사업 운영 뉴스의 실제 수혜 종목은 운영 자회사({', '.join(sub_names)})입니다. "
                "지주사 대신 운영 실체를 우선 검토하세요."
            )
        lines.append("")
        holding_context_text = "\n".join(lines) + "\n"

    # REQ-AI-020: 시장 변동성 레벨 (브리핑 상단 표시)
    volatility_text = ""
    try:
        from app.services.market_context import get_market_volatility, format_volatility_for_briefing
        vol_info = await get_market_volatility()
        volatility_text = "\n## 시장 변동성 현황\n" + format_volatility_for_briefing(vol_info) + "\n"
    except Exception as vol_e:
        logger.warning("브리핑용 시장 변동성 데이터 수집 실패 (브리핑 계속 진행): %s", vol_e)

    # REQ-AI-016/017: 섹터 모멘텀 분석 + 로테이션 감지
    sector_momentum_text = ""
    try:
        from app.services.sector_momentum import (
            detect_momentum_sectors,
            detect_capital_inflow,
            detect_sector_rotation,
            format_sector_momentum_for_briefing,
        )
        momentum_sectors = detect_momentum_sectors(db)
        inflow_sectors = detect_capital_inflow(db)
        rotation_events = detect_sector_rotation(db)
        sector_momentum_text = "\n" + format_sector_momentum_for_briefing(
            momentum_sectors, inflow_sectors, rotation_events, db
        ) + "\n"
    except Exception as sm_e:
        logger.warning("섹터 모멘텀 분석 실패 (브리핑 계속 진행): %s", sm_e)

    # REQ-AI-018: 어닝 프리뷰 (실적 공시 예정 D-5)
    earnings_text = ""
    try:
        from app.services.earnings_analyzer import (
            get_upcoming_earnings,
            analyze_earnings_preview,
            format_earnings_for_briefing,
        )
        upcoming = get_upcoming_earnings(db)
        if upcoming:
            previews = []
            for item in upcoming[:5]:  # 최대 5개 종목
                preview = analyze_earnings_preview(db, item["stock_id"])
                previews.append(preview)
            earnings_text = "\n" + format_earnings_for_briefing(previews) + "\n"
    except Exception as earn_e:
        logger.warning("어닝 프리뷰 분석 실패 (브리핑 계속 진행): %s", earn_e)

    # REQ-AI-024: 원자재 크로스 검증 컨텍스트
    commodity_context_text = ""
    try:
        from app.services.market_context import format_commodity_context_for_briefing
        all_sector_ids = [s["id"] for s in sector_info]
        commodity_context_text = "\n" + format_commodity_context_for_briefing(db, all_sector_ids) + "\n"
    except Exception as comm_e:
        logger.warning("원자재 컨텍스트 수집 실패 (브리핑 계속 진행): %s", comm_e)

    # REQ-AI-022: 과거 유사 시장 패턴 매칭
    historical_pattern_text = ""
    try:
        from app.services.market_context import format_historical_patterns_for_briefing
        # vol_info에서 변동성 레벨, sector_momentum에서 모멘텀 섹터 추출
        _vol_level = vol_info.get("volatility_level") if vol_info else None
        # KOSPI 5일 수익률: sector_momentum의 전체 평균으로 추정
        _kospi_ret_5d = None
        _momentum_ids: list[int] = []
        try:
            from app.models.sector_momentum import SectorMomentum
            from sqlalchemy import func as _sa_func
            from datetime import date as _date_type
            _today = _date_type.today()
            _avg_row = (
                db.query(_sa_func.avg(SectorMomentum.avg_return_5d))
                .filter(SectorMomentum.date == _today)
                .scalar()
            )
            _kospi_ret_5d = float(_avg_row) if _avg_row is not None else None
            _momentum_rows = (
                db.query(SectorMomentum.sector_id)
                .filter(
                    SectorMomentum.date == _today,
                    SectorMomentum.momentum_tag == "momentum_sector",
                )
                .all()
            )
            _momentum_ids = [r[0] for r in _momentum_rows]
        except Exception:
            pass  # 모멘텀 데이터 없어도 패턴 매칭 시도 가능

        _pattern_text = format_historical_patterns_for_briefing(
            db, _kospi_ret_5d, _vol_level, _momentum_ids
        )
        if _pattern_text:
            historical_pattern_text = "\n" + _pattern_text + "\n"
    except Exception as hist_e:
        logger.warning("과거 패턴 매칭 실패 (브리핑 계속 진행): %s", hist_e)

    # REQ-NPI-014~015: 후보 종목별 뉴스-가격 반응 통계 주입
    news_impact_text = ""
    try:
        from app.services.news_price_impact_service import get_stock_impact_stats
        from app.models.stock import Stock as StockModel

        impact_lines = []
        # candidate_data에서 종목명 추출하여 stock_id 조회
        if candidate_data:
            candidate_names = [c.get("name") or c.get("stock") for c in candidate_data if isinstance(c, dict)]
            candidate_stocks = db.query(StockModel).filter(StockModel.name.in_(candidate_names)).all() if candidate_names else []
            for stock in candidate_stocks:
                stats = await get_stock_impact_stats(db, stock.id, days=30)
                if stats.get("status") == "sufficient" and stats.get("count", 0) > 0:
                    impact_lines.append(
                        f"- {stock.name}: 평균 1일 수익률 {stats['avg_1d']}%, "
                        f"평균 5일 수익률 {stats['avg_5d']}%, "
                        f"승률(5일) {stats['win_rate_5d']}% "
                        f"(샘플 {stats['count']}건)"
                    )
        if impact_lines:
            news_impact_text = "\n## 뉴스 반응 통계 (30일)\n" + "\n".join(impact_lines) + "\n"
    except Exception as e:
        logger.warning(f"뉴스 반응 통계 수집 실패 (브리핑 계속 진행): {e}")

    # REQ-021: 방어 모드 상태 확인 및 브리핑 경고 문구
    defensive_mode_text = ""
    try:
        from app.services.paper_trading import check_defensive_mode, get_or_create_portfolio
        is_defensive = check_defensive_mode(db)
        if is_defensive:
            portfolio = get_or_create_portfolio(db)
            entered_at = portfolio.defensive_mode_entered_at
            entered_str = entered_at.strftime('%Y-%m-%d %H:%M') if entered_at else "알 수 없음"
            defensive_mode_text = (
                f"\n## [경고] 방어 모드 활성화 중\n"
                f"- 포트폴리오 누적 수익률이 -10% 이하로 하락하여 방어 모드가 활성화되었습니다.\n"
                f"- 방어 모드 진입 시각: {entered_str}\n"
                f"- 신규 매수 시그널이 차단됩니다.\n"
                f"- 기존 포지션의 손절 기준이 -5%에서 -3%로 강화됩니다.\n"
                f"- 누적 수익률이 -5% 이상으로 회복되면 자동 해제됩니다.\n"
            )
    except Exception as e:
        logger.warning(f"방어 모드 상태 확인 실패 (브리핑 계속 진행): {e}")

    prompt = f"""당신은 국내 최고 자산운용사의 CIO(최고투자책임자)이자 20년 경력 전문 펀드매니저입니다.
오늘 날짜: {today.strftime('%Y년 %m월 %d일')}

**절대 규칙:**
- 반드시 한국어로만 응답하세요. 영어 사용 금지.
- 한자(漢字) 절대 사용 금지. 모든 텍스트는 순수 한글로 작성하세요. (예: 愼重 → 신중, 下落 → 하락)
- 추상적/일반적 표현 금지. 반드시 구체적 수치와 데이터를 인용하세요.

아래에 뉴스, 공시, 센티먼트 추이, 매크로 리스크, 그리고 **후보 종목들의 실시간 시세/밸류에이션/수급/재무 데이터**가 제공됩니다.
이 모든 데이터를 종합적으로 분석하여 전문 펀드매니저 수준의 데일리 브리핑을 작성하세요.

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
{json.dumps(macro_alerts.get("alerts"), ensure_ascii=False, indent=2) if macro_alerts.get("alerts") else '현재 특이 리스크 없음'}

## 최근 주요 공시
{json.dumps(disc_list, ensure_ascii=False, indent=2) if disc_list else '주요 공시 없음'}

## 추적 중인 섹터
{', '.join(s['name'] for s in sector_info)}

## 매수 후보 종목 실시간 데이터 (시세 + 밸류에이션 + 수급 + 재무)
아래 데이터의 각 필드 의미:
- current_price: 현재가, **change_rate: 당일 등락률(%) ← 이 값이 음수이면 하락 중! -3% 이하는 매수 금지!**, volume: 거래량
- per: 주가수익비율, pbr: 주가순자산비율, industry_per: 업종 평균 PER
- roe: 자기자본이익률(%), operating_margin: 영업이익률(%)
- revenue_growth: 매출성장률(%), op_profit_growth: 영업이익성장률(%)
- price_5d_trend: 5일 주가추세(%), price_20d_trend: 20일 주가추세(%)
- foreign_net_5d: 외국인 5일 순매수(주), institution_net_5d: 기관 5일 순매수(주)
- supply_demand: 수급 판단 요약
- high_52w/low_52w: 52주 최고/최저가
- dividend_yield: 배당수익률(%)
- **leading_signals: 선행 매수 신호 목록** (REQ-AI-044)
  - type: "quiet_accumulation"(조용한수급축적) | "news_divergence"(뉴스가격괴리) | "bb_compression"(볼린저밴드수축) | "sector_laggard"(섹터낙오자)
  - strength: "strong"(강함) | "moderate"(보통)
  - detail: 신호 상세 설명
  - **leading_signals가 있는 종목은 아직 가격이 움직이지 않은 선행 신호 기반 후보입니다. 진입 근거를 선행 지표 중심으로 분석하세요.**

{candidate_text}
{holding_context_text}{volatility_text}{sector_momentum_text}{earnings_text}{commodity_context_text}{historical_pattern_text}{news_impact_text}{defensive_mode_text}
## Chain-of-Thought 분석 (5단계)
아래 5단계를 **반드시 순서대로** 수행하고, 각 단계의 분석 결과를 JSON의 "cot_reasoning" 필드에 포함하세요.

[STEP 1: 시장 환경 진단]
현재 시장 변동성, 섹터 로테이션, 매크로 리스크를 종합하여 시장 환경을 진단하시오.

[STEP 2: 종목별 팩터 분석]
각 후보 종목에 대해 4개 팩터(뉴스, 기술적, 수급, 밸류에이션) 점수를 기반으로 강약점을 분석하시오.

[STEP 3: 추세 정렬 검증]
다중 시간축(5일/20일/60일) 추세 방향이 일치하는지 확인하시오.

[STEP 4: 리스크 평가]
과거 유사 시장 상황의 적중률, 섹터 중복 리스크, 어닝 이벤트 유무를 평가하시오.

[STEP 5: 최종 추천 및 근거]
매수 추천 종목과 구체적 근거를 제시하시오. 각 추천에 대해 "가장 큰 리스크"도 명시하시오.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.
{{
  "market_overview": "오늘 시장의 핵심 이슈를 7-10문장으로 상세 분석. (1) 글로벌 매크로 환경(금리, 환율, 유가, 지정학 리스크), (2) 국내 시장 흐름(코스피/코스닥 동향, 거래대금, 외국인/기관 동향), (3) 핵심 뉴스 2-3개를 구체적으로 인용하며 시장 영향 분석, (4) 당일 시장 전망. 일반 텍스트로 작성.",

  "sector_highlights": [
    {{"sector": "섹터명", "sentiment": "positive 또는 negative 또는 neutral", "analysis": "3-4문장으로 해당 섹터 분석. (1) 섹터에 영향을 미치는 뉴스/이벤트 구체 인용, (2) 대표 종목의 주가 흐름, (3) 업황 전망. 구체적 수치 필수."}}
  ],

  "stock_picks": [
    {{
      "stock": "종목명 (반드시 위 후보 종목 데이터에 있는 종목명과 동일하게)",
      "action": "적극매수 또는 매수 또는 관망 또는 회피",
      "reason": "5-7문장으로 상세 분석. 반드시 다음 4가지를 모두 포함: [밸류에이션] PER {{}}, 업종평균 PER {{}}, PBR {{}}, ROE {{}}%로 업종 대비 저평가/고평가 판단. [주가흐름/수급] 5일 {{}}%, 20일 {{}}% 변동, 외국인 {{}}주/기관 {{}}주 순매수로 수급 양호/불량. [카탈리스트] 해당 종목과 관련된 뉴스/공시의 구체적 내용과 주가 영향 분석. [리스크] 매크로 리스크, 업황 리스크, 밸류에이션 리스크 등 구체적 위험 요소.",
      "target_price": 현재가 대비 +5%~+20% 범위의 목표가 정수 (0 또는 null 금지),
      "stop_loss": 현재가 대비 -3%~-10% 범위의 손절가 정수 (0 또는 null 금지)
    }}
  ],

  "risk_assessment": "5-7문장. (1) 현재 가장 큰 매크로 리스크와 그 영향을 구체적 수치로 분석, (2) 포트폴리오 방어 전략, (3) 주의해야 할 섹터/종목. 뉴스 제목을 직접 인용하며 분석.",

  "strategy": "5-7문장. (1) 오늘 시장에서 취해야 할 구체적 액션(비중 조절, 섹터 로테이션 등), (2) 단기(1주) 전략, (3) 중기(1개월) 관점. 추상적 조언이 아닌 실행 가능한 구체적 전략 제시.",

  "cot_reasoning": "위 5단계 Chain-of-Thought 분석 내용을 여기에 작성. 반드시 [STEP 1], [STEP 2], [STEP 3], [STEP 4], [STEP 5] 헤더를 모두 포함하여 단계별 분석 결과를 기술."
}}

**핵심 규칙 (절대 위반 금지):**

## 매수 추천 기준 (가장 중요)
- "매수" 또는 "적극매수"는 **상승 추세가 확인된 종목만** 가능합니다.
- 단순히 "많이 떨어져서 싸다"는 매수 근거가 아닙니다. 이것은 "떨어지는 칼날 잡기"입니다.
- **매수 추천 필수 조건 (모두 충족해야 함):**
  (1) change_rate(당일 등락률)이 -3% 이상일 것 (단, -1% 이하는 "조건부 매수 후보"로 분류)
  (2) price_5d_trend(5일 추세)가 양수이거나 하락 후 반등 신호가 있을 것
  (3) 외국인 또는 기관 순매수가 양수일 것 (foreign_net_5d 또는 institution_net_5d > 0)
  (4) 밸류에이션 매력이 있을 것 (PER이 업종 평균 이하 또는 PBR 1배 미만)
- 위 4가지 중 3가지 이상 충족하면 매수 후보로 포함하세요. 4가지 모두 충족하면 "적극매수" 후보, 3가지 충족하면 "조건부 매수" 후보로 분류하세요. 2가지 이하 충족 시 "관망"으로 설정하세요.

## 절대 금지 사항
1. **당일 -5% 이상 하락 종목 → 무조건 "관망" 또는 "회피"**. -3%~-5% 구간은 반등 가능성을 수급과 기술적 지표로 판단. 급락 중 매수 추천은 투자자에게 큰 손실을 줍니다.
2. **하락 추세 종목(5일, 20일 모두 마이너스) + 수급 악화(외국인/기관 매도) → "회피"**
3. 뉴스에 언급됐다는 이유만으로 추천 금지. 밸류에이션 + 수급 + 추세를 종합 판단.
4. PER이 업종 평균 대비 50% 이상 높거나 ROE 5% 미만 → 일반적으로 "관망" 또는 "회피". 단, leading_signals가 있는 선행 신호 종목(아직 가격 미반영)은 ROE 기준을 완화하여 성장성·기술적 신호를 우선 반영하세요.
5. 하락장에서 함부로 매수 추천 금지. 시장 전체가 약세이면 대부분 "관망"이 맞습니다. 단, 선행 신호 종목은 하락장에서도 "조건부 매수"가 가능합니다.

## 조건부 매수 후보 처리
- 4가지 조건 중 3가지만 충족하는 종목은 "조건부 매수"로 표시하세요.
- 미충족 조건을 명시하세요 (예: "[수급 미충족] 외국인/기관 순매도 중이나, 밸류에이션/추세/등락률 조건 충족")
- 조건부 매수의 confidence는 0.5~0.65 범위로 설정하세요.
- 4가지 모두 충족 시 confidence 0.7 이상 가능.

## 기타 규칙
6. stock_picks는 반드시 후보 종목 데이터의 수치를 직접 인용하여 분석. 데이터 없이 추측 금지.
7. target_price와 stop_loss는 반드시 0이 아닌 구체적 정수로 기입. null/0 금지.
   예시1: 현재가 50,000원 → target_price: 55000, stop_loss: 47500
   예시2: 현재가 12,300원 → target_price: 14000, stop_loss: 11500
8. stock_picks는 후보 종목 데이터가 제공된 경우 3-5개 종목 포함. 후보 종목 데이터가 없으면 빈 배열 [] 허용. 데이터 없는 종목명 추측/창작 절대 금지. 데이터 있을 경우 "적극매수"는 최대 1개. 매수 매력 없으면 전부 "관망"/"회피"로.
9. sector_highlights는 3-5개 섹터 배열.
10. 한자(漢字) 절대 사용 금지. 순수 한글만 사용하세요.
"""

    response, ai_model_used = await _ask_ai_with_model(prompt, free_only=True)
    if not response:
        # 설정된 키 확인
        from app.config import settings as _s
        configured = []
        for idx, key in enumerate([_s.GEMINI_API_KEY, _s.GEMINI_API_KEY_2, _s.GEMINI_API_KEY_3], 1):
            if key:
                configured.append(f"Gemini-{idx}(key={key[:8]}...)")
        raise RuntimeError(
            f"모든 Gemini API 키가 실패했습니다. 설정된 키: {configured or '없음'}. "
            "서버 로그에서 상세 에러를 확인하세요."
        )
    parsed = _parse_json_response(response)
    if not parsed:
        # AI가 Markdown 형식으로 응답한 경우 JSON 변환 재시도 (1회)
        logger.warning("[브리핑] AI가 JSON 대신 Markdown으로 응답. JSON 변환 재시도...")
        retry_prompt = (
            "다음은 당신이 방금 작성한 브리핑입니다:\n\n"
            f"{response}\n\n"
            "위 내용을 아래 JSON 스키마로 변환해주세요. "
            "JSON 외 다른 텍스트 없이 JSON 객체만 출력하세요.\n"
            + prompt.split("반드시 아래 JSON 형식으로만 응답하세요.")[1]
            if "반드시 아래 JSON 형식으로만 응답하세요." in prompt
            else prompt
        )
        retry_response, _ = await _ask_ai_with_model(retry_prompt, free_only=True)
        if retry_response:
            parsed = _parse_json_response(retry_response)
        if not parsed:
            raise RuntimeError(f"AI 응답 JSON 파싱 실패. 원본 응답(앞 500자): {response[:500]}")

    # REQ-023: CoT 5단계 완성도 검증
    # cot_reasoning 필드 또는 원본 응답에서 STEP 1~5 존재 여부 확인
    cot_text = parsed.get("cot_reasoning", "") or ""
    # cot_reasoning 필드에 없으면 원본 응답 전체에서 검색
    cot_check_target = cot_text if cot_text.strip() else response
    cot_result = validate_cot_steps(cot_check_target)
    parsed = apply_cot_penalty(parsed, cot_result)

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
        ai_model=ai_model_used,
    )

    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    # REQ-023: CoT 프롬프트 버전 및 검증 결과 로깅
    logger.info(
        "Daily briefing generated for %s (prompt=cot_v1, cot_complete=%s)",
        today, cot_result["complete"],
    )

    # 브리핑 추천 종목 → 투자 시그널 생성
    # NOTE: asyncio.run() 컨텍스트(스케줄러)에서 create_task()는 이벤트 루프가 닫히면 실행되지 않음
    # 따라서 await으로 직접 호출하여 시그널이 실제로 생성되도록 수정
    stock_picks_data = parsed.get("stock_picks")
    # REQ-023: CoT 불완전 분석 정보를 시그널 생성에 전달
    cot_validation = parsed.get("_cot_validation")
    if stock_picks_data:
        await _generate_signals_from_picks(db, stock_picks_data, cot_validation)

    return briefing


async def _generate_signals_background(
    stock_picks_data, cot_validation: dict | None = None,
) -> None:
    """백그라운드에서 브리핑 추천 종목의 투자 시그널을 생성한다.

    별도 DB 세션을 사용하여 메인 요청과 독립적으로 실행.

    Args:
        cot_validation: REQ-023 CoT 검증 결과. 불완전 시 confidence 감산에 사용.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await _generate_signals_from_picks(db, stock_picks_data, cot_validation)
    except Exception as e:
        logger.error(f"백그라운드 시그널 생성 실패: {e}")
    finally:
        db.close()


async def _generate_signals_from_picks(
    db: Session, stock_picks, cot_validation: dict | None = None,
) -> None:
    """브리핑의 stock_picks에서 종목명을 추출하여 자동 투자 시그널 생성.

    Args:
        cot_validation: REQ-023 CoT 검증 결과. 불완전 시 생성된 시그널 confidence 0.1 감산.
    """
    if not stock_picks:
        return

    # stock_picks가 문자열이면 파싱
    picks = stock_picks
    if isinstance(picks, str):
        try:
            picks = json.loads(picks)
        except json.JSONDecodeError:
            logger.warning("stock_picks JSON 파싱 실패")
            return

    if not isinstance(picks, list):
        return

    # 종목명/종목코드 + 브리핑 힌트 추출
    stock_hints: list[tuple[str, str, dict]] = []  # (name, code, hint)
    for pick in picks:
        if isinstance(pick, dict):
            name = pick.get("stock", "").strip()
            code = pick.get("stock_code", "").strip()
            if name or code:
                hint = {
                    "action": pick.get("action", ""),
                    "reasoning": pick.get("reasoning", ""),
                }
                stock_hints.append((name, code, hint))

    if not stock_hints:
        return

    # 브리핑 pick이 너무 많으면 시그널 품질이 희석됨.
    # 최대 5개 종목으로 제한하여 AI가 확신 있는 종목에만 집중하도록 유도.
    MAX_SIGNAL_PICKS = 5
    if len(stock_hints) > MAX_SIGNAL_PICKS:
        logger.info(
            "브리핑 추천 종목 %d개 → 상위 %d개로 제한",
            len(stock_hints), MAX_SIGNAL_PICKS,
        )
        stock_hints = stock_hints[:MAX_SIGNAL_PICKS]

    stock_labels = [name or code for name, code, _ in stock_hints]
    logger.info(f"브리핑 추천 종목 {len(stock_labels)}개에 대해 시그널 자동 생성: {stock_labels}")

    # DB에서 종목 매칭 (종목코드 > 정확 이름 > 부분 이름 순으로 매칭)
    matched: list[tuple] = []  # (stock, hint)
    for name, code, hint in stock_hints:
        stock = None
        # 1순위: 종목코드로 정확 매칭
        if code:
            stock = db.query(Stock).filter(Stock.stock_code == code).first()
        # 2순위: 종목명 정확 매칭
        if not stock and name:
            stock = db.query(Stock).filter(Stock.name == name).first()
        # 3순위: 종목명 부분 매칭 (결과가 1개일 때만 채택 — 모호한 매칭 방지)
        if not stock and name:
            partial = db.query(Stock).filter(Stock.name.ilike(f"%{name}%")).all()
            if len(partial) == 1:
                stock = partial[0]
            elif len(partial) > 1:
                logger.warning(
                    "브리핑 추천 종목 '%s' 부분 매칭 %d건 — 모호하여 스킵: %s",
                    name, len(partial), [s.name for s in partial[:5]],
                )
        if stock:
            matched.append((stock, hint))
        else:
            logger.warning(f"브리핑 추천 종목 '{name or code}'을 DB에서 찾을 수 없습니다")

    # 각 종목에 대해 시그널 생성 (순차 실행 — AI API rate limit 고려)
    # REQ-023: CoT 불완전 분석 시 confidence 0.1 감산
    is_incomplete_cot = (
        cot_validation is not None
        and cot_validation.get("status") == "incomplete_analysis"
    )
    generated = 0
    for stock, hint in matched:
        try:
            signal = await analyze_stock(db, stock.id, briefing_hint=hint)
            if signal:
                # REQ-023: CoT 불완전 분석 시 confidence 감산 및 태그
                if is_incomplete_cot:
                    signal.confidence = max(0.0, signal.confidence - 0.1)
                    db.commit()
                    logger.info(
                        "REQ-023: CoT 불완전 분석으로 %s confidence 0.1 감산 → %.2f",
                        stock.name, signal.confidence,
                    )
                generated += 1
                logger.info(f"브리핑 추천 → 시그널 생성: {stock.name} → {signal.signal} ({signal.confidence})")
        except Exception as e:
            logger.error(f"브리핑 추천 종목 '{stock.name}' 시그널 생성 실패: {e}")

    logger.info(f"브리핑 추천 종목 시그널 생성 완료: {generated}/{len(matched)}건")


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
{json.dumps(macro_alerts.get("alerts"), ensure_ascii=False, indent=2) if macro_alerts.get("alerts") else '없음'}

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
