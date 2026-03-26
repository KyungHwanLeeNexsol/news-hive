"""Add news_commodity_relations table

Revision ID: 018
Revises: 017
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_commodity_relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("commodity_id", sa.Integer(), nullable=False),
        sa.Column("relevance", sa.String(20), nullable=False),
        sa.Column("impact_direction", sa.String(20), nullable=True),
        sa.Column("match_type", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["news_id"], ["news_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ncr_news_id", "news_commodity_relations", ["news_id"])
    op.create_index("ix_ncr_commodity_id", "news_commodity_relations", ["commodity_id"])


def downgrade() -> None:
    op.drop_index("ix_ncr_commodity_id", table_name="news_commodity_relations")
    op.drop_index("ix_ncr_news_id", table_name="news_commodity_relations")
    op.drop_table("news_commodity_relations")
