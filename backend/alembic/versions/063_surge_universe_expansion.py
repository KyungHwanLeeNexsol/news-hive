"""SPEC-AI-065: 스캔 유니버스 확장 + z-score 기준선 테이블 생성.

Revision ID: 063_surge_universe_expansion
Revises: 062_crash_risk_alerts
Create Date: 2026-06-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "063_surge_universe_expansion"
down_revision = "062_crash_risk_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # REQ-1: stock_signal_baselines 테이블 — (stock_code, detector_name) 롤링 통계
    op.create_table(
        "stock_signal_baselines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("detector_name", sa.String(length=50), nullable=False),
        sa.Column("rolling_mean", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("rolling_m2", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_code", "detector_name", name="uq_stock_detector_baseline"
        ),
    )
    op.create_index(
        "ix_stock_signal_baselines_stock_code",
        "stock_signal_baselines",
        ["stock_code"],
        unique=False,
    )
    op.create_index(
        "ix_stock_signal_baselines_detector_name",
        "stock_signal_baselines",
        ["detector_name"],
        unique=False,
    )

    # REQ-5: surge_prediction_evaluation에 스캔 유니버스 크기 및 풀별 집계 컬럼 추가
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "scan_universe_size",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: 당일 평가 대상 총 스캔 유니버스 크기",
        ),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "pool_a_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: Pool A (DART 공시 당일) 종목 수",
        ),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "pool_b_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: Pool B (거래량 200%+ 당일) 종목 수",
        ),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column(
            "pool_c_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: Pool C (등락률 5~15% 당일) 종목 수",
        ),
    )


def downgrade() -> None:
    op.drop_column("surge_prediction_evaluation", "pool_c_count")
    op.drop_column("surge_prediction_evaluation", "pool_b_count")
    op.drop_column("surge_prediction_evaluation", "pool_a_count")
    op.drop_column("surge_prediction_evaluation", "scan_universe_size")

    op.drop_index(
        "ix_stock_signal_baselines_detector_name",
        table_name="stock_signal_baselines",
    )
    op.drop_index(
        "ix_stock_signal_baselines_stock_code",
        table_name="stock_signal_baselines",
    )
    op.drop_table("stock_signal_baselines")
