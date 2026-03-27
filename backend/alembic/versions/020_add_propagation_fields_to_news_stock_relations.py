"""add propagation fields to news_stock_relations

Revision ID: 020
Revises: 019
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_stock_relations",
        sa.Column("relation_sentiment", sa.String(10), nullable=True),
    )
    op.add_column(
        "news_stock_relations",
        sa.Column("propagation_type", sa.String(10), nullable=True, server_default="direct"),
    )
    op.add_column(
        "news_stock_relations",
        sa.Column("impact_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_stock_relations", "impact_reason")
    op.drop_column("news_stock_relations", "propagation_type")
    op.drop_column("news_stock_relations", "relation_sentiment")
