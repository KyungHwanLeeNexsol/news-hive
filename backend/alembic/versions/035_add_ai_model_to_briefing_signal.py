"""daily_briefings, fund_signals에 ai_model 컬럼 추가

Revision ID: 035_add_ai_model
Revises: 034_change_verification_code_to_token
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "035_add_ai_model"
down_revision = "034_change_verification_code_to_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_briefings",
        sa.Column("ai_model", sa.String(50), nullable=True),
    )
    op.add_column(
        "fund_signals",
        sa.Column("ai_model", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_signals", "ai_model")
    op.drop_column("daily_briefings", "ai_model")
