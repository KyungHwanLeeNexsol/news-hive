"""add ai_summary to news_articles

Revision ID: 005
Revises: 004
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "news_articles",
        sa.Column("ai_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_articles", "ai_summary")
