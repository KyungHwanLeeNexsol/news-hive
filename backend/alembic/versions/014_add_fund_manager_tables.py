"""Add fund_signals, daily_briefings, portfolio_reports tables

Revision ID: 014
Revises: 013
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fund_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False),
        sa.Column("signal", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Integer(), nullable=True),
        sa.Column("stop_loss", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("news_summary", sa.Text(), nullable=True),
        sa.Column("financial_summary", sa.Text(), nullable=True),
        sa.Column("market_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fund_signals_stock_id", "fund_signals", ["stock_id"])
    op.create_index("ix_fund_signals_created_at", "fund_signals", ["created_at"])

    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False, unique=True),
        sa.Column("market_overview", sa.Text(), nullable=False),
        sa.Column("sector_highlights", sa.Text(), nullable=True),
        sa.Column("stock_picks", sa.Text(), nullable=True),
        sa.Column("risk_assessment", sa.Text(), nullable=True),
        sa.Column("strategy", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "portfolio_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_ids", sa.Text(), nullable=False),
        sa.Column("overall_assessment", sa.Text(), nullable=False),
        sa.Column("risk_analysis", sa.Text(), nullable=True),
        sa.Column("sector_balance", sa.Text(), nullable=True),
        sa.Column("rebalancing", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_reports")
    op.drop_table("daily_briefings")
    op.drop_index("ix_fund_signals_created_at", table_name="fund_signals")
    op.drop_index("ix_fund_signals_stock_id", table_name="fund_signals")
    op.drop_table("fund_signals")
