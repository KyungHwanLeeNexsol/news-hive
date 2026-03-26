import asyncio
import gc
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
from app.services.crawlers.content_scraper import scrape_articles_batch
from app.services.ai_classifier import (
    KeywordIndex, classify_news, classify_news_with_ai, classify_sentiment,
    classify_sentiment_with_ai, _extract_sector_keywords,
    translate_articles_batch, is_non_financial_article,
)

logger = logging.getLogger(__name__)

# Query budget for search-based crawlers
MAX_TOTAL_QUERIES = 60
MAX_STOCK_QUERIES = 20

# Regex to strip noise for title dedup (whitespace, punctuation, source suffixes)
_TITLE_NOISE_RE = re.compile(r"[\s\-–—·:;,.\[\](){}「」『』<>《》\u200b]+")
# Match source suffix: "- 한국경제", "- 철강금속신문", "| 뉴스1" etc. (1-4 words at end)
_SOURCE_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*[\w.]{1,20}(?:\s[\w.]{1,10}){0,3}$")


def _normalize_title(title: str) -> str:
    """Normalize a title for near-duplicate detection.

    Strips source suffix (e.g. '- 한국경제', '- 철강금속신문', '- Yahoo Finance'),
    normalizes Korean number expressions, collapses whitespace/punctuation, and lowercases.
    """
    t = _SOURCE_SUFFIX_RE.sub("", title)
    # Normalize Korean number variants
    t = re.sub(r"(\d)천만", r"\g<1>000만", t)
    t = re.sub(r"(\d)백만", r"\g<1>00만", t)
    t = _TITLE_NOISE_RE.sub("", t).lower()
    return t


def _title_bigrams(norm_title: str) -> set[str]:
    """Extract character bigrams from a normalized title for fuzzy matching."""
    if len(norm_title) < 2:
        return set()
    return {norm_title[i:i+2] for i in range(len(norm_title) - 1)}


def _is_similar_title(bigrams_a: set[str], bigrams_b: set[str], threshold: float = 0.55) -> bool:
    """Check if two titles are similar using Jaccard + containment on bigrams.

    Two-pass approach:
    1. Jaccard similarity >= threshold (symmetric, strict)
    2. Containment ratio >= 0.7 (catches cases where one title is a subset
       of another with different surrounding text, e.g. same event reported
       with different wording)
    """
    if not bigrams_a or not bigrams_b:
        return False
    intersection = len(bigrams_a & bigrams_b)
    union = len(bigrams_a | bigrams_b)
    if (intersection / union) >= threshold:
        return True
    # Containment: what fraction of the smaller title is found in the larger
    smaller = min(len(bigrams_a), len(bigrams_b))
    if smaller > 0 and (intersection / smaller) >= 0.7:
        return True
    return False

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


