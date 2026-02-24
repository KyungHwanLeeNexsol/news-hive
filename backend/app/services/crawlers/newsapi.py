import html
from datetime import datetime, timezone

import httpx

from app.config import settings


async def search_newsapi(query: str, page_size: int = 10) -> list[dict]:
    """Search NewsAPI.org for articles matching the query."""
    if not settings.NEWSAPI_KEY:
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "pageSize": page_size,
        "sortBy": "publishedAt",
        "language": "ko",
        "apiKey": settings.NEWSAPI_KEY,
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

    data = resp.json()
    articles = []
    for item in data.get("articles", []):
        pub_date = None
        if item.get("publishedAt"):
            try:
                pub_date = datetime.fromisoformat(
                    item["publishedAt"].replace("Z", "+00:00")
                )
            except ValueError:
                pub_date = datetime.now(timezone.utc)

        articles.append(
            {
                "title": html.unescape(item.get("title", "")),
                "url": item.get("url", ""),
                "source": "newsapi",
                "published_at": pub_date,
                "description": html.unescape(item.get("description") or ""),
            }
        )
    return articles
