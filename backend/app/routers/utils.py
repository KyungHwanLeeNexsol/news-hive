
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
                        relation_sentiment=rel.relation_sentiment,
                        propagation_type=rel.propagation_type,
                        impact_reason=rel.impact_reason,
                    )
                )
        results.append(
            NewsArticleResponse(
                id=article.id,
                title=article.title,
                summary=article.summary,
                ai_summary=article.ai_summary,
                content=article.content,
                url=article.url,
                source=article.source,
                sentiment=article.sentiment,
                published_at=article.published_at,
                collected_at=article.collected_at,
                relations=relation_responses,
            )
        )
    return results
