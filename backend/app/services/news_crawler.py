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
    get_or_build_index, calculate_relevance_score,
)

from app.config import settings
from app.services.circuit_breaker import api_circuit_breaker

logger = logging.getLogger(__name__)

# 설정에서 크롤링 쿼리 제한값 로드
MAX_TOTAL_QUERIES = settings.MAX_TOTAL_QUERIES
MAX_STOCK_QUERIES = settings.MAX_STOCK_QUERIES

# ---------------------------------------------------------------------------
# 뉴스 긴급도 분류
# ---------------------------------------------------------------------------
_BREAKING_RE = re.compile(
    r"\[속보\]|\[긴급\]|\[단독\]|\[breaking\]|\[exclusive\]",
    re.IGNORECASE,
)

_IMPORTANT_KEYWORDS = [
    "실적", "인수", "합병", "M&A", "규제", "소송", "배당",
    "상장폐지", "유상증자", "감사의견", "워크아웃", "법정관리",
    "공시", "IPO", "상폐",
]


def _classify_urgency(
    title: str,
    recent_topic_counts: dict[str, int] | None = None,
) -> str:
    """기사 제목으로 긴급도를 분류한다.

    반환값: 'breaking' / 'important' / 'routine'
    """
    # 속보/긴급/단독 태그 감지
    if _BREAKING_RE.search(title):
        return "breaking"

    # (선택) 동일 토픽 5건 이상이면 breaking
    if recent_topic_counts:
        for _topic, count in recent_topic_counts.items():
            if count >= 5:
                return "breaking"

    # 금융 영향 키워드 감지
    title_lower = title.lower()
    for kw in _IMPORTANT_KEYWORDS:
        if kw.lower() in title_lower:
            return "important"

    return "routine"


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


def _adaptive_threshold(
    bigrams_a: set[str],
    bigrams_b: set[str],
    source_a: str | None = None,
    source_b: str | None = None,
) -> float:
    """제목 길이와 출처에 따른 적응형 중복 제거 임계값 계산.

    - 짧은 제목 (bigram < 10): 0.70 (짧을수록 엄격하게)
    - 중간 제목 (10-20 bigrams): 0.60
    - 긴 제목 (20+ bigrams): 0.50 (길수록 부분 일치 허용)
    - 다른 출처: threshold + 0.05 (교차 출처는 약간 더 엄격)
    """
    avg_size = (len(bigrams_a) + len(bigrams_b)) / 2
    if avg_size < 10:
        threshold = 0.70
    elif avg_size <= 20:
        threshold = 0.60
    else:
        threshold = 0.50

    # 다른 출처에서 온 기사는 우연히 유사할 수 있으므로 임계값을 높임
    if source_a and source_b and source_a != source_b:
        threshold += 0.05

    return threshold


