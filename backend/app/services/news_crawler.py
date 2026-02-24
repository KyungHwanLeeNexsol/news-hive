import asyncio
import logging
import random

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.services.crawlers.naver import search_naver_news
from app.services.crawlers.google import search_google_news
from app.services.crawlers.newsapi import search_newsapi

logger = logging.getLogger(__name__)

# Keep total queries under this limit to avoid Render free-plan timeout
MAX_TOTAL_QUERIES = 10
MAX_STOCK_QUERIES = 3


def _build_search_queries(db: Session, sectors: list[Sector], stocks: list[Stock]) -> list[str]:
    """Build an optimised list of search queries.

    Keeps total queries ≤ MAX_TOTAL_QUERIES to stay within Render
    free-plan timeout (~2 min for the entire crawl cycle).

    Strategy:
    1. Random sample of sector names (broad industry news)
    2. Stocks with custom keywords (user-curated, always included)
    3. Random sample of remaining stocks
    """
    queries: set[str] = set()

    # 1) Stocks with custom keywords — always included (user explicitly wants these)
    keyword_stocks = [s for s in stocks if s.keywords]
    for stock in keyword_stocks:
        queries.add(stock.name)
        for kw in stock.keywords:
            queries.add(kw)

    # 2) Sector-level queries — random sample
    sectors_with_stocks = [
        sector for sector in sectors
        if db.query(Stock.id).filter(Stock.sector_id == sector.id).first()
    ]
    remaining_budget = MAX_TOTAL_QUERIES - len(queries) - MAX_STOCK_QUERIES
    if remaining_budget > 0 and sectors_with_stocks:
        sample_size = min(remaining_budget, len(sectors_with_stocks))
        for sector in random.sample(sectors_with_stocks, sample_size):
            queries.add(sector.name)

    # 3) Random sample of remaining stocks
    remaining = [s for s in stocks if not s.keywords]
    stock_budget = max(0, MAX_TOTAL_QUERIES - len(queries))
    sample_size = min(stock_budget, MAX_STOCK_QUERIES, len(remaining))
    if sample_size > 0:
        for stock in random.sample(remaining, sample_size):
            queries.add(stock.name)

    return list(queries)


async def crawl_all_news(db: Session) -> int:
    """Main orchestrator: crawl news for all stocks and sectors, classify, and save."""
    stocks = db.query(Stock).all()
    sectors = db.query(Sector).all()

    logger.info(f"DB state: {len(sectors)} sectors, {len(stocks)} stocks")

    search_queries = _build_search_queries(db, sectors, stocks)
    if not search_queries:
        logger.info("No stocks or sectors registered. Skipping news crawl.")
        return 0

    logger.info(f"Crawling news for {len(search_queries)} search queries (sample: {search_queries[:5]})")

    # Crawl from all sources — run queries with a small concurrency limit
    all_raw_articles: list[dict] = []
    source_counts: dict[str, int] = {"naver": 0, "google": 0, "newsapi": 0}
    semaphore = asyncio.Semaphore(3)

    async def _search_one(query: str):
        async with semaphore:
            results = await asyncio.gather(
                search_naver_news(query, display=5),
                search_google_news(query, num=5),
                search_newsapi(query, page_size=5),
                return_exceptions=True,
            )
            source_names = ["naver", "google", "newsapi"]
            articles = []
            for source_name, result in zip(source_names, results):
                if isinstance(result, list):
                    articles.extend(result)
                    source_counts[source_name] += len(result)
                elif isinstance(result, Exception):
                    logger.warning(f"Crawler [{source_name}] error for '{query}': {result}")
            return articles

    tasks = [_search_one(q) for q in search_queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_raw_articles.extend(result)
        elif isinstance(result, Exception):
            logger.warning(f"Query batch error: {result}")

    logger.info(f"Raw articles by source: {source_counts}, total={len(all_raw_articles)}")

    # Deduplicate by URL — pre-fetch existing URLs in one query
    seen_urls: set[str] = set()
    unique_articles: list[dict] = []
    existing_urls = {row[0] for row in db.query(NewsArticle.url).all()}

    for article in all_raw_articles:
        url = article.get("url", "")
        if not url or url in seen_urls or url in existing_urls:
            continue
        seen_urls.add(url)
        unique_articles.append(article)

    if not unique_articles:
        logger.info(f"No new articles (existing_urls={len(existing_urls)}, raw={len(all_raw_articles)}).")
        return 0

    logger.info(f"Found {len(unique_articles)} new articles. Classifying...")

    # AI classification and save — process in batches
    saved_count = 0
    batch_size = 5
    for i in range(0, len(unique_articles), batch_size):
        batch = unique_articles[i : i + batch_size]
        for article_data in batch:
            try:
                saved = await _save_article_with_classification(
                    db, article_data, sectors, stocks
                )
                if saved:
                    saved_count += 1
            except Exception as e:
                logger.warning(f"Error saving article: {e}")

    logger.info(f"Saved {saved_count} new articles.")
    return saved_count


async def _save_article_with_classification(
    db: Session,
    article_data: dict,
    sectors: list[Sector],
    stocks: list[Stock],
) -> bool:
    """Save a single article with keyword-based classification."""
    from app.models.news_relation import NewsStockRelation
    from app.services.ai_classifier import _keyword_fallback

    article = NewsArticle(
        title=article_data["title"],
        summary=article_data.get("description"),
        url=article_data["url"],
        source=article_data["source"],
        published_at=article_data.get("published_at"),
    )
    db.add(article)
    try:
        db.flush()
    except Exception:
        db.rollback()
        return False

    classifications = _keyword_fallback(article_data["title"], sectors, stocks)

    for cls in classifications:
        relation = NewsStockRelation(
            news_id=article.id,
            stock_id=cls.get("stock_id"),
            sector_id=cls.get("sector_id"),
            match_type=cls.get("match_type", "keyword"),
            relevance=cls.get("relevance", "indirect"),
        )
        db.add(relation)

    db.commit()
    return True
