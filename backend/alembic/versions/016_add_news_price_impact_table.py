"""Add news_price_impact table for news-price reaction tracking

Revision ID: 016
Revises: 015
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_price_impact",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_id", sa.Integer(), sa.ForeignKey("news_stock_relations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("price_at_news", sa.Float(), nullable=False),
        sa.Column("price_after_1d", sa.Float(), nullable=True),
        sa.Column("price_after_5d", sa.Float(), nullable=True),
        sa.Column("return_1d_pct", sa.Float(), nullable=True),
        sa.Column("return_5d_pct", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("backfill_1d_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfill_5d_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_news_price_impact_stock_id", "news_price_impact", ["stock_id"])
    op.create_index("ix_news_price_impact_news_id", "news_price_impact", ["news_id"])
    op.create_index("ix_news_price_impact_captured_at", "news_price_impact", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_news_price_impact_captured_at")
    op.drop_index("ix_news_price_impact_news_id")
    op.drop_index("ix_news_price_impact_stock_id")
    op.drop_table("news_price_impact")
