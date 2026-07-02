"""SPEC-AI-068: surge_universe_members 테이블 생성 + 평가지표/유형 라벨 컬럼 추가.

Revision ID: 065_surge_universe_members
Revises: 064_surge_universe_pool_history
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "065_surge_universe_members"
down_revision = "064_surge_universe_pool_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # REQ-001: 거래일별 스캔 유니버스 종목코드 영속화 테이블
    op.create_table(
        "surge_universe_members",
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column(
            "entry_pool",
            sa.String(length=10),
            nullable=False,
            comment="SPEC-AI-068 REQ-001: pool_a/pool_b/pool_c/existing",
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
        "ix_surge_universe_members_trading_date",
        "surge_universe_members",
        ["trading_date"],
        unique=False,
    )

    # REQ-002/003: SurgePredictionEvaluation 진단 지표 컬럼 4종
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "scannable_recall",
            sa.Float(),
            nullable=True,
            comment="SPEC-AI-068 REQ-002: 스캔 유니버스 교집합 기준 recall (알고리즘 품질)",
        ),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "coverage",
            sa.Float(),
            nullable=True,
            comment="SPEC-AI-068 REQ-003: 실제급등주 중 스캔 유니버스 비율 (유니버스 설계 품질)",
        ),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "scannable_actual_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
            comment="SPEC-AI-068 REQ-002/003: 실제급등주 ∩ 스캔 유니버스 종목 수",
        ),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "total_actual_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
            comment="SPEC-AI-068 REQ-003: 전체 실제급등주 종목 수",
        ),
    )

    # REQ-005: SurgeActualOutcome 급등 유형 라벨 컬럼
    op.add_column(
        "surge_actual_outcome",
        sa.Column(
            "surge_type",
            sa.String(length=20),
            nullable=True,
            comment="SPEC-AI-068 REQ-005: scannable(T-1 유니버스 포함) / non_scannable(미포함)",
        ),
    )


def downgrade() -> None:
    op.drop_column("surge_actual_outcome", "surge_type")

    op.drop_column("surge_prediction_evaluation", "total_actual_count")
    op.drop_column("surge_prediction_evaluation", "scannable_actual_count")
    op.drop_column("surge_prediction_evaluation", "coverage")
    op.drop_column("surge_prediction_evaluation", "scannable_recall")

    op.drop_index(
        "ix_surge_universe_members_trading_date",
        table_name="surge_universe_members",
    )
    op.drop_table("surge_universe_members")
