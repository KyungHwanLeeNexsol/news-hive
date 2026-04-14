"""해외 거시경제 뉴스 크롤러.

국내 증시에 직접 영향을 미치는 해외 매크로 이벤트를 Google News RSS로 수집한다.
수집 대상: 연준(FOMC), 미국 물가지표(CPI/PPI), 글로벌 반도체 업황, 달러/환율.

DB에 source='macro_global' 로 저장하여 일반 뉴스와 구분한다.
"""

import asyncio
import html
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser
import httpx

logger = logging.getLogger(__name__)

# 국내 증시에 영향이 큰 해외 매크로 키워드 (Google News RSS 쿼리)
# 키: 카테고리 레이블 (로그/DB 태깅용), 값: 검색어
MACRO_QUERIES: dict[str, str] = {
    "fed_policy": "Federal Reserve interest rate FOMC",
    "us_inflation": "US CPI PPI inflation data",
    "semiconductor_global": "semiconductor TSMC Nvidia memory chip supply",
    "korea_export": "Korea export semiconductor battery trade",
    "dollar_yen": "US dollar Korean won exchange rate",
    "china_economy": "China economy manufacturing PMI slowdown",
    "oil_energy": "oil price OPEC energy supply",
}

# 쿼리당 최대 기사 수
_MAX_PER_QUERY = 5

# HTTP 타임아웃
_TIMEOUT = 10


async def _fetch_macro_query(category: str, query: str) -> list[dict]:
    """단일 매크로 키워드 Google News RSS 수집."""
    encoded = quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(rss_url, timeout=_TIMEOUT)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"매크로 뉴스 [{category}] 수집 실패: {e}")
            return []

    feed = feedparser.parse(resp.text)
    articles = []
    for entry in feed.entries[:_MAX_PER_QUERY]:
        pub_date = datetime.now(timezone.utc)
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        title = html.unescape(entry.get("title", "")).strip()
        url = entry.get("link", "").strip()
        if not title or not url:
            continue

        articles.append({
            "title": title,
            "url": url,
            "source": "macro_global",
            "published_at": pub_date,
            "description": html.unescape(entry.get("summary", "")).strip(),
            "category": category,  # DB 저장 시 urgency 또는 source 서브태그로 활용
        })

    logger.debug(f"매크로 뉴스 [{category}]: {len(articles)}건 수집")
    return articles


async def fetch_macro_global_news() -> list[dict]:
    """전체 매크로 카테고리 병렬 수집.

    Returns:
        source='macro_global' 형태의 기사 딕셔너리 목록.
        뉴스 크롤러 파이프라인에서 news_crawler.py 와 동일한 형식을 사용한다.
    """
    tasks = [
        _fetch_macro_query(category, query)
        for category, query in MACRO_QUERIES.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: list[dict] = []
    for (category, _), result in zip(MACRO_QUERIES.items(), results):
        if isinstance(result, list):
            all_articles.extend(result)
        elif isinstance(result, Exception):
            logger.warning(f"매크로 뉴스 [{category}] 오류: {result}")

    logger.info(f"매크로 글로벌 뉴스 총 {len(all_articles)}건 수집 ({len(MACRO_QUERIES)}개 카테고리)")
    return all_articles
