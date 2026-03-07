import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Backoff: skip Naver requests until this timestamp (0 = not backing off)
_backoff_until: float = 0
_consecutive_failures: int = 0
_MAX_BACKOFF_SECONDS = 1800  # 30 minutes max backoff


async def search_naver_news(query: str, display: int = 10) -> list[dict]:
    """Search Naver News API for articles matching the query."""
    global _backoff_until, _consecutive_failures

    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return []

    # Temporary backoff instead of permanent disable
    if _backoff_until and time.monotonic() < _backoff_until:
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
                # Success — reset backoff
                _consecutive_failures = 0
                _backoff_until = 0
                last_err = None
                break
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status == 429 and attempt < 1:
                    await asyncio.sleep(1)
                    continue
                # Temporary backoff with exponential increase
                _consecutive_failures += 1
                backoff = min(60 * (2 ** (_consecutive_failures - 1)), _MAX_BACKOFF_SECONDS)
                _backoff_until = time.monotonic() + backoff
                logger.warning(
                    f"Naver API error {status}, backing off {backoff}s "
                    f"(failure #{_consecutive_failures})"
                )
                return []
            except httpx.HTTPError as e:
                last_err = e
                if attempt < 1:
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
