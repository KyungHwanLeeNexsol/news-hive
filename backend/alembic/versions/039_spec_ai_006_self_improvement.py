"""SPEC-AI-006: 자기개선 피드백 루프 — 팩터 가중치 이력 및 개선 로그 테이블 추가.

prompt_versions 테이블에 prompt_template, generation_source 컬럼 추가.

Revision ID: 039
Revises: 038
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # factor_weight_history 테이블 생성
    op.create_table(
        "factor_weight_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("news_sentiment", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("technical", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("supply_demand", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("valuation", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("correlations", sa.String(500), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # improvement_logs 테이블 생성
    op.create_table(
        "improvement_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # prompt_versions: AI 자동 생성 프롬프트 내용 컬럼 추가
    op.add_column(
        "prompt_versions",
        sa.Column("prompt_template", sa.Text(), nullable=True),
    )
    op.add_column(
        "prompt_versions",
        sa.Column("generation_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # prompt_versions 컬럼 제거
    op.drop_column("prompt_versions", "generation_source")
    op.drop_column("prompt_versions", "prompt_template")

    # 테이블 제거
    op.drop_table("improvement_logs")
    op.drop_table("factor_weight_history")
