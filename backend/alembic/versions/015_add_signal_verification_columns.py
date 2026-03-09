"""Add signal verification columns to fund_signals

Revision ID: 015
Revises: 014
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fund_signals", sa.Column("price_at_signal", sa.Integer(), nullable=True))
    op.add_column("fund_signals", sa.Column("price_after_1d", sa.Integer(), nullable=True))
    op.add_column("fund_signals", sa.Column("price_after_3d", sa.Integer(), nullable=True))
    op.add_column("fund_signals", sa.Column("price_after_5d", sa.Integer(), nullable=True))
    op.add_column("fund_signals", sa.Column("is_correct", sa.Boolean(), nullable=True))
    op.add_column("fund_signals", sa.Column("return_pct", sa.Float(), nullable=True))
    op.add_column("fund_signals", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fund_signals", "verified_at")
    op.drop_column("fund_signals", "return_pct")
    op.drop_column("fund_signals", "is_correct")
    op.drop_column("fund_signals", "price_after_5d")
    op.drop_column("fund_signals", "price_after_3d")
    op.drop_column("fund_signals", "price_after_1d")
    op.drop_column("fund_signals", "price_at_signal")
