from sqlalchemy.orm import Session

from app.models.news import NewsArticle
from app.schemas.news import NewsArticleResponse, NewsRelationResponse


def format_articles(articles: list[NewsArticle]) -> list[NewsArticleResponse]:
    results = []
    for article in articles:
        relation_responses = []
        if article.relations:
            for rel in article.relations:
                relation_responses.append(
                    NewsRelationResponse(
                        stock_id=rel.stock_id,
                        stock_name=rel.stock.name if rel.stock else None,
                        sector_id=rel.sector_id,
                        sector_name=rel.sector.name if rel.sector else None,
                        match_type=rel.match_type,
                        relevance=rel.relevance,
                    )
                )
        results.append(
            NewsArticleResponse(
                id=article.id,
                title=article.title,
                summary=article.summary,
                url=article.url,
                source=article.source,
                published_at=article.published_at,
                collected_at=article.collected_at,
                relations=relation_responses,
            )
        )
    return results
