import asyncio
import logging
import re

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.services.crawlers.naver import search_naver_news
from app.services.crawlers.google import search_google_news
from app.services.crawlers.yahoo import search_yahoo_finance_top, search_yahoo_stock_news
from app.services.crawlers.korean_rss import fetch_korean_rss_feeds
from app.services.ai_classifier import (
    KeywordIndex, classify_news, classify_sentiment, _extract_sector_keywords,
    translate_articles_batch, is_non_financial_article,
)

logger = logging.getLogger(__name__)

# Query budget for search-based crawlers
MAX_TOTAL_QUERIES = 50
MAX_STOCK_QUERIES = 15

# Regex to strip noise for title dedup (whitespace, punctuation, source suffixes)
_TITLE_NOISE_RE = re.compile(r"[\s\-–—·:;,.\[\](){}「」『』<>《》\u200b]+")
_SOURCE_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*\S+$")


def _normalize_title(title: str) -> str:
    """Normalize a title for near-duplicate detection.

    Strips source suffix (e.g. '- 한국경제', '- 연합뉴스'), collapses whitespace/punctuation,
    and lowercases so that "고려아연 온산제련소 노사, 울주군 온산읍에 2억5000만원 지정기탁"
    and "고려아연 온산제련소 노사, 울주군 온산읍에 2억5천만원 지정기탁 - 뉴스1" match.
    """
    t = _SOURCE_SUFFIX_RE.sub("", title)
    t = t.replace("5천만", "5000만").replace("5백만", "500만")
    t = _TITLE_NOISE_RE.sub("", t).lower()
    return t

# Round-robin index for stock selection (persists across cycles within same process)
_stock_rr_index = 0


def _build_search_queries(db: Session, sectors: list[Sector], stocks: list[Stock]) -> list[str]:
    """Build search queries ensuring all sectors are covered within budget."""
    queries: set[str] = set()

    sectors_with_stocks = [
        sector for sector in sectors
        if db.query(Stock.id).filter(Stock.sector_id == sector.id).first()
    ]
    for sector in sectors_with_stocks:
        queries.add(sector.name)
        if len(queries) >= MAX_TOTAL_QUERIES:
            return list(queries)

    keyword_stocks = [s for s in stocks if s.keywords]
    for stock in keyword_stocks:
        queries.add(stock.name)
        for kw in stock.keywords:
            queries.add(kw)
        if len(queries) >= MAX_TOTAL_QUERIES:
            return list(queries)

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
    index: KeywordIndex,
    sectors: list[Sector],
) -> list[dict]:
    """Resolve a search query to sector/stock relations using index."""
    results = []
    matched_sector_ids: set[int] = set()

    # Check stock names
    if query in index.stock_names:
        stock_id, sector_id = index.stock_names[query]
        results.append({
            "stock_id": stock_id,
            "sector_id": sector_id,
            "match_type": "keyword",
            "relevance": "direct",
        })
        matched_sector_ids.add(sector_id)

    # Check stock keywords
    query_lower = query.lower()
    if query_lower in index.stock_keywords:
        for stock_id, sector_id in index.stock_keywords[query_lower]:
            if sector_id not in matched_sector_ids:
                results.append({
                    "stock_id": stock_id,
                    "sector_id": sector_id,
                    "match_type": "keyword",
                    "relevance": "indirect",
                })
                matched_sector_ids.add(sector_id)

    # Check sector names
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
        elif query_lower in _extract_sector_keywords(sector.name):
            results.append({
                "stock_id": None,
                "sector_id": sector.id,
                "match_type": "keyword",
                "relevance": "indirect",
            })

    return results


