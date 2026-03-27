"""add commodity performance indexes

Revision ID: 021
Revises: 020
Create Date: 2026-03-27
"""
from alembic import op

# revision identifiers
revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # news_commodity_relations 쿼리 성능 개선 인덱스
    op.create_index(
        "ix_news_commodity_relations_news_id",
        "news_commodity_relations",
        ["news_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_news_commodity_relations_commodity_id",
        "news_commodity_relations",
        ["commodity_id"],
        if_not_exists=True,
    )
    # commodity_prices 최신가격 조회 성능 개선
    op.create_index(
        "ix_commodity_prices_commodity_id_recorded_at",
        "commodity_prices",
        ["commodity_id", "recorded_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_commodity_prices_commodity_id_recorded_at", table_name="commodity_prices")
    op.drop_index("ix_news_commodity_relations_commodity_id", table_name="news_commodity_relations")
    op.drop_index("ix_news_commodity_relations_news_id", table_name="news_commodity_relations")
