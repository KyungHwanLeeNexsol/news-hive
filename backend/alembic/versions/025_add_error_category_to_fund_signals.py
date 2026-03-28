"""Add error_category column to fund_signals

Revision ID: 025
Revises: 024
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fund_signals", sa.Column("error_category", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("fund_signals", "error_category")
