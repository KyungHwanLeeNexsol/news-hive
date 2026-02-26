"""add composite indexes for performance

Revision ID: 010
Revises: 009
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_not_exists(name: str, table: str, columns: list[str]):
    """Create index only if it doesn't already exist."""
    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
        {"name": name},
    ).fetchone()
    if not result:
        op.create_index(name, table, columns)


def upgrade() -> None:
    _create_index_if_not_exists(
        "ix_news_stock_relations_stock_news",
        "news_stock_relations",
        ["stock_id", "news_id"],
    )
    _create_index_if_not_exists("ix_stocks_stock_code", "stocks", ["stock_code"])
    _create_index_if_not_exists("ix_stocks_market", "stocks", ["market"])
    _create_index_if_not_exists(
        "ix_news_articles_published_at_id",
        "news_articles",
        ["published_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_articles_published_at_id", "news_articles")
    op.drop_index("ix_stocks_market", "stocks")
    op.drop_index("ix_stocks_stock_code", "stocks")
    op.drop_index("ix_news_stock_relations_stock_news", "news_stock_relations")
