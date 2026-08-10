"""SPEC-AI-116: missing trigger shadow candidates table.

Revision ID: 077_surge_missing_trigger_shadow_candidate
Revises: 076_surge_gate_drop_observations
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "077_surge_missing_trigger_shadow_candidate"
down_revision = "076_surge_gate_drop_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_missing_trigger_shadow_candidates",
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column("detector_family", sa.String(length=40), nullable=False),
        sa.Column("horizon", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("source_pool", sa.String(length=60), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("risk_tags_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "trading_date", "stock_code", "detector_family", "horizon"
        ),
    )
    op.create_index(
        "ix_surge_missing_trigger_shadow_candidates_date_family",
        "surge_missing_trigger_shadow_candidates",
        ["trading_date", "detector_family"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_missing_trigger_shadow_candidates_date_family",
        table_name="surge_missing_trigger_shadow_candidates",
    )
    op.drop_table("surge_missing_trigger_shadow_candidates")
