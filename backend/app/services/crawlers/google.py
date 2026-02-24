import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import feedparser

logger = logging.getLogger(__name__)


async def _resolve_google_url(google_url: str, client: httpx.AsyncClient) -> str:
    """Resolve a Google News redirect URL to the actual article URL.

    Google News RSS links are like:
      https://news.google.com/rss/articles/CBMi...
    They redirect (via HTTP 302) to the real article URL.
    """
    if "news.google.com" not in google_url:
        return google_url

    try:
        resp = await client.head(google_url, follow_redirects=True, timeout=8)
        final_url = str(resp.url)
        if "news.google.com" not in final_url:
            return final_url
    except Exception:
        pass

    # Fallback: try GET with redirect
    try:
        resp = await client.get(google_url, follow_redirects=True, timeout=8)
        final_url = str(resp.url)
        if "news.google.com" not in final_url:
            return final_url
        # Some Google News pages embed the real URL in the HTML
        match = re.search(r'data-n-au="([^"]+)"', resp.text)
        if match:
            return match.group(1)
    except Exception as e:
        logger.debug(f"Google URL resolve failed for {google_url}: {e}")

    return google_url


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
            pub_date = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pub_date = datetime.now(timezone.utc)

            # Resolve Google redirect URL to actual article URL
            raw_url = entry.get("link", "")
            real_url = await _resolve_google_url(raw_url, client)

            articles.append(
                {
                    "title": html.unescape(entry.get("title", "")),
                    "url": real_url,
                    "source": "google",
                    "published_at": pub_date,
                    "description": html.unescape(entry.get("summary", "")),
                }
            )
    return articles
