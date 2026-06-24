"""crash_risk_alerts 테이블 생성 (SPEC-AI-064).

Revision ID: 062_crash_risk_alerts
Revises: 061_surge_per_stock_analysis
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "062_crash_risk_alerts"
down_revision = "061_surge_per_stock_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crash_risk_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_type", sa.String(length=20), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("triggered_signals", sa.Text(), nullable=True),
        sa.Column("kospi_change_pct", sa.Float(), nullable=True),
        sa.Column("telegram_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("crash_risk_alerts")
