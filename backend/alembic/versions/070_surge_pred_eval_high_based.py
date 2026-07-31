"""surge_prediction_evaluation 테이블에 고가 기반 병렬 평가지표 컬럼 추가 (SPEC-AI-095 REQ-AI095-003).

Revision ID: 070_surge_pred_eval_high_based
Revises: 069_surge_pred_eval_snapshot
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "070_surge_pred_eval_high_based"
down_revision = "069_surge_pred_eval_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column("high_based_recall", sa.Float(), nullable=True),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column("high_based_precision", sa.Float(), nullable=True),
    )
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column("high_based_coverage", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("surge_prediction_evaluation", "high_based_coverage")
    op.drop_column("surge_prediction_evaluation", "high_based_precision")
    op.drop_column("surge_prediction_evaluation", "high_based_recall")
