"""surge_actual_outcome 테이블 추가 (SPEC-AI-041).

장 마감 후 실제 급등주 결과(change_rate >= 10%)를 저장한다.
composite PK: (trading_date, stock_code).

Revision ID: 058_surge_actual_outcome
Revises: 057_surge_threshold_history
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "058_surge_actual_outcome"
down_revision = "057_surge_threshold_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_actual_outcome",
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("stock_name", sa.String(50), nullable=False),
        sa.Column("change_rate", sa.Float(), nullable=False),
        sa.Column("was_surge", sa.Boolean(), nullable=False),
        sa.Column("high_change_rate", sa.Float(), nullable=True),
        sa.Column("market", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("trading_date", "stock_code"),
    )
    op.create_index(
        "ix_surge_actual_outcome_trading_date",
        "surge_actual_outcome",
        ["trading_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_surge_actual_outcome_trading_date", table_name="surge_actual_outcome")
    op.drop_table("surge_actual_outcome")
