"""Add market_cap column to stocks

Revision ID: 012
Revises: 011
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocks", sa.Column("market_cap", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("stocks", "market_cap")
