import asyncio
import logging

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.services.crawlers.naver import search_naver_news
from app.services.crawlers.google import search_google_news
from app.services.crawlers.newsapi import search_newsapi
from app.services.ai_classifier import classify_news

logger = logging.getLogger(__name__)


async def crawl_all_news(db: Session) -> int:
    """Main orchestrator: crawl news for all stocks and sectors, classify, and save."""
    stocks = db.query(Stock).all()
    sectors = db.query(Sector).all()

    # Build search queries from stock names + keywords
    search_queries: list[str] = []
    for stock in stocks:
        search_queries.append(stock.name)
        if stock.keywords:
            search_queries.extend(stock.keywords)

    # Also search by sector names for industry-wide news
    for sector in sectors:
        if db.query(Stock).filter(Stock.sector_id == sector.id).count() > 0:
            search_queries.append(sector.name)

    search_queries = list(set(search_queries))
    if not search_queries:
        logger.info("No stocks or sectors registered. Skipping news crawl.")
        return 0

    # Crawl from all sources in parallel
    all_raw_articles: list[dict] = []
    for query in search_queries:
        results = await asyncio.gather(
            search_naver_news(query, display=5),
            search_google_news(query, num=5),
            search_newsapi(query, page_size=5),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, list):
                all_raw_articles.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"Crawler error for query '{query}': {result}")

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_articles: list[dict] = []
    for article in all_raw_articles:
        url = article.get("url", "")
        if not url or url in seen_urls:
            continue
        # Check if already in DB
        exists = db.query(NewsArticle).filter(NewsArticle.url == url).first()
        if exists:
            seen_urls.add(url)
            continue
        seen_urls.add(url)
        unique_articles.append(article)

    if not unique_articles:
        logger.info("No new articles found.")
        return 0

    logger.info(f"Found {len(unique_articles)} new articles. Classifying...")

    # AI classification and save
    saved_count = 0
    # Process in batches of 5 to avoid overloading the AI API
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
    """Save a single article with AI classification."""
    from app.models.news_relation import NewsStockRelation

    # Save the article first
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

    # Classify with AI
    classifications = await classify_news(article_data["title"], sectors, stocks)

    for cls in classifications:
        relation = NewsStockRelation(
            news_id=article.id,
            stock_id=cls.get("stock_id"),
            sector_id=cls.get("sector_id"),
            match_type=cls.get("match_type", "ai_classified"),
            relevance=cls.get("relevance", "indirect"),
        )
        db.add(relation)

    db.commit()
    return True
