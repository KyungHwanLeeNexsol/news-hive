"""SPEC-AI-101: surge_horizon_shadow_observation 테이블 신설 — 섀도우 비교 결과 영속화.

REQ-AI101-004: run_horizon_shadow_comparison()이 매 스코어링 사이클마다 무조건 1행씩
적재한다(added/removed가 모두 빈 경우 포함, D3). REQ-AI101-005 전환 게이트 3요건
판정 함수(check_horizon_transition_readiness)의 집계 대상이다.

Revision ID: 074_surge_horizon_shadow_observation
Revises: 073_surge_signal_forward_outcome
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "074_surge_horizon_shadow_observation"
down_revision = "073_surge_signal_forward_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_horizon_shadow_observation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("market_regime", sa.String(length=20), nullable=False),
        sa.Column("existing_qualified_count", sa.Integer(), nullable=False),
        sa.Column("shadow_qualified_count", sa.Integer(), nullable=False),
        sa.Column("added_codes_json", sa.Text(), nullable=True),
        sa.Column("removed_codes_json", sa.Text(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_surge_horizon_shadow_observation_observed_at",
        "surge_horizon_shadow_observation",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_horizon_shadow_observation_observed_at",
        table_name="surge_horizon_shadow_observation",
    )
    op.drop_table("surge_horizon_shadow_observation")
