"""Add paper trading tables: virtual_portfolios, virtual_trades, portfolio_snapshots

Revision ID: 027
Revises: 026
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 가상 포트폴리오 테이블
    op.create_table(
        "virtual_portfolios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), default="기본 포트폴리오"),
        sa.Column("initial_capital", sa.Integer(), default=100_000_000),
        sa.Column("current_cash", sa.Integer(), default=100_000_000),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 가상 매매 기록 테이블
    op.create_table(
        "virtual_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("virtual_portfolios.id"), nullable=False),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("fund_signals.id"), nullable=False),
        # 진입 정보
        sa.Column("entry_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("entry_date", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # 청산 정보
        sa.Column("exit_price", sa.Integer(), nullable=True),
        sa.Column("exit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(30), nullable=True),
        # 성과
        sa.Column("pnl", sa.Integer(), nullable=True),
        sa.Column("return_pct", sa.Float(), nullable=True),
        # 시그널 조건
        sa.Column("target_price", sa.Integer(), nullable=True),
        sa.Column("stop_loss", sa.Integer(), nullable=True),
        sa.Column("is_open", sa.Boolean(), default=True),
    )

    # 일일 포트폴리오 스냅샷 테이블
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("virtual_portfolios.id"), nullable=False),
        sa.Column("snapshot_date", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # 자산 현황
        sa.Column("total_value", sa.Integer(), nullable=False),
        sa.Column("cash", sa.Integer(), nullable=False),
        sa.Column("positions_value", sa.Integer(), nullable=False),
        sa.Column("open_positions", sa.Integer(), default=0),
        # 성과 지표
        sa.Column("daily_return_pct", sa.Float(), nullable=True),
        sa.Column("cumulative_return_pct", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("virtual_trades")
    op.drop_table("virtual_portfolios")
