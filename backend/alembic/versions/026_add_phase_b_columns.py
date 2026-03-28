"""Add Phase B columns: fast verify, factor scoring, prompt versioning, A/B testing

Revision ID: 026
Revises: 025
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # REQ-AI-005: 장중 빠른 검증
    op.add_column("fund_signals", sa.Column("price_after_6h", sa.Integer(), nullable=True))
    op.add_column("fund_signals", sa.Column("price_after_12h", sa.Integer(), nullable=True))
    op.add_column("fund_signals", sa.Column("early_warning", sa.Boolean(), nullable=True))

    # REQ-AI-006: 다중 팩터 스코어링
    op.add_column("fund_signals", sa.Column("factor_scores", sa.Text(), nullable=True))
    op.add_column("fund_signals", sa.Column("composite_score", sa.Float(), nullable=True))

    # REQ-AI-008: A/B 테스트
    op.add_column("fund_signals", sa.Column("prompt_version", sa.String(50), nullable=True))

    # prompt_versions 테이블
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_name", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("template_key", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("is_control", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # prompt_ab_results 테이블
    op.create_table(
        "prompt_ab_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_a", sa.String(50), nullable=False),
        sa.Column("version_b", sa.String(50), nullable=False),
        sa.Column("total_trials", sa.Integer(), default=0),
        sa.Column("accuracy_a", sa.Float(), nullable=True),
        sa.Column("accuracy_b", sa.Float(), nullable=True),
        sa.Column("p_value", sa.Float(), nullable=True),
        sa.Column("winner", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("prompt_ab_results")
    op.drop_table("prompt_versions")
    op.drop_column("fund_signals", "prompt_version")
    op.drop_column("fund_signals", "composite_score")
    op.drop_column("fund_signals", "factor_scores")
    op.drop_column("fund_signals", "early_warning")
    op.drop_column("fund_signals", "price_after_12h")
    op.drop_column("fund_signals", "price_after_6h")
