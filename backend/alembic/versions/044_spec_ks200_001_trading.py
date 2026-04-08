"""KOSPI 200 스토캐스틱+이격도 자동매매 테이블 생성 (SPEC-KS200-001).

ks200_portfolios, ks200_trades, ks200_signals 3개 테이블을 신규 생성한다.
기존 virtual_portfolios, vip_portfolios와 완전히 분리된 독립 스키마.

Revision ID: 044
Revises: 043
Create Date: 2026-04-08
"""

import sqlalchemy as sa
from alembic import op

# revision 식별자
revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ks200_portfolios: 단일 포트폴리오 인스턴스
    op.create_table(
        "ks200_portfolios",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default="KOSPI200 스토캐스틱+이격도"),
        sa.Column("initial_capital", sa.Integer(), nullable=False, server_default="100000000"),
        sa.Column("current_cash", sa.Integer(), nullable=False, server_default="100000000"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ks200_trades: 매매 기록
    op.create_table(
        "ks200_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("entry_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "entry_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("exit_price", sa.Integer(), nullable=True),
        sa.Column("exit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(30), nullable=True),
        sa.Column("pnl", sa.Integer(), nullable=True),
        sa.Column("return_pct", sa.Float(), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["ks200_portfolios.id"]),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ks200_trades_stock_code", "ks200_trades", ["stock_code"])

    # ks200_signals: 신호 기록
    op.create_table(
        "ks200_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("signal_type", sa.String(10), nullable=False),
        sa.Column("stoch_k", sa.Float(), nullable=False),
        sa.Column("disparity", sa.Float(), nullable=False),
        sa.Column("price_at_signal", sa.Integer(), nullable=False),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("signal_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ks200_signals_stock_code", "ks200_signals", ["stock_code"])


def downgrade() -> None:
    op.drop_index("ix_ks200_signals_stock_code", table_name="ks200_signals")
    op.drop_table("ks200_signals")
    op.drop_index("ix_ks200_trades_stock_code", table_name="ks200_trades")
    op.drop_table("ks200_trades")
    op.drop_table("ks200_portfolios")
