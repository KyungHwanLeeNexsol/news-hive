"""surge_prediction_evaluation 테이블에 predicted_codes_json 컬럼 추가 (SPEC-AI-092 REQ-AI092-002).

Revision ID: 069_surge_pred_eval_snapshot
Revises: 068_fund_signal_fk_set_null
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "069_surge_pred_eval_snapshot"
down_revision = "068_fund_signal_fk_set_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "surge_prediction_evaluation",
        sa.Column("predicted_codes_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("surge_prediction_evaluation", "predicted_codes_json")
