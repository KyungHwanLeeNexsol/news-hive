import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_naver_disabled = False


async def search_naver_news(query: str, display: int = 10) -> list[dict]:
    """Search Naver News API for articles matching the query."""
    global _naver_disabled

    # Once disabled (auth failure), skip all further requests this process
    if _naver_disabled:
        return []

    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        logger.warning("Naver API keys not configured, disabling Naver crawler")
        _naver_disabled = True
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}

    async with httpx.AsyncClient(timeout=10) as client:
        last_err = None
        for attempt in range(2):
            try:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                last_err = None
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < 1:
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                logger.warning(f"Naver API error: {e.response.status_code}, disabling Naver crawler")
                _naver_disabled = True
                return []
            except httpx.HTTPError as e:
                last_err = e
                if attempt < 1:
                    import asyncio
                    await asyncio.sleep(0.5)
                    continue
        if last_err:
            logger.warning(f"Naver API request failed: {last_err}")
            return []

    data = resp.json()
    articles = []
    for item in data.get("items", []):
        # Strip HTML tags from title/description
        title = _strip_html(item.get("title", ""))
        description = _strip_html(item.get("description", ""))

        pub_date = datetime.now(timezone.utc)
        if item.get("pubDate"):
            try:
                pub_date = datetime.strptime(
                    item["pubDate"], "%a, %d %b %Y %H:%M:%S %z"
                )
            except ValueError:
                pass

        articles.append(
            {
                "title": title,
                "url": item.get("originallink") or item.get("link", ""),
                "source": "naver",
                "published_at": pub_date,
                "description": description,
            }
        )
    return articles


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities from text."""
    import re
    import html

    return html.unescape(re.sub(r"<[^>]+>", "", text))
