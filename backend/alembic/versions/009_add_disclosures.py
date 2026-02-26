"""add disclosures table

Revision ID: 009
Revises: 008
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "disclosures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("corp_name", sa.String(100), nullable=False),
        sa.Column("stock_code", sa.String(6), nullable=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=True),
        sa.Column("report_name", sa.String(500), nullable=False),
        sa.Column("report_type", sa.String(50), nullable=True),
        sa.Column("rcept_no", sa.String(20), unique=True, nullable=False),
        sa.Column("rcept_dt", sa.String(10), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_disclosures_stock_id", "disclosures", ["stock_id"])
    op.create_index("ix_disclosures_rcept_dt", "disclosures", ["rcept_dt"])
    op.create_index("ix_disclosures_rcept_no", "disclosures", ["rcept_no"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_disclosures_rcept_no", table_name="disclosures")
    op.drop_index("ix_disclosures_rcept_dt", table_name="disclosures")
    op.drop_index("ix_disclosures_stock_id", table_name="disclosures")
    op.drop_table("disclosures")
