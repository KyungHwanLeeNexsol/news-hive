import asyncio
import logging

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.services.crawlers.naver import search_naver_news
from app.services.crawlers.google import search_google_news
from app.services.crawlers.yahoo import search_yahoo_finance_top, search_yahoo_stock_news
from app.services.crawlers.korean_rss import fetch_korean_rss_feeds
from app.services.ai_classifier import _extract_sector_keywords

logger = logging.getLogger(__name__)

# Query budget for search-based crawlers
MAX_TOTAL_QUERIES = 50
MAX_STOCK_QUERIES = 15

# Round-robin index for stock selection (persists across cycles within same process)
_stock_rr_index = 0


def _build_search_queries(db: Session, sectors: list[Sector], stocks: list[Stock]) -> list[str]:
    """Build search queries ensuring all sectors are covered.

    Strategy:
    1. ALL sectors with stocks — guaranteed coverage every crawl
    2. Stocks with custom keywords (user-curated, always included)
    3. Random sample of remaining stocks to fill budget
    """
    queries: set[str] = set()

    # 1) ALL sectors with stocks — guaranteed every cycle
    #    Also add sub-keywords from compound names (e.g. "반도체와반도체장비" → "반도체", "반도체장비")
    sectors_with_stocks = [
        sector for sector in sectors
        if db.query(Stock.id).filter(Stock.sector_id == sector.id).first()
    ]
    for sector in sectors_with_stocks:
        queries.add(sector.name)
        for kw in _extract_sector_keywords(sector.name):
            if kw != sector.name.lower():
                queries.add(kw)

    # 2) Stocks with custom keywords — always included
    keyword_stocks = [s for s in stocks if s.keywords]
    for stock in keyword_stocks:
        queries.add(stock.name)
        for kw in stock.keywords:
            queries.add(kw)

    # 3) Round-robin selection of remaining stocks to fill budget
    #    Cycles through all stocks evenly across crawl cycles
    global _stock_rr_index
    remaining = sorted([s for s in stocks if not s.keywords], key=lambda s: s.id)
    stock_budget = max(0, MAX_TOTAL_QUERIES - len(queries))
    sample_size = min(stock_budget, MAX_STOCK_QUERIES, len(remaining))
    if sample_size > 0 and remaining:
        for i in range(sample_size):
            idx = (_stock_rr_index + i) % len(remaining)
            queries.add(remaining[idx].name)
        _stock_rr_index = (_stock_rr_index + sample_size) % len(remaining)

    return list(queries)


def _resolve_query_relations(
    query: str,
    sectors: list[Sector],
    stocks: list[Stock],
) -> list[dict]:
    """Resolve a search query to sector/stock relations.

    Since articles are fetched by searching for a specific sector or stock name,
    we can automatically tag them with the entity that triggered the search.
    """
    results = []
    matched_sector_ids: set[int] = set()

    # Check if query matches a stock name
    for stock in stocks:
        if stock.name == query:
            results.append({
                "stock_id": stock.id,
                "sector_id": stock.sector_id,
                "match_type": "keyword",
                "relevance": "direct",
            })
            matched_sector_ids.add(stock.sector_id)
        elif stock.keywords and query in stock.keywords:
            results.append({
                "stock_id": stock.id,
                "sector_id": stock.sector_id,
                "match_type": "keyword",
                "relevance": "indirect",
            })
            matched_sector_ids.add(stock.sector_id)

    # Check if query matches a sector name (exact or sub-keyword)
    for sector in sectors:
        if sector.id in matched_sector_ids:
            continue
        if sector.name == query:
            results.append({
                "stock_id": None,
                "sector_id": sector.id,
                "match_type": "keyword",
                "relevance": "direct",
            })
        elif query.lower() in _extract_sector_keywords(sector.name):
            results.append({
                "stock_id": None,
                "sector_id": sector.id,
                "match_type": "keyword",
                "relevance": "indirect",
            })

    return results


