"""Yahoo Finance RSS crawler.

No API key required. Fetches news from Yahoo Finance RSS feeds.
Two modes:
  1. Top financial headlines (global market news)
  2. Per-stock headlines using KRX ticker codes (e.g. 005930.KS)
"""

import html
import logging
from datetime import datetime, timezone

import httpx
import feedparser

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

YAHOO_TOP_URL = "https://finance.yahoo.com/news/rssindex"
YAHOO_TICKER_URL = "https://finance.yahoo.com/rss/headline?s={ticker}"


def _parse_feed_entries(feed: feedparser.FeedParserDict, num: int) -> list[dict]:
    """Parse feedparser entries into article dicts."""
    articles = []
    for entry in feed.entries[:num]:
        pub_date = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pub_date = datetime.now(timezone.utc)

        url = entry.get("link", "")
        title = html.unescape(entry.get("title", ""))
        description = html.unescape(entry.get("summary", ""))

        if not url or not title:
            continue

        articles.append({
            "title": title,
            "url": url,
            "source": "yahoo",
            "published_at": pub_date,
            "description": description,
        })
    return articles


async def search_yahoo_finance_top(num: int = 20) -> list[dict]:
    """Fetch top Yahoo Finance headlines (global market news)."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(YAHOO_TOP_URL, headers=HEADERS, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

    feed = feedparser.parse(resp.text)
    return _parse_feed_entries(feed, num)


async def search_yahoo_stock_news(stock_code: str, num: int = 5) -> list[dict]:
    """Fetch Yahoo Finance news for a specific KRX stock ticker.

    stock_code: 6-digit KRX code (e.g. "005930" for Samsung)
    Converts to Yahoo ticker format: "005930.KS"
    """
    ticker = f"{stock_code}.KS"
    url = YAHOO_TICKER_URL.format(ticker=ticker)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

    feed = feedparser.parse(resp.text)
    return _parse_feed_entries(feed, num)
