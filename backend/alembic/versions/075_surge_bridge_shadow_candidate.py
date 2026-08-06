"""SPEC-AI-105 REQ-AI105-002: surge_bridge_shadow_candidates 테이블 생성.

bridge shadow 계측(`scan_universe_bridge_shadow_enabled`, 기본 비활성)이 마스터
스위치만 override한 config 사본으로 `generate_scan_universe_bridge_candidates()`를
재호출해 산출한 pool_a/pool_c 한정 후보를 거래일별 replace semantics로 저장한다.
`SurgeUniverseMember`(065_surge_universe_members) 스키마 관례를 그대로 따른다.

Revision ID: 075_surge_bridge_shadow_candidate
Revises: 074_surge_horizon_shadow_observation
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "075_surge_bridge_shadow_candidate"
down_revision = "074_surge_horizon_shadow_observation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_bridge_shadow_candidates",
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column(
            "entry_pool",
            sa.String(length=10),
            nullable=False,
            comment="SPEC-AI-105 REQ-AI105-002: pool_a/pool_c 한정 (pool_b 하드코딩 배제)",
        ),
        sa.Column(
            "bridge_score",
            sa.Float(),
            nullable=False,
            comment="SPEC-AI-105 REQ-AI105-001: generate_scan_universe_bridge_candidates() 재사용 점수",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("trading_date", "stock_code"),
    )
    op.create_index(
        "ix_surge_bridge_shadow_candidates_trading_date",
        "surge_bridge_shadow_candidates",
        ["trading_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_bridge_shadow_candidates_trading_date",
        table_name="surge_bridge_shadow_candidates",
    )
    op.drop_table("surge_bridge_shadow_candidates")
