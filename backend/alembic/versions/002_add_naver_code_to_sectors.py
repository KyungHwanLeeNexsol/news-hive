"""add naver_code to sectors

Revision ID: 002
Revises: 001
Create Date: 2026-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sectors", sa.Column("naver_code", sa.String(length=10), nullable=True))
    op.create_unique_constraint("uq_sectors_naver_code", "sectors", ["naver_code"])


def downgrade() -> None:
    op.drop_constraint("uq_sectors_naver_code", "sectors", type_="unique")
    op.drop_column("sectors", "naver_code")
