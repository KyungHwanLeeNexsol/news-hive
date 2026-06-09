"""surge_prediction_evaluation 테이블 추가 (SPEC-AI-041).

T-1 급등 시그널과 T 당일 실제 급등주를 비교하여
precision/recall/f1 및 미스 분석 결과를 저장한다.

Revision ID: 059_surge_prediction_evaluation
Revises: 058_surge_actual_outcome
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "059_surge_prediction_evaluation"
down_revision = "058_surge_actual_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_prediction_evaluation",
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("predicted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_surge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("true_positive", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_positive", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_negative", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column("miss_analysis_json", sa.Text(), nullable=True),
        sa.Column("improvements_applied_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("evaluation_date"),
    )


def downgrade() -> None:
    op.drop_table("surge_prediction_evaluation")
