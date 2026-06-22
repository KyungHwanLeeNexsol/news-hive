"""surge_prediction_evaluation 테이블에 per_stock_analysis_json 컬럼 추가 (SPEC-AI-060).

Revision ID: 061_surge_per_stock_analysis
Revises: 060_surge_auto_improvement_log
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "061_surge_per_stock_analysis"
down_revision = "060_surge_auto_improvement_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column("per_stock_analysis_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("surge_prediction_evaluation", "per_stock_analysis_json")
