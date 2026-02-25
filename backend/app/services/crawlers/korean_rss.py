"""Korean financial news RSS feed crawler.

Fetches category-based RSS feeds from major Korean financial newspapers.
No API keys required — all feeds are publicly accessible.
"""

import asyncio
import html
import logging
from datetime import datetime, timezone

import httpx
import feedparser

logger = logging.getLogger(__name__)

# Korean financial news RSS feeds (category-based, no API keys needed)
KOREAN_RSS_FEEDS = [
    ("파이낸셜뉴스", "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml"),
    ("이투데이 산업", "https://rss.etoday.co.kr/eto/industry_news.xml"),
    ("이투데이 증권", "https://rss.etoday.co.kr/eto/market_news.xml"),
    ("전자신문 전자", "http://rss.etnews.com/06.xml"),
    ("전자신문 중공업", "http://rss.etnews.com/06065.xml"),
    ("한국경제", "https://www.hankyung.com/feed/finance"),
    ("서울경제", "https://www.sedaily.com/rss/finance"),
    ("이데일리", "http://rss.edaily.co.kr/stock_news.xml"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


async def _fetch_single_feed(name: str, url: str) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Korean RSS [{name}] fetch failed: {e}")
            return []

    feed = feedparser.parse(resp.text)
    articles = []
    for entry in feed.entries:
        pub_date = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pub_date = datetime.now(timezone.utc)

        title = html.unescape(entry.get("title", "")).strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        articles.append(
            {
                "title": title,
                "url": link,
                "source": "korean_rss",
                "published_at": pub_date,
                "description": html.unescape(entry.get("summary", "")).strip(),
            }
        )
    return articles


async def fetch_korean_rss_feeds() -> list[dict]:
    """Fetch all Korean financial RSS feeds in parallel.

    Returns articles from all feeds combined. Unlike search-based crawlers,
    this fetches entire category feeds once per crawl cycle.
    """
    tasks = [_fetch_single_feed(name, url) for name, url in KOREAN_RSS_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for (name, _), result in zip(KOREAN_RSS_FEEDS, results):
        if isinstance(result, list):
            logger.info(f"Korean RSS [{name}]: {len(result)} articles")
            all_articles.extend(result)
        elif isinstance(result, Exception):
            logger.warning(f"Korean RSS [{name}] error: {result}")

    logger.info(f"Korean RSS total: {len(all_articles)} articles from {len(KOREAN_RSS_FEEDS)} feeds")
    return all_articles
