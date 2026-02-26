"""add sector_insights table

Revision ID: 008
Revises: 007
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sector_insights",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sector_id", sa.Integer(), sa.ForeignKey("sectors.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sector_insights_sector_id", "sector_insights", ["sector_id"])


def downgrade() -> None:
    op.drop_index("ix_sector_insights_sector_id", table_name="sector_insights")
    op.drop_table("sector_insights")