def _is_similar_title(
    bigrams_a: set[str],
    bigrams_b: set[str],
    threshold: float | None = None,
    source_a: str | None = None,
    source_b: str | None = None,
) -> bool:
    """Check if two titles are similar using Jaccard + containment on bigrams.

    Two-pass approach:
    1. Jaccard similarity >= threshold (symmetric, strict)
    2. Containment ratio >= 0.7 (catches cases where one title is a subset
       of another with different surrounding text, e.g. same event reported
       with different wording)

    threshold가 None이면 _adaptive_threshold()로 자동 결정.
    """
    if not bigrams_a or not bigrams_b:
        return False

    if threshold is None:
        threshold = _adaptive_threshold(bigrams_a, bigrams_b, source_a, source_b)

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

    # 캐시된 KeywordIndex 사용 (stocks/sectors 변경 시에만 재빌드)
    index = get_or_build_index(db)

    all_raw_articles: list[dict] = []
    source_counts: dict[str, int] = {"naver": 0, "google": 0, "yahoo": 0, "korean_rss": 0, "us_news": 0}

    # Phase 1: RSS feeds (parallel) — 서킷 브레이커 적용
    async def _fetch_korean_rss():
        if not api_circuit_breaker.is_available("korean_rss"):
            logger.info("korean_rss 서킷 열림, 스킵")
            return ("korean_rss", [])
        try:
            articles = await fetch_korean_rss_feeds()
            api_circuit_breaker.record_success("korean_rss")
            for a in articles:
                a["_query"] = None
            return ("korean_rss", articles)
        except Exception:
            api_circuit_breaker.record_failure("korean_rss")
            raise

    async def _fetch_yahoo_top():
        if not api_circuit_breaker.is_available("yahoo"):
            logger.info("yahoo 서킷 열림, 스킵")
            return ("yahoo", [])
        try:
            articles = await search_yahoo_finance_top(num=20)
            api_circuit_breaker.record_success("yahoo")
            for a in articles:
                a["_query"] = None
            return ("yahoo", articles)
        except Exception:
            api_circuit_breaker.record_failure("yahoo")
            raise

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
            try:
                from app.metrics import CRAWL_ERRORS
                CRAWL_ERRORS.labels(source="phase1").inc()
            except Exception:
                pass

    # Phase 2: Query-based search
    search_queries = _build_search_queries(db, sectors, stocks)
    if search_queries:
        logger.info(f"Crawling {len(search_queries)} queries (sample: {search_queries[:5]})")

        semaphore = asyncio.Semaphore(10)
        stock_code_by_name = {s.name: s.stock_code for s in stocks}

        async def _search_one(query: str):
            async with semaphore:
                crawlers = []
                source_names = []
                # 서킷 브레이커: 사용 가능한 크롤러만 실행
                if api_circuit_breaker.is_available("naver"):
                    crawlers.append(search_naver_news(query, display=10))
                    source_names.append("naver")
                if api_circuit_breaker.is_available("google"):
                    crawlers.append(search_google_news(query, num=10))
                    source_names.append("google")
                stock_code = stock_code_by_name.get(query)
                if stock_code and api_circuit_breaker.is_available("yahoo"):
                    crawlers.append(search_yahoo_stock_news(stock_code, num=5))
                    source_names.append("yahoo")

                if not crawlers:
                    return []

                results = await asyncio.gather(*crawlers, return_exceptions=True)
                articles = []
                for sn, result in zip(source_names, results):
                    if isinstance(result, list):
                        api_circuit_breaker.record_success(sn)
                        for a in result:
                            a["_query"] = query
                        articles.extend(result)
                        source_counts[sn] += len(result)
                    elif isinstance(result, Exception):
                        api_circuit_breaker.record_failure(sn)
                        logger.warning(f"[{sn}] error for '{query}': {result}")
                return articles

        tasks = [_search_one(q) for q in search_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                all_raw_articles.extend(result)

    logger.info(f"Raw articles by source: {source_counts}, total={len(all_raw_articles)}")

    # Prometheus 크롤링 메트릭 기록
    try:
        from app.metrics import CRAWL_ARTICLES
        for source_name, count in source_counts.items():
            if count > 0:
                CRAWL_ARTICLES.labels(source=source_name).inc(count)
    except Exception:
        pass

    # Deduplicate by URL + near-duplicate title detection (exact + fuzzy)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    # (bigrams, source) 튜플 리스트 — 적응형 임계값에 source 정보 활용
    seen_bigrams: list[tuple[set[str], str | None]] = []
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
    # DB 기존 제목의 bigram 인덱스 (source 불명이므로 None)
    for norm in existing_norm_titles:
        bg = _title_bigrams(norm)
        if bg:
            seen_bigrams.append((bg, None))

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

        # Fuzzy match dedup (적응형 임계값 기반 bigram Jaccard similarity)
        new_bigrams = _title_bigrams(norm_title)
        new_source = article.get("source")
        if new_bigrams and len(new_bigrams) >= 4:  # skip very short titles
            is_fuzzy_dup = False
            for existing_bg, existing_source in seen_bigrams:
                if _is_similar_title(
                    new_bigrams, existing_bg,
                    source_a=new_source, source_b=existing_source,
                ):
                    is_fuzzy_dup = True
                    break
            if is_fuzzy_dup:
                fuzzy_dedup_count += 1
                continue

        seen_titles.add(norm_title)
        if new_bigrams:
            seen_bigrams.append((new_bigrams, new_source))
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
        logger.info(f"No new articles after dedup/filter (unique_before_filter={pre_filter_count}).")
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
                f"(:t{j}, :sm{j}, :u{j}, :sr{j}, :pa{j}, :se{j}, :ct{j}, :ug{j})"
            )
            params[f"t{j}"] = ad["title"][:500]
            params[f"sm{j}"] = (ad.get("description") or "")[:2000]
            params[f"u{j}"] = ad["url"][:1000]
            params[f"sr{j}"] = ad["source"]
            params[f"pa{j}"] = ad.get("published_at")
            # 감성: AI 분류 결과 우선, 없으면 키워드 기반 6단계 분류
            params[f"se{j}"] = ad.get("_ai_sentiment") or classify_sentiment(ad["title"])  # noqa: F823
            params[f"ct{j}"] = ad.get("_content")
            # 긴급도 분류
            params[f"ug{j}"] = _classify_urgency(ad["title"])

        sql = sa_text(
            f"""INSERT INTO news_articles (title, summary, url, source, published_at, sentiment, content, urgency)
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

        # WebSocket 브로드캐스트: 새 뉴스 기사 알림
        if url_to_id:
            from app.event_bus import fire_event
            fire_event("news", {
                "type": "new_articles",
                "count": len(url_to_id),
                "article_ids": list(url_to_id.values())[:10],
            })

        # Step 2: Bulk insert relations via raw SQL (using pre-computed _relations)
        rel_values = []
        rel_params: dict = {}
        rel_idx = 0

        # 섹터/종목 이름 매핑 (relevance_score 계산용, 배치당 1회만 생성)
        sector_name_map = {s.id: s.name for s in sectors}
        stock_name_map = {s.id: s.name for s in stocks}

        for ad in batch:
            article_id = url_to_id.get(ad["url"])
            if not article_id:
                continue

            relations = ad.get("_relations", [])

            # 뉴스 전파: 직접 관계를 기반으로 관련 종목/섹터에 전파
            try:
                from app.services.relation_propagator import propagate_news

                article_sentiment = classify_sentiment(ad.get("title", ""))
                propagated = propagate_news(
                    db,
                    news_id=article_id,
                    article_sentiment=article_sentiment,
                    direct_relations=relations,
                )
                if propagated:
                    relations = relations + propagated
            except Exception as e:
                logger.warning(f"뉴스 전파 실패 (news_id={article_id}): {e}")

            seen_pairs: set[tuple] = set()
            for rel in relations:
                pair = (rel.get("stock_id"), rel.get("sector_id"))
                if pair in seen_pairs:
                    continue

                # 관련성 점수 계산 (소스 신뢰도 반영)
                stock_name = stock_name_map.get(rel.get("stock_id")) if rel.get("stock_id") else None
                sector_name = sector_name_map.get(rel.get("sector_id")) if rel.get("sector_id") else None
                is_ai = rel.get("match_type") == "ai_classified"
                score = calculate_relevance_score(
                    title=ad["title"],
                    description=ad.get("description"),
                    stock_name=stock_name,
                    sector_name=sector_name,
                    is_ai_classified=is_ai,
                    source=ad.get("source"),
                )

                # 전파된 간접 관계(propagated)는 엄격한 점수 필터(30),
                # 직접 분류된 관계(keyword/AI)는 완화된 기준(15) 적용
                is_propagated = rel.get("propagation_type") == "propagated"
                min_score = 30 if is_propagated else 15
                if score < min_score:
                    continue

                seen_pairs.add(pair)
                rel_values.append(
                    f"(:ni{rel_idx}, :si{rel_idx}, :se{rel_idx}, :mt{rel_idx}, :rv{rel_idx},"
                    f" :rs{rel_idx}, :pt{rel_idx}, :ir{rel_idx}, :sc{rel_idx})"
                )
                rel_params[f"ni{rel_idx}"] = article_id
                rel_params[f"si{rel_idx}"] = rel.get("stock_id")
                rel_params[f"se{rel_idx}"] = rel.get("sector_id")
                rel_params[f"mt{rel_idx}"] = rel.get("match_type", "keyword")
                rel_params[f"rv{rel_idx}"] = rel.get("relevance", "indirect")
                rel_params[f"rs{rel_idx}"] = rel.get("relation_sentiment")
                rel_params[f"pt{rel_idx}"] = rel.get("propagation_type", "direct")
                rel_params[f"ir{rel_idx}"] = rel.get("impact_reason")
                rel_params[f"sc{rel_idx}"] = score
                rel_idx += 1

            saved_count += 1

        if rel_values:
            rel_sql = sa_text(
                f"""INSERT INTO news_stock_relations
                (news_id, stock_id, sector_id, match_type, relevance,
                 relation_sentiment, propagation_type, impact_reason, relevance_score)
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


# ---------------------------------------------------------------------------
# 뉴스 커버리지 갭 감지
# ---------------------------------------------------------------------------
async def detect_coverage_gaps(db: Session) -> list[dict]:
    """최근 72시간 동안 뉴스가 없는 종목을 감지한다.

    Returns:
        list of {"stock_id": int, "stock_name": str, "sector_name": str,
                 "hours_since_last_news": float | None}
        hours_since_last_news가 None이면 해당 종목에 뉴스가 전혀 없음을 의미한다.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func as sa_func

    now = datetime.now(timezone.utc)
    gap_threshold = now - timedelta(hours=72)

    # 종목별 최근 뉴스 시점 조회
    # LEFT JOIN으로 뉴스가 없는 종목도 포함
    results = (
        db.query(
            Stock.id.label("stock_id"),
            Stock.name.label("stock_name"),
            Sector.name.label("sector_name"),
            sa_func.max(NewsArticle.published_at).label("last_news_at"),
        )
        .join(Sector, Stock.sector_id == Sector.id)
        .outerjoin(NewsStockRelation, NewsStockRelation.stock_id == Stock.id)
        .outerjoin(NewsArticle, NewsStockRelation.news_id == NewsArticle.id)
        .group_by(Stock.id, Stock.name, Sector.name)
        .all()
    )

    gaps: list[dict] = []
    for row in results:
        last_news_at = row.last_news_at
        hours_since: float | None = None

        if last_news_at is None:
            # 뉴스가 전혀 없는 종목
            hours_since = None
            gaps.append({
                "stock_id": row.stock_id,
                "stock_name": row.stock_name,
                "sector_name": row.sector_name,
                "hours_since_last_news": hours_since,
            })
        else:
            # timezone-naive datetime 처리
            if hasattr(last_news_at, "tzinfo") and last_news_at.tzinfo is None:
                last_news_at = last_news_at.replace(tzinfo=timezone.utc)
            if last_news_at < gap_threshold:
                hours_since = (now - last_news_at).total_seconds() / 3600
                gaps.append({
                    "stock_id": row.stock_id,
                    "stock_name": row.stock_name,
                    "sector_name": row.sector_name,
                    "hours_since_last_news": round(hours_since, 1),
                })

    if gaps:
        logger.info(
            f"커버리지 갭 감지: {len(gaps)}개 종목에 72시간 이상 뉴스 없음 "
            f"(뉴스 없는 종목: {sum(1 for g in gaps if g['hours_since_last_news'] is None)}건)"
        )

    return gaps
