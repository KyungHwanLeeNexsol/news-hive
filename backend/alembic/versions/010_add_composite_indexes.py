"""add composite indexes for performance

Revision ID: 010
Revises: 009
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for news count queries (stock_id + news_id)
    op.create_index(
        "ix_news_stock_relations_stock_news",
        "news_stock_relations",
        ["stock_id", "news_id"],
    )

    # Index on stocks.stock_code for fast lookups
    op.create_index("ix_stocks_stock_code", "stocks", ["stock_code"])

    # Index on stocks.market for filtering
    op.create_index("ix_stocks_market", "stocks", ["market"])

    # Composite index for news ordering (published_at DESC, id)
    op.create_index(
        "ix_news_articles_published_at_id",
        "news_articles",
        ["published_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_articles_published_at_id", "news_articles")
    op.drop_index("ix_stocks_market", "stocks")
    op.drop_index("ix_stocks_stock_code", "stocks")
    op.drop_index("ix_news_stock_relations_stock_news", "news_stock_relations")
