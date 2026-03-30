"""ML 피처 스냅샷 테이블 추가.

Revision ID: 032
Revises: 031
Create Date: 2026-03-29

REQ-025: ML Feature Engineering Pipeline
일별 ML 피처 스냅샷을 저장하는 테이블 생성.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_feature_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("avg_news_sentiment", sa.Float(), nullable=True),
        sa.Column("avg_technical", sa.Float(), nullable=True),
        sa.Column("avg_supply_demand", sa.Float(), nullable=True),
        sa.Column("avg_valuation", sa.Float(), nullable=True),
        sa.Column("trend_alignment_distribution", sa.Text(), nullable=True),
        sa.Column("volatility_level", sa.String(length=10), nullable=True),
        sa.Column("volume_spike_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("momentum_sector_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("momentum_sector_ids", sa.Text(), nullable=True),
        sa.Column("recent_5_accuracy", sa.Float(), nullable=True),
        sa.Column("total_signals_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date"),
    )


def downgrade() -> None:
    op.drop_table("ml_feature_snapshots")
