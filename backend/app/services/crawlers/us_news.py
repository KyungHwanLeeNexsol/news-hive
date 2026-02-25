"""US industry news crawler via Google News RSS (English).

Fetches sector-level US news for each Korean sector using English search terms.
Only industry/sector trends — no individual company tracking.
"""

import asyncio
import html
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import feedparser

logger = logging.getLogger(__name__)

# Round-robin index for US news sector rotation (persists across cycles)
_us_rr_index = 0

# Korean sector name -> English industry search term mapping
SECTOR_EN_TERMS: dict[str, str] = {
    "제약": "pharmaceutical industry news",
    "생명과학도구및서비스": "life sciences tools services",
    "게임엔터테인먼트": "gaming entertainment industry",
    "백화점과일반상점": "retail department store",
    "판매업체": "retail distributor",
    "화장품": "cosmetics beauty industry",
    "IT서비스": "IT services industry",
    "식품": "food industry",
    "디스플레이장비및부품": "display equipment components",
    "자동차부품": "auto parts industry",
    "레저용장비와제품": "leisure equipment products",
    "화학": "chemical industry",
    "자동차": "automotive industry",
    "섬유,의류,신발,호화품": "textile apparel luxury",
    "담배": "tobacco industry",
    "복합기업": "conglomerate",
    "창업투자": "venture capital",
    "반도체와반도체장비": "semiconductor industry",
    "건설": "construction industry",
    "부동산": "real estate industry",
    "건강관리장비와용품": "healthcare equipment supplies",
    "전자장비와기기": "electronic equipment instruments",
    "전기제품": "electrical products",
    "우주항공과국방": "aerospace defense industry",
    "방송과엔터테인먼트": "broadcasting entertainment media",
    "생물공학": "biotechnology industry",
    "소프트웨어": "software industry",
    "건강관리기술": "health technology",
    "건축자재": "building materials industry",
    "교육서비스": "education services industry",
    "조선": "shipbuilding industry",
    "핸드셋": "smartphone handset industry",
    "컴퓨터와주변기기": "computer peripherals industry",
    "통신장비": "telecommunications equipment",
    "에너지장비및서비스": "energy equipment services",
    "운송인프라": "transportation infrastructure",
    "가정용품": "household products industry",
    "가정용기기와용품": "home appliance industry",
    "기계": "machinery industry",
    "양방향미디어와서비스": "interactive media services",
    "은행": "banking industry",
    "식품과기본식료품소매": "grocery retail industry",
    "가구": "furniture industry",
    "철강": "steel industry",
    "항공사": "airline industry",
    "전기장비": "electrical equipment industry",
    "전자제품": "consumer electronics",
    "인터넷과카탈로그소매": "e-commerce retail",
    "음료": "beverage industry",
    "광고": "advertising industry",
    "포장재": "packaging industry",
    "가스유틸리티": "gas utilities",
    "석유와가스": "oil gas industry",
    "출판": "publishing industry",
    "손해보험": "property casualty insurance",
    "건강관리업체및서비스": "healthcare providers services",
    "호텔,레스토랑,레저": "hotel restaurant leisure",
    "종이와목재": "paper forestry industry",
    "기타금융": "diversified financials",
    "건축제품": "building products",
    "증권": "securities brokerage",
    "비철금속": "non-ferrous metals",
    "해운사": "shipping industry",
    "상업서비스와공급품": "commercial services supplies",
    "전기유틸리티": "electric utilities",
    "항공화물운송과물류": "air freight logistics",
    "디스플레이패널": "display panel industry",
    "전문소매": "specialty retail",
    "도로와철도운송": "road rail transportation",
    "생명보험": "life insurance industry",
    "복합유틸리티": "multi-utilities",
    "무선통신서비스": "wireless telecom services",
    "무역회사와판매업체": "trading companies distributors",
    "다각화된통신서비스": "diversified telecom services",
    "카드": "credit card payment industry",
}

# Budget: limit the number of US news queries per cycle
MAX_US_QUERIES = 40


async def _search_us_news_for_term(
    en_term: str, num: int = 5
) -> list[dict]:
    """Search Google News RSS with English/US locale for an industry term."""
    encoded = quote(en_term)
    rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(rss_url, timeout=10)
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

            url = entry.get("link", "")
            if not url:
                continue

            articles.append({
                "title": html.unescape(entry.get("title", "")),
                "url": url,
                "source": "us_news",
                "published_at": pub_date,
                "description": html.unescape(entry.get("summary", "")),
            })
    return articles


async def fetch_us_industry_news(
    sector_names: list[str],
) -> list[tuple[str, list[dict]]]:
    """Fetch US industry news for a list of Korean sector names.

    Returns list of (sector_name, articles) tuples.
    Only fetches for sectors that have an English term mapping.
    """
    queries = []
    for name in sector_names:
        en_term = SECTOR_EN_TERMS.get(name)
        if en_term:
            queries.append((name, en_term))

    # Limit queries per cycle — round-robin rotation for even coverage
    global _us_rr_index
    if len(queries) > MAX_US_QUERIES:
        selected = []
        for i in range(MAX_US_QUERIES):
            idx = (_us_rr_index + i) % len(queries)
            selected.append(queries[idx])
        _us_rr_index = (_us_rr_index + MAX_US_QUERIES) % len(queries)
        queries = selected

    semaphore = asyncio.Semaphore(3)
    results: list[tuple[str, list[dict]]] = []

    async def _fetch_one(sector_name: str, en_term: str):
        async with semaphore:
            articles = await _search_us_news_for_term(en_term, num=5)
            return (sector_name, articles)

    tasks = [_fetch_one(name, term) for name, term in queries]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in raw_results:
        if isinstance(result, tuple):
            results.append(result)
        elif isinstance(result, Exception):
            logger.warning(f"US news fetch error: {result}")

    total = sum(len(articles) for _, articles in results)
    logger.info(f"US news: fetched {total} articles for {len(results)} sectors")
    return results
