import html
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import feedparser

logger = logging.getLogger(__name__)


async def search_google_news(query: str, num: int = 10) -> list[dict]:
    """Search Google News RSS for articles matching the query."""
    encoded_query = quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(rss_url, timeout=5)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries[:num]:
            pub_date = datetime.now(timezone.utc)
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

            url = entry.get("link", "")
            if not url:
                continue

            articles.append(
                {
                    "title": html.unescape(entry.get("title", "")),
                    "url": url,
                    "source": "google",
                    "published_at": pub_date,
                    "description": html.unescape(entry.get("summary", "")),
                }
            )
    return articles
