import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.database import get_db, SessionLocal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
async def list_news(limit: int = 30, offset: int = 0, q: str | None = None, db: Session = Depends(get_db)):
    base_query = db.query(NewsArticle)
    count_query = db.query(func.count(NewsArticle.id))

    if q:
        keyword_filter = or_(
            NewsArticle.title.ilike(f"%{q}%"),
            NewsArticle.summary.ilike(f"%{q}%"),
        )
        base_query = base_query.filter(keyword_filter)
        count_query = count_query.filter(keyword_filter)

    total = count_query.scalar()
    articles = (
        base_query
        .options(
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
        )
        .order_by(NewsArticle.published_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )
    data = format_articles(articles)
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"X-Total-Count": str(total), "Access-Control-Expose-Headers": "X-Total-Count"},
    )


@router.get("/{news_id}", response_model=NewsArticleResponse)
async def get_news_detail(news_id: int, db: Session = Depends(get_db)):
    article = (
        db.query(NewsArticle)
        .options(
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id == news_id)
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")

    # On-demand: if article has no sector relation, classify now
    has_sector = any(r.sector_id is not None for r in article.relations)
    if not has_sector:
        await _classify_article_on_demand(article, db)
        # Re-query with eager loading to pick up new relations
        article = (
            db.query(NewsArticle)
            .options(
                selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
                selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
            )
            .filter(NewsArticle.id == news_id)
            .first()
        )

    return format_articles([article])[0]


@router.post("/refresh")
async def refresh_news(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Quick synchronous reclassify (keyword-only, instant)
    reclassified = await _reclassify_unlinked(db)

    # Remove near-duplicate articles
    deduped = _deduplicate_existing(db)

    # Backfill sentiment for articles that don't have it yet
    _backfill_sentiment(db)

    # Backfill: translate existing English titles
    await _backfill_translate(db)

    # Launch crawl in background so the HTTP response returns immediately
    background_tasks.add_task(_run_crawl_background)

    total = db.query(NewsArticle).count()
    return {
        "message": f"Reclassified {reclassified}, deduped {deduped}. Crawl started in background.",
        "reclassified": reclassified,
        "deduped": deduped,
        "total": total,
    }


@router.post("/{news_id}/summary", response_model=NewsArticleResponse)
async def generate_summary(news_id: int, db: Session = Depends(get_db)):
    """Generate AI summary for a news article (lazy, cached in DB)."""
    article = (
        db.query(NewsArticle)
        .options(
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id == news_id)
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")

    if not article.ai_summary:
        from app.services.ai_classifier import generate_ai_summary

        relations_context = []
        for rel in article.relations:
            relations_context.append({
                "stock_name": rel.stock.name if rel.stock else None,
                "sector_name": rel.sector.name if rel.sector else None,
                "relevance": rel.relevance,
            })

        ai_summary = await generate_ai_summary(
            title=article.title,
            description=article.summary,
            relations=relations_context,
        )

        if ai_summary:
            article.ai_summary = ai_summary
            db.commit()
            db.refresh(article)

    return format_articles([article])[0]


@router.post("/{news_id}/content", response_model=NewsArticleResponse)
async def scrape_content(news_id: int, db: Session = Depends(get_db)):
    """Scrape article content on demand (lazy, cached in DB)."""
    article = (
        db.query(NewsArticle)
        .options(
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id == news_id)
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")

    if not article.content:
        from app.services.article_scraper import scrape_article_content

        # Resolve Google News redirect URL if needed
        url = article.url
        if "news.google.com" in url:
            url = await _resolve_google_url(url)
            if url != article.url:
                article.url = url
                db.flush()

        content = await scrape_article_content(url)
        if content:
            article.content = content
            db.commit()
            db.refresh(article)
        else:
            db.commit()  # save resolved URL even if scraping fails
    else:
        # Re-filter cached content to remove ads that slipped through
        from app.services.article_scraper import clean_cached_content
        cleaned = clean_cached_content(article.content)
        if cleaned != article.content:
            article.content = cleaned
            db.commit()
            db.refresh(article)

    return format_articles([article])[0]


async def _resolve_google_url(url: str) -> str:
    """Resolve a Google News redirect URL to the actual article URL."""
    import re
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.head(url, follow_redirects=True)
            final_url = str(resp.url)
            if "news.google.com" not in final_url:
                return final_url
            # Fallback: GET and parse HTML
            resp = await client.get(url, follow_redirects=True)
            final_url = str(resp.url)
            if "news.google.com" not in final_url:
                return final_url
            match = re.search(r'data-n-au="([^"]+)"', resp.text)
            if match:
                return match.group(1)
    except Exception:
        pass
    return url


async def _classify_article_on_demand(article: NewsArticle, db: Session) -> None:
    """Classify a single article on-demand when it has no sector tag."""
    from app.models.sector import Sector
    from app.models.stock import Stock
    from app.services.ai_classifier import KeywordIndex, classify_news

    sectors = db.query(Sector).all()
    stocks = db.query(Stock).all()
    index = KeywordIndex.build(sectors, stocks)

    try:
        classifications = classify_news(article.title, index)
        for cls in classifications:
            existing = db.query(NewsStockRelation).filter(
                NewsStockRelation.news_id == article.id,
                NewsStockRelation.stock_id == cls.get("stock_id"),
                NewsStockRelation.sector_id == cls.get("sector_id"),
            ).first()
            if existing:
                continue
            db.add(NewsStockRelation(
                news_id=article.id,
                stock_id=cls.get("stock_id"),
                sector_id=cls.get("sector_id"),
                match_type=cls.get("match_type", "keyword"),
                relevance=cls.get("relevance", "indirect"),
            ))
        db.commit()
    except Exception as e:
        logger.warning(f"On-demand classify failed for article {article.id}: {e}")


async def _run_crawl_background():
    """Run the crawl in background with a dedicated DB session."""
    from app.services.news_crawler import crawl_all_news

    db = SessionLocal()
    try:
        count = await crawl_all_news(db)
        logger.info(f"Background crawl completed: {count} new articles")
    except Exception as e:
        logger.error(f"Background crawl failed: {e}")
    finally:
        db.close()


def _backfill_sentiment(db: Session) -> None:
    """Backfill sentiment for existing articles that don't have it."""
    from app.services.ai_classifier import classify_sentiment

    articles = db.query(NewsArticle).filter(NewsArticle.sentiment.is_(None)).all()
    if not articles:
        return

    for article in articles:
        article.sentiment = classify_sentiment(article.title)

    db.commit()
    logger.info(f"Backfilled sentiment for {len(articles)} articles")


async def _reclassify_unlinked(db: Session) -> int:
    """Reclassify articles that have no sector tag.

    Targets two cases:
    1. Articles with zero relations (completely unlinked)
    2. Articles that only have stock relations but no sector relation

    Uses keyword matching first, then AI classification as fallback.
    """
    from sqlalchemy import and_, exists
    from app.models.sector import Sector
    from app.models.stock import Stock
    from app.services.ai_classifier import KeywordIndex, classify_news

    # Case 1: articles with zero relations
    articles_with_rels = db.query(NewsStockRelation.news_id).distinct()
    no_relations = (
        db.query(NewsArticle)
        .filter(NewsArticle.id.notin_(articles_with_rels))
        .all()
    )

    # Case 2: articles that have relations but none with a sector_id
    has_sector_rel = (
        db.query(NewsStockRelation.news_id)
        .filter(NewsStockRelation.sector_id.isnot(None))
        .distinct()
    )
    no_sector = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.id.in_(articles_with_rels),
            NewsArticle.id.notin_(has_sector_rel),
        )
        .all()
    )

    targets = no_relations + no_sector
    if not targets:
        return 0

    logger.info(
        f"Reclassifying {len(targets)} articles "
        f"({len(no_relations)} unlinked, {len(no_sector)} missing sector)"
    )

    sectors = db.query(Sector).all()
    stocks = db.query(Stock).all()
    index = KeywordIndex.build(sectors, stocks)
    count = 0

    for article in targets:
        try:
            classifications = classify_news(article.title, index)
            for cls in classifications:
                # Skip if this exact relation already exists
                existing = db.query(NewsStockRelation).filter(
                    NewsStockRelation.news_id == article.id,
                    NewsStockRelation.stock_id == cls.get("stock_id"),
                    NewsStockRelation.sector_id == cls.get("sector_id"),
                ).first()
                if existing:
                    continue
                db.add(NewsStockRelation(
                    news_id=article.id,
                    stock_id=cls.get("stock_id"),
                    sector_id=cls.get("sector_id"),
                    match_type=cls.get("match_type", "keyword"),
                    relevance=cls.get("relevance", "indirect"),
                ))
                count += 1
        except Exception as e:
            logger.warning(f"Reclassify failed for article {article.id}: {e}")

    if count > 0:
        db.commit()
    logger.info(f"Reclassified: added {count} relations")
    return count


def _deduplicate_existing(db: Session) -> int:
    """Remove near-duplicate articles from DB, keeping the one with most relations."""
    from sqlalchemy import text as sa_text
    from app.services.news_crawler import _normalize_title

    # Load article id, title, relation count without triggering ORM cascade
    rows = db.execute(sa_text(
        """SELECT a.id, a.title, a.published_at,
                  COALESCE(r.rel_count, 0) as rel_count
           FROM news_articles a
           LEFT JOIN (
               SELECT news_id, COUNT(*) as rel_count
               FROM news_stock_relations
               GROUP BY news_id
           ) r ON r.news_id = a.id
           ORDER BY a.published_at DESC NULLS LAST"""
    )).fetchall()

    # Group by normalized title
    groups: dict[str, list[tuple]] = {}
    for row in rows:
        norm = _normalize_title(row[1])
        if not norm:
            continue
        if norm not in groups:
            groups[norm] = []
        groups[norm].append(row)  # (id, title, published_at, rel_count)

    # Collect IDs to delete (keep the one with most relations per group)
    delete_ids: list[int] = []
    for norm_title, group in groups.items():
        if len(group) <= 1:
            continue
        # Sort: most relations first, then earliest published
        group.sort(key=lambda r: (-r[3], r[2] or ""))
        # Skip first (keep), delete the rest
        for dup in group[1:]:
            delete_ids.append(dup[0])

    if not delete_ids:
        return 0

    # Bulk delete via raw SQL to avoid ORM cascade warnings
    for i in range(0, len(delete_ids), 500):
        batch = delete_ids[i:i + 500]
        ids_str = ",".join(str(x) for x in batch)
        db.execute(sa_text(f"DELETE FROM news_stock_relations WHERE news_id IN ({ids_str})"))
        db.execute(sa_text(f"DELETE FROM news_articles WHERE id IN ({ids_str})"))

    db.commit()
    logger.info(f"Deduplicated: removed {len(delete_ids)} near-duplicate articles")
    return len(delete_ids)


async def _backfill_translate(db: Session) -> None:
    """Translate existing English-titled articles to Korean (title + summary)."""
    from app.services.ai_classifier import _is_english_title, translate_articles_batch

    articles = db.query(NewsArticle).filter(
        NewsArticle.source.in_(["us_news", "yahoo"]),
    ).all()

    # Filter to ones still in English
    en_articles = [a for a in articles if _is_english_title(a.title)]
    if not en_articles:
        return

    logger.info(f"Backfill translating {len(en_articles)} English articles")

    # Convert to dicts for translate_articles_batch
    article_dicts = [{"title": a.title, "description": a.summary or ""} for a in en_articles]
    await translate_articles_batch(article_dicts)

    # Apply translations back to DB
    translated = 0
    for article, d in zip(en_articles, article_dicts):
        if "original_title" in d:
            article.title = d["title"]
            if d.get("description"):
                article.summary = d["description"]
            translated += 1

    if translated:
        db.commit()
        logger.info(f"Backfill translated {translated} articles")
