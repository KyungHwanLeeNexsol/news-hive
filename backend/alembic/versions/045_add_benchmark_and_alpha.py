"""포트폴리오/시그널에 KOSPI 벤치마크 및 알파 컬럼 추가.

portfolio_snapshots: benchmark_value, benchmark_cumulative_return_pct, alpha_pct
fund_signals: benchmark_return_pct, alpha_pct

승률만 보고 매매 전략 품질을 오판하던 문제 교정 — 시장중립 알파 기반 평가 인프라.

Revision ID: 045
Revises: 044
Create Date: 2026-04-09
"""

import sqlalchemy as sa
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # portfolio_snapshots: 벤치마크/알파 3개 컬럼 추가
    with op.batch_alter_table("portfolio_snapshots") as batch:
        batch.add_column(
            sa.Column("benchmark_value", sa.Float(), nullable=True)
        )
        batch.add_column(
            sa.Column("benchmark_cumulative_return_pct", sa.Float(), nullable=True)
        )
        batch.add_column(
            sa.Column("alpha_pct", sa.Float(), nullable=True)
        )

    # fund_signals: 시장중립 판정용 2개 컬럼 추가
    with op.batch_alter_table("fund_signals") as batch:
        batch.add_column(
            sa.Column("benchmark_return_pct", sa.Float(), nullable=True)
        )
        batch.add_column(
            sa.Column("alpha_pct", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("fund_signals") as batch:
        batch.drop_column("alpha_pct")
        batch.drop_column("benchmark_return_pct")

    with op.batch_alter_table("portfolio_snapshots") as batch:
        batch.drop_column("alpha_pct")
        batch.drop_column("benchmark_cumulative_return_pct")
        batch.drop_column("benchmark_value")
