"""add market column to stocks

Revision ID: 007
Revises: 006
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stocks",
        sa.Column("market", sa.String(10), nullable=True),
    )
    op.create_index("ix_stocks_market", "stocks", ["market"])


def downgrade() -> None:
    op.drop_index("ix_stocks_market", table_name="stocks")
    op.drop_column("stocks", "market")
