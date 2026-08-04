"""SPEC-AI-101: surge_signal_forward_outcome 테이블 신설 — 신호가 기준 EOD 최대수익률 근사.

REQ-AI101-001: SurgeActualOutcome과 독립된 신규 additive 테이블. (trading_date,
fund_signal_id) UNIQUE로 평가 잡 재실행 시 upsert 멱등성을 보장한다(AC-101-002).

Revision ID: 073_surge_signal_forward_outcome
Revises: 072_surge_feature_snapshot
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "073_surge_signal_forward_outcome"
down_revision = "072_surge_feature_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_signal_forward_outcome",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column(
            "fund_signal_id",
            sa.Integer(),
            sa.ForeignKey("fund_signals.id"),
            nullable=False,
        ),
        sa.Column("price_at_signal", sa.Integer(), nullable=True),
        sa.Column("prev_close_price", sa.Integer(), nullable=True),
        sa.Column("day_high_price", sa.Integer(), nullable=True),
        sa.Column("forward_max_return_pct", sa.Float(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "trading_date", "fund_signal_id", name="uq_signal_forward_outcome_date_signal"
        ),
    )
    op.create_index(
        "ix_surge_signal_forward_outcome_trading_date",
        "surge_signal_forward_outcome",
        ["trading_date"],
    )
    op.create_index(
        "ix_surge_signal_forward_outcome_stock_code",
        "surge_signal_forward_outcome",
        ["stock_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_signal_forward_outcome_stock_code",
        table_name="surge_signal_forward_outcome",
    )
    op.drop_index(
        "ix_surge_signal_forward_outcome_trading_date",
        table_name="surge_signal_forward_outcome",
    )
    op.drop_table("surge_signal_forward_outcome")
