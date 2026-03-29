"""SPEC-NEWS-002 Phase 2: relevance_score, urgency, sentiment 6단계 확장

- news_stock_relations.relevance_score: 관련성 점수 (0-100) 추가
- news_stock_relations.relation_sentiment: String(10) -> String(20) 확장
- news_articles.sentiment: String(10) -> String(20) 확장
- news_articles.urgency: 긴급도 컬럼 추가

Revision ID: 028
Revises: 027
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) news_stock_relations.relevance_score 추가
    op.add_column(
        "news_stock_relations",
        sa.Column("relevance_score", sa.Integer(), nullable=True),
    )

    # 2) news_stock_relations.relation_sentiment: String(10) -> String(20)
    op.alter_column(
        "news_stock_relations",
        "relation_sentiment",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=True,
    )

    # 3) news_articles.sentiment: String(10) -> String(20)
    op.alter_column(
        "news_articles",
        "sentiment",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=True,
    )

    # 4) news_articles.urgency 추가
    op.add_column(
        "news_articles",
        sa.Column("urgency", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_articles", "urgency")

    op.alter_column(
        "news_articles",
        "sentiment",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=True,
    )

    op.alter_column(
        "news_stock_relations",
        "relation_sentiment",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=True,
    )

    op.drop_column("news_stock_relations", "relevance_score")
