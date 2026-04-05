"""동적 TP/SL 컬럼 추가 — SPEC-AI-005

fund_signals 테이블에 tp_sl_method 컬럼 추가,
virtual_trades 테이블에 트레일링 스탑 관련 컬럼 추가.

Revision ID: 038
Revises: 037
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # fund_signals: TP/SL 산출 방식 컬럼 추가
    # 값: ai_provided | atr_dynamic | sector_default | legacy_fixed
    op.add_column(
        "fund_signals",
        sa.Column(
            "tp_sl_method",
            sa.String(20),
            nullable=True,
            server_default="legacy_fixed",
        ),
    )

    # virtual_trades: 트레일링 스탑 관련 컬럼 추가
    op.add_column(
        "virtual_trades",
        sa.Column(
            "trailing_stop_active",
            sa.Boolean,
            nullable=True,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "virtual_trades",
        sa.Column(
            "trailing_stop_price",
            sa.Integer,
            nullable=True,
        ),
    )
    op.add_column(
        "virtual_trades",
        sa.Column(
            "high_water_mark",
            sa.Integer,
            nullable=True,
        ),
    )


def downgrade() -> None:
    # virtual_trades 컬럼 제거
    op.drop_column("virtual_trades", "high_water_mark")
    op.drop_column("virtual_trades", "trailing_stop_price")
    op.drop_column("virtual_trades", "trailing_stop_active")

    # fund_signals 컬럼 제거
    op.drop_column("fund_signals", "tp_sl_method")