async def crawl_all_news(db: Session, skip_us_news: bool = False) -> int:
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

    phase1_tasks = [_fetch_korean_rss(), _fetch_yahoo_top()]
    if not skip_us_news:
        phase1_tasks.append(_fetch_us_news())
    phase1_results = await asyncio.gather(
        *phase1_tasks,
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

        semaphore = asyncio.Semaphore(10)
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

    # Deduplicate by URL + near-duplicate title detection (exact + fuzzy)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    seen_bigrams: list[set[str]] = []  # for fuzzy matching
    unique_articles: list[dict] = []
    existing_urls = set()
    for row in db.query(NewsArticle.url).yield_per(500):
        existing_urls.add(row[0])

    # Load recent titles from DB for cross-batch dedup (last 7 days worth)
    from datetime import datetime, timedelta, timezone
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    existing_norm_titles = []
    for row in db.query(NewsArticle.title).filter(NewsArticle.published_at >= recent_cutoff).yield_per(500):
        norm = _normalize_title(row[0])
        if norm:
            seen_titles.add(norm)
            existing_norm_titles.append(norm)
    # Build bigram index for existing titles (for fuzzy dedup)
    for norm in existing_norm_titles:
        bg = _title_bigrams(norm)
        if bg:
            seen_bigrams.append(bg)

    title_dedup_count = 0
    fuzzy_dedup_count = 0
    for article in all_raw_articles:
        url = article.get("url", "")
        if not url or url in seen_urls or url in existing_urls:
            continue
        seen_urls.add(url)

        norm_title = _normalize_title(article.get("title", ""))
        if not norm_title:
            unique_articles.append(article)
            continue

        # Exact match dedup
        if norm_title in seen_titles:
            title_dedup_count += 1
            continue

        # Fuzzy match dedup (bigram Jaccard similarity)
        new_bigrams = _title_bigrams(norm_title)
        if new_bigrams and len(new_bigrams) >= 4:  # skip very short titles
            is_fuzzy_dup = False
            for existing_bg in seen_bigrams:
                if _is_similar_title(new_bigrams, existing_bg):
                    is_fuzzy_dup = True
                    break
            if is_fuzzy_dup:
                fuzzy_dedup_count += 1
                continue

        seen_titles.add(norm_title)
        if new_bigrams:
            seen_bigrams.append(new_bigrams)
        unique_articles.append(article)

    if title_dedup_count or fuzzy_dedup_count:
        logger.info(f"Filtered {title_dedup_count} exact + {fuzzy_dedup_count} fuzzy duplicate articles by title")

    # Free dedup structures no longer needed
    del all_raw_articles, seen_urls, seen_titles, seen_bigrams, existing_urls, existing_norm_titles
    gc.collect()

    # Filter out non-financial articles (entertainment, sports, lifestyle)
    pre_filter_count = len(unique_articles)
    unique_articles = [a for a in unique_articles if not is_non_financial_article(a.get("title", ""), a.get("url", ""), a.get("description", ""))]
    filtered_count = pre_filter_count - len(unique_articles)
    if filtered_count:
        logger.info(f"Filtered {filtered_count} non-financial articles (entertainment/sports/lifestyle)")

    if not unique_articles:
        logger.info(f"No new articles (existing={len(existing_urls)}, raw={len(all_raw_articles)}).")
        return 0

    logger.info(f"Saving {len(unique_articles)} new articles...")

    # Translate English titles to Korean before saving
    await translate_articles_batch(unique_articles)

    # Pre-compute relations and discard articles with no sector/stock match
    for ad in unique_articles:
        relations: list[dict] = []
        query = ad.get("_query")
        if query:
            relations.extend(_resolve_query_relations(query, index, sectors))
        us_sector_id = ad.get("_us_sector_id")
        if us_sector_id:
            relations.append({
                "stock_id": None, "sector_id": us_sector_id,
                "match_type": "keyword", "relevance": "indirect",
            })
        relations.extend(classify_news(ad["title"], index))
        ad["_relations"] = relations

    # AI 분류: 키워드 매칭이 안 된 기사에 대해 AI로 섹터 분류 시도
    unmatched_count = sum(1 for a in unique_articles if not a.get("_relations"))
    if unmatched_count > 0:
        logger.info(f"Running AI classification on {unmatched_count} unmatched articles...")
        try:
            await classify_news_with_ai(unique_articles, index, sectors)
        except Exception as e:
            logger.warning(f"AI classification failed (continuing with keyword matches): {e}")

    pre_rel_count = len(unique_articles)
    unique_articles = [a for a in unique_articles if a.get("_relations")]
    no_rel_count = pre_rel_count - len(unique_articles)
    if no_rel_count:
        logger.info(f"Skipped {no_rel_count} articles with no sector/stock match")

    if not unique_articles:
        logger.info("No articles with sector/stock relations to save.")
        return 0

    # AI 감성분석: 키워드 분석이 neutral인 기사에 대해 AI로 정밀 분석
    try:
        await classify_sentiment_with_ai(unique_articles)
    except Exception as e:
        logger.warning(f"AI sentiment classification failed (using keyword-based): {e}")

    # Phase 3: Scrape article content (본문 스크래핑)
    url_to_content = await scrape_articles_batch(unique_articles)
    for ad in unique_articles:
        ad["_content"] = url_to_content.get(ad["url"])

    from sqlalchemy import text as sa_text

    saved_count = 0
    batch_size = 30

    for i in range(0, len(unique_articles), batch_size):
        batch = unique_articles[i : i + batch_size]

        # Step 1: Bulk insert articles via raw SQL
        values_parts = []
        params: dict = {}
        for j, ad in enumerate(batch):
            values_parts.append(
                f"(:t{j}, :sm{j}, :u{j}, :sr{j}, :pa{j}, :se{j}, :ct{j})"
            )
            params[f"t{j}"] = ad["title"][:500]
            params[f"sm{j}"] = (ad.get("description") or "")[:2000]
            params[f"u{j}"] = ad["url"][:1000]
            params[f"sr{j}"] = ad["source"]
            params[f"pa{j}"] = ad.get("published_at")
            params[f"se{j}"] = ad.get("_ai_sentiment") or classify_sentiment(ad["title"])
            params[f"ct{j}"] = ad.get("_content")

        sql = sa_text(
            f"""INSERT INTO news_articles (title, summary, url, source, published_at, sentiment, content)
            VALUES {', '.join(values_parts)}
            ON CONFLICT (url) DO NOTHING
            RETURNING id, url"""
        )

        url_to_id: dict = {}
        for attempt in range(3):
            try:
                result = db.execute(sql, params)
                url_to_id = {row[1]: row[0] for row in result.fetchall()}
                db.commit()
                break
            except Exception as e:
                db.rollback()
                if attempt < 2:
                    logger.info(f"Article batch insert retry {attempt+1}: {type(e).__name__}")
                    # Dispose stale connections and wait before retry
                    db.get_bind().dispose()
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"Article batch insert failed (giving up): {e}")

        if not url_to_id:
            continue

        # Step 2: Bulk insert relations via raw SQL (using pre-computed _relations)
        rel_values = []
        rel_params: dict = {}
        rel_idx = 0

        for ad in batch:
            article_id = url_to_id.get(ad["url"])
            if not article_id:
                continue

            relations = ad.get("_relations", [])

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
            for attempt in range(3):
                try:
                    db.execute(rel_sql, rel_params)
                    db.commit()
                    break
                except Exception as e:
                    db.rollback()
                    if attempt < 2:
                        logger.info(f"Relations batch insert retry {attempt+1}: {type(e).__name__}")
                        db.get_bind().dispose()
                        await asyncio.sleep(2)
                    else:
                        logger.warning(f"Relations batch insert failed (giving up): {e}")

        # @MX:WARN: [AUTO] 가격 캡처 실패가 뉴스 수집을 중단하면 안 됨
        # @MX:REASON: REQ-NPI-001~004 - 뉴스 저장 후 가격 스냅샷 캡처, 실패 시 무시
        if rel_values:
            try:
                from app.services.news_price_impact_service import capture_price_snapshots

                # relations에서 stock_id가 있는 (news_id, stock_id, relation_id) 쌍 수집
                article_stock_pairs: list[tuple[int, int, int | None]] = []
                for ad in batch:
                    article_id = url_to_id.get(ad["url"])
                    if not article_id:
                        continue
                    for rel in ad.get("_relations", []):
                        stock_id = rel.get("stock_id")
                        if stock_id:  # REQ-NPI-005: stock_id가 있는 관계만
                            article_stock_pairs.append((article_id, stock_id, None))

                if article_stock_pairs:
                    await capture_price_snapshots(db, article_stock_pairs)
            except Exception as e:
                logger.error(f"가격 스냅샷 캡처 실패 (뉴스 수집은 정상 진행): {e}")

        logger.info(f"Batch {i // batch_size + 1}: {len(url_to_id)} articles ({saved_count} total)")

    logger.info(f"Saved {saved_count} new articles.")
    return saved_count
