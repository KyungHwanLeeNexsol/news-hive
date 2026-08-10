"""SPEC-AI-115: surge gate/drop observation table.

Revision ID: 076_surge_gate_drop_observations
Revises: 075_surge_bridge_shadow_candidate
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "076_surge_gate_drop_observations"
down_revision = "075_surge_bridge_shadow_candidate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_gate_drop_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column("gate_name", sa.String(length=60), nullable=False),
        sa.Column("detector_set_json", sa.Text(), nullable=False),
        sa.Column("score_before_drop", sa.Float(), nullable=True),
        sa.Column("reason_metadata_json", sa.Text(), nullable=True),
        sa.Column("market_regime", sa.String(length=20), nullable=True),
        sa.Column("shadow_profile", sa.String(length=80), nullable=True),
        sa.Column("shadow_candidate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_surge_gate_drop_observations_trading_date",
        "surge_gate_drop_observations",
        ["trading_date"],
    )
    op.create_index(
        "ix_surge_gate_drop_observations_stock_code",
        "surge_gate_drop_observations",
        ["stock_code"],
    )
    op.create_index(
        "ix_surge_gate_drop_observations_gate_name",
        "surge_gate_drop_observations",
        ["gate_name"],
    )
    op.create_index(
        "ix_surge_gate_drop_observations_shadow_profile",
        "surge_gate_drop_observations",
        ["shadow_profile"],
    )
    op.create_index(
        "ix_surge_gate_drop_observations_observed_at",
        "surge_gate_drop_observations",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_gate_drop_observations_observed_at",
        table_name="surge_gate_drop_observations",
    )
    op.drop_index(
        "ix_surge_gate_drop_observations_shadow_profile",
        table_name="surge_gate_drop_observations",
    )
    op.drop_index(
        "ix_surge_gate_drop_observations_gate_name",
        table_name="surge_gate_drop_observations",
    )
    op.drop_index(
        "ix_surge_gate_drop_observations_stock_code",
        table_name="surge_gate_drop_observations",
    )
    op.drop_index(
        "ix_surge_gate_drop_observations_trading_date",
        table_name="surge_gate_drop_observations",
    )
    op.drop_table("surge_gate_drop_observations")