async def crawl_all_news(db: Session) -> int:
    """Main orchestrator: crawl news for all stocks and sectors, classify, and save."""
    stocks = db.query(Stock).all()
    sectors = db.query(Sector).all()

    logger.info(f"DB state: {len(sectors)} sectors, {len(stocks)} stocks")

    all_raw_articles: list[dict] = []
    source_counts: dict[str, int] = {"naver": 0, "google": 0, "yahoo": 0, "korean_rss": 0, "us_news": 0}

    # Phase 1: Fetch Korean financial RSS feeds (once per cycle, not per query)
    try:
        korean_rss_articles = await fetch_korean_rss_feeds()
        # RSS feeds have no specific query — they'll rely on keyword/AI classification
        for a in korean_rss_articles:
            a["_query"] = None
        all_raw_articles.extend(korean_rss_articles)
        source_counts["korean_rss"] = len(korean_rss_articles)
    except Exception as e:
        logger.warning(f"Korean RSS feeds failed: {e}")

    # Phase 1.2: Yahoo Finance top headlines (global market, once per cycle)
    try:
        yahoo_top_articles = await search_yahoo_finance_top(num=20)
        for a in yahoo_top_articles:
            a["_query"] = None
        all_raw_articles.extend(yahoo_top_articles)
        source_counts["yahoo"] = len(yahoo_top_articles)
    except Exception as e:
        logger.warning(f"Yahoo Finance top headlines failed: {e}")

    # Phase 1.5: US industry news (sector-level, English)
    try:
        from app.services.crawlers.us_news import fetch_us_industry_news

        sector_names_with_stocks = [
            sector.name for sector in sectors
            if db.query(Stock.id).filter(Stock.sector_id == sector.id).first()
        ]
        sector_by_name = {s.name: s for s in sectors}
        us_results = await fetch_us_industry_news(sector_names_with_stocks)

        for sector_name, articles in us_results:
            sector = sector_by_name.get(sector_name)
            for a in articles:
                a["_query"] = None
                a["_us_sector_id"] = sector.id if sector else None
            all_raw_articles.extend(articles)
            source_counts["us_news"] += len(articles)
    except Exception as e:
        logger.warning(f"US news fetch failed: {e}")

    # Phase 2: Query-based search across all sources
    search_queries = _build_search_queries(db, sectors, stocks)
    if search_queries:
        logger.info(f"Crawling news for {len(search_queries)} search queries (sample: {search_queries[:5]})")

        semaphore = asyncio.Semaphore(3)

        # Map stock names to codes for Yahoo per-stock search
        stock_code_by_name = {s.name: s.stock_code for s in stocks}

        async def _search_one(query: str):
            async with semaphore:
                crawlers = [
                    search_naver_news(query, display=10),
                    search_google_news(query, num=10),
                ]
                source_names = ["naver", "google"]

                # If query matches a stock name, also fetch Yahoo per-stock news
                stock_code = stock_code_by_name.get(query)
                if stock_code:
                    crawlers.append(search_yahoo_stock_news(stock_code, num=5))
                    source_names.append("yahoo")

                results = await asyncio.gather(
                    *crawlers,
                    return_exceptions=True,
                )
                articles = []
                for source_name, result in zip(source_names, results):
                    if isinstance(result, list):
                        # Tag each article with the query that fetched it
                        for a in result:
                            a["_query"] = query
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
    else:
        logger.info("No search queries built. Using RSS feeds only.")

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
    """Save a single article with query-based + keyword + AI classification.

    Three-phase tagging:
    1. Query-based: If the article was fetched by searching for a sector/stock name,
       automatically tag it with that entity (most reliable).
    2. Keyword matching: Scan title for exact sector/stock name matches.
    3. AI classification: Gemini API fallback for articles with no tags yet.
    """
    from app.models.news_relation import NewsStockRelation
    from app.services.ai_classifier import classify_news, classify_sentiment

    article = NewsArticle(
        title=article_data["title"],
        summary=article_data.get("description"),
        url=article_data["url"],
        source=article_data["source"],
        published_at=article_data.get("published_at"),
        sentiment=classify_sentiment(article_data["title"]),
    )
    db.add(article)
    try:
        db.flush()
    except Exception:
        db.rollback()
        return False

    # Phase 1: Query-based auto-tagging (guaranteed relation from search context)
    query = article_data.get("_query")
    query_relations = []
    if query:
        query_relations = _resolve_query_relations(query, sectors, stocks)

    # Phase 1.5: US sector-level auto-tagging
    us_sector_id = article_data.get("_us_sector_id")
    if us_sector_id:
        query_relations.append({
            "stock_id": None,
            "sector_id": us_sector_id,
            "match_type": "keyword",
            "relevance": "indirect",
        })

    # Phase 2+3: Keyword + AI classification (may find additional relations)
    ai_relations = await classify_news(article_data["title"], sectors, stocks)

    # Merge: deduplicate by (stock_id, sector_id) pair
    seen_pairs: set[tuple] = set()
    all_relations: list[dict] = []

    for rel in query_relations + ai_relations:
        pair = (rel.get("stock_id"), rel.get("sector_id"))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            all_relations.append(rel)

    for cls in all_relations:
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
