"""add performance indexes

Revision ID: 004
Revises: 003
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Speed up news lookups by sector/stock
    op.create_index("ix_news_stock_relations_sector_id", "news_stock_relations", ["sector_id"])
    op.create_index("ix_news_stock_relations_stock_id", "news_stock_relations", ["stock_id"])
    op.create_index("ix_news_stock_relations_news_id", "news_stock_relations", ["news_id"])

    # Speed up news ordering by published_at
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])

    # Speed up stock lookups by sector
    op.create_index("ix_stocks_sector_id", "stocks", ["sector_id"])


def downgrade() -> None:
    op.drop_index("ix_stocks_sector_id", "stocks")
    op.drop_index("ix_news_articles_published_at", "news_articles")
    op.drop_index("ix_news_stock_relations_news_id", "news_stock_relations")
    op.drop_index("ix_news_stock_relations_stock_id", "news_stock_relations")
    op.drop_index("ix_news_stock_relations_sector_id", "news_stock_relations")
