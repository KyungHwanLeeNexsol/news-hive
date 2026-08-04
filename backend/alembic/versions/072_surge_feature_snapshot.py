"""SPEC-AI-099: surge_feature_snapshots 테이블 신설 — 종목별·사이클별 불변 피처 스냅샷.

미래 모델링 SPEC이 필요로 할 데이터 인프라(피처 스토어)를 구축한다. 모델 학습/서빙은
본 SPEC의 범위가 아니다 — 데이터 캡처·조회 가능 상태까지만(REQ-AI099-001~006).

Revision ID: 072_surge_feature_snapshot
Revises: 071_surge_universe_pool_history_pool_d
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "072_surge_feature_snapshot"
down_revision = "071_surge_universe_pool_history_pool_d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_feature_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("theme_cluster_score", sa.Float(), nullable=False),
        sa.Column("combo_score", sa.Float(), nullable=False),
        sa.Column("best_disclosure_score", sa.Float(), nullable=False),
        sa.Column("legacy_score", sa.Float(), nullable=False),
        sa.Column("news_delayed_score", sa.Float(), nullable=False),
        sa.Column("volume_breakout_score", sa.Float(), nullable=False),
        sa.Column("momentum_continuation_score", sa.Float(), nullable=False),
        sa.Column("squeeze_score", sa.Float(), nullable=False),
        sa.Column("active_groups", sa.Integer(), nullable=False),
        sa.Column("surge_score", sa.Float(), nullable=False),
        sa.Column("price_5d_trend", sa.Float(), nullable=True),
        sa.Column("entry_pool", sa.String(length=20), nullable=False),
        sa.Column("active_detectors_json", sa.Text(), nullable=True),
        sa.Column(
            "market_cap_eok",
            sa.Integer(),
            nullable=True,
            comment="시가총액 (억원 단위)",
        ),
        sa.Column("price_at_signal", sa.Integer(), nullable=True),
        sa.Column("qualified", sa.Boolean(), nullable=False),
        sa.Column("outcome_trading_date", sa.Date(), nullable=True),
        sa.Column("outcome_change_rate", sa.Float(), nullable=True),
        sa.Column("outcome_was_surge", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_surge_feature_snapshots_stock_scanned",
        "surge_feature_snapshots",
        ["stock_code", "scanned_at"],
    )
    op.create_index(
        "ix_surge_feature_snapshots_outcome_trading_date",
        "surge_feature_snapshots",
        ["outcome_trading_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_feature_snapshots_outcome_trading_date",
        table_name="surge_feature_snapshots",
    )
    op.drop_index(
        "ix_surge_feature_snapshots_stock_scanned",
        table_name="surge_feature_snapshots",
    )
    op.drop_table("surge_feature_snapshots")
