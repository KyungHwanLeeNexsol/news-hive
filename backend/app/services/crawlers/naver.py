from datetime import datetime, timezone

import httpx

from app.config import settings


async def search_naver_news(query: str, display: int = 10) -> list[dict]:
    """Search Naver News API for articles matching the query."""
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

    data = resp.json()
    articles = []
    for item in data.get("items", []):
        # Strip HTML tags from title/description
        title = _strip_html(item.get("title", ""))
        description = _strip_html(item.get("description", ""))

        pub_date = None
        if item.get("pubDate"):
            try:
                pub_date = datetime.strptime(
                    item["pubDate"], "%a, %d %b %Y %H:%M:%S %z"
                )
            except ValueError:
                pub_date = datetime.now(timezone.utc)

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
    """Remove HTML tags from text."""
    import re

    return re.sub(r"<[^>]+>", "", text)
