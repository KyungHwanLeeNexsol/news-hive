"""방어 모드(defensive mode) 컬럼 추가.

Revision ID: 031
Revises: 030
Create Date: 2026-03-29

REQ-021: Max Drawdown Control - 포트폴리오 누적 손실 -10% 이하 시 방어 모드 전환
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "virtual_portfolios",
        sa.Column("is_defensive_mode", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "virtual_portfolios",
        sa.Column("defensive_mode_entered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("virtual_portfolios", "defensive_mode_entered_at")
    op.drop_column("virtual_portfolios", "is_defensive_mode")