async def crawl_all_news(db: Session) -> int:
    """Main orchestrator: crawl news, classify by keyword, and save."""
    stocks = db.query(Stock).all()
    sectors = db.query(Sector).all()

    logger.info(f"DB state: {len(sectors)} sectors, {len(stocks)} stocks")

    # Build keyword index once — reused for all articles
    index = KeywordIndex.build(sectors, stocks)

    all_raw_articles: list[dict] = []
    source_counts: dict[str, int] = {"naver": 0, "google": 0, "yahoo": 0, "korean_rss": 0, "us_news": 0}

    # Phase 1: RSS feeds (parallel)
    async def _fetch_korean_rss():
        articles = await fetch_korean_rss_feeds()
        for a in articles:
            a["_query"] = None
        return ("korean_rss", articles)

    async def _fetch_yahoo_top():
        articles = await search_yahoo_finance_top(num=20)
        for a in articles:
            a["_query"] = None
        return ("yahoo", articles)

    async def _fetch_us_news():
        from app.services.crawlers.us_news import fetch_us_industry_news
        sector_names_with_stocks = [
            sector.name for sector in sectors
            if db.query(Stock.id).filter(Stock.sector_id == sector.id).first()
        ]
        sector_by_name = {s.name: s for s in sectors}
        us_results = await fetch_us_industry_news(sector_names_with_stocks)
        articles = []
        for sector_name, sector_articles in us_results:
            sector = sector_by_name.get(sector_name)
            for a in sector_articles:
                a["_query"] = None
                a["_us_sector_id"] = sector.id if sector else None
            articles.extend(sector_articles)
        return ("us_news", articles)

    phase1_results = await asyncio.gather(
        _fetch_korean_rss(), _fetch_yahoo_top(), _fetch_us_news(),
        return_exceptions=True,
    )
    for result in phase1_results:
        if isinstance(result, tuple):
            source_name, articles = result
            all_raw_articles.extend(articles)
            source_counts[source_name] = len(articles)
        elif isinstance(result, Exception):
            logger.warning(f"Phase 1 fetch failed: {result}")

    # Phase 2: Query-based search
    search_queries = _build_search_queries(db, sectors, stocks)
    if search_queries:
        logger.info(f"Crawling {len(search_queries)} queries (sample: {search_queries[:5]})")

        semaphore = asyncio.Semaphore(5)
        stock_code_by_name = {s.name: s.stock_code for s in stocks}

        async def _search_one(query: str):
            async with semaphore:
                crawlers = [
                    search_naver_news(query, display=10),
                    search_google_news(query, num=10),
                ]
                source_names = ["naver", "google"]
                stock_code = stock_code_by_name.get(query)
                if stock_code:
                    crawlers.append(search_yahoo_stock_news(stock_code, num=5))
                    source_names.append("yahoo")

                results = await asyncio.gather(*crawlers, return_exceptions=True)
                articles = []
                for sn, result in zip(source_names, results):
                    if isinstance(result, list):
                        for a in result:
                            a["_query"] = query
                        articles.extend(result)
                        source_counts[sn] += len(result)
                    elif isinstance(result, Exception):
                        logger.warning(f"[{sn}] error for '{query}': {result}")
                return articles

        tasks = [_search_one(q) for q in search_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                all_raw_articles.extend(result)

    logger.info(f"Raw articles by source: {source_counts}, total={len(all_raw_articles)}")

    # Deduplicate by URL + near-duplicate title detection
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique_articles: list[dict] = []
    existing_urls = {row[0] for row in db.query(NewsArticle.url).all()}

    # Load recent titles from DB for cross-batch dedup (last 7 days worth)
    from datetime import datetime, timedelta, timezone
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    existing_titles = {
        _normalize_title(row[0])
        for row in db.query(NewsArticle.title)
        .filter(NewsArticle.published_at >= recent_cutoff)
        .all()
    }
    seen_titles.update(existing_titles)

    title_dedup_count = 0
    for article in all_raw_articles:
        url = article.get("url", "")
        if not url or url in seen_urls or url in existing_urls:
            continue
        seen_urls.add(url)

        norm_title = _normalize_title(article.get("title", ""))
        if norm_title and norm_title in seen_titles:
            title_dedup_count += 1
            continue
        if norm_title:
            seen_titles.add(norm_title)

        unique_articles.append(article)

    if title_dedup_count:
        logger.info(f"Filtered {title_dedup_count} near-duplicate articles by title")

    # Filter out non-financial articles (entertainment, sports, lifestyle)
    pre_filter_count = len(unique_articles)
    unique_articles = [a for a in unique_articles if not is_non_financial_article(a.get("title", ""))]
    filtered_count = pre_filter_count - len(unique_articles)
    if filtered_count:
        logger.info(f"Filtered {filtered_count} non-financial articles (entertainment/sports/lifestyle)")

    if not unique_articles:
        logger.info(f"No new articles (existing={len(existing_urls)}, raw={len(all_raw_articles)}).")
        return 0

    logger.info(f"Saving {len(unique_articles)} new articles...")

    # Translate English titles to Korean before saving
    await translate_articles_batch(unique_articles)

    from sqlalchemy import text as sa_text

    saved_count = 0
    batch_size = 200

    for i in range(0, len(unique_articles), batch_size):
        batch = unique_articles[i : i + batch_size]

        # Step 1: Bulk insert articles via raw SQL (single round-trip)
        values_parts = []
        params: dict = {}
        for j, ad in enumerate(batch):
            values_parts.append(
                f"(:t{j}, :sm{j}, :u{j}, :sr{j}, :pa{j}, :se{j})"
            )
            params[f"t{j}"] = ad["title"][:500]
            params[f"sm{j}"] = (ad.get("description") or "")[:2000]
            params[f"u{j}"] = ad["url"][:1000]
            params[f"sr{j}"] = ad["source"]
            params[f"pa{j}"] = ad.get("published_at")
            params[f"se{j}"] = classify_sentiment(ad["title"])

        sql = sa_text(
            f"""INSERT INTO news_articles (title, summary, url, source, published_at, sentiment)
            VALUES {', '.join(values_parts)}
            ON CONFLICT (url) DO NOTHING
            RETURNING id, url"""
        )

        try:
            result = db.execute(sql, params)
            url_to_id = {row[1]: row[0] for row in result.fetchall()}
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Article batch insert failed: {e}")
            continue

        if not url_to_id:
            continue

        # Step 2: Bulk insert relations via raw SQL
        rel_values = []
        rel_params: dict = {}
        rel_idx = 0

        for ad in batch:
            article_id = url_to_id.get(ad["url"])
            if not article_id:
                continue

            relations: list[dict] = []
            query = ad.get("_query")
            if query:
                relations.extend(_resolve_query_relations(query, index, sectors))

            us_sector_id = ad.get("_us_sector_id")
            if us_sector_id:
                relations.append({
                    "stock_id": None,
                    "sector_id": us_sector_id,
                    "match_type": "keyword",
                    "relevance": "indirect",
                })

            keyword_rels = classify_news(ad["title"], index)
            relations.extend(keyword_rels)

            seen_pairs: set[tuple] = set()
            for rel in relations:
                pair = (rel.get("stock_id"), rel.get("sector_id"))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    rel_values.append(
                        f"(:ni{rel_idx}, :si{rel_idx}, :se{rel_idx}, :mt{rel_idx}, :rv{rel_idx})"
                    )
                    rel_params[f"ni{rel_idx}"] = article_id
                    rel_params[f"si{rel_idx}"] = rel.get("stock_id")
                    rel_params[f"se{rel_idx}"] = rel.get("sector_id")
                    rel_params[f"mt{rel_idx}"] = rel.get("match_type", "keyword")
                    rel_params[f"rv{rel_idx}"] = rel.get("relevance", "indirect")
                    rel_idx += 1

            saved_count += 1

        if rel_values:
            rel_sql = sa_text(
                f"""INSERT INTO news_stock_relations (news_id, stock_id, sector_id, match_type, relevance)
                VALUES {', '.join(rel_values)}"""
            )
            try:
                db.execute(rel_sql, rel_params)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.warning(f"Relations batch insert failed: {e}")

        logger.info(f"Batch {i // batch_size + 1}: {len(url_to_id)} articles ({saved_count} total)")

    logger.info(f"Saved {saved_count} new articles.")
    return saved_count
