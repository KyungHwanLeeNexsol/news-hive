"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 테이블 생성.

surge_portfolios, surge_trades 테이블 및 인덱스를 생성한다.
마이그레이션 적용 시 초기 포트폴리오 레코드(id=1, 5,000,000원) 자동 생성.

Revision ID: 052_spec_ai_013_surge_portfolio
Revises: 051
Create Date: 2026-05-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func

revision = "052_spec_ai_013_surge_portfolio"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_portfolios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "initial_capital",
            sa.Numeric(15, 2),
            nullable=False,
            server_default="5000000",
        ),
        sa.Column(
            "current_cash",
            sa.Numeric(15, 2),
            nullable=False,
            server_default="5000000",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )

    op.create_table(
        "surge_trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id",
            sa.Integer,
            sa.ForeignKey("surge_portfolios.id"),
            nullable=False,
        ),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("stock_name", sa.String(100), nullable=False),
        sa.Column(
            "signal_id",
            sa.Integer,
            sa.ForeignKey("fund_signals.id"),
            nullable=True,
        ),
        sa.Column("entry_price", sa.Numeric(15, 2), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("exit_date", sa.Date, nullable=True),
        sa.Column("exit_price", sa.Numeric(15, 2), nullable=True),
        sa.Column(
            "is_open",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.Column("surge_probability_score", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )

    op.create_index("idx_surge_trades_open", "surge_trades", ["is_open"])
    op.create_index("idx_surge_trades_stock_code", "surge_trades", ["stock_code"])
    op.create_index("idx_surge_trades_entry_date", "surge_trades", ["entry_date"])

    # 초기 포트폴리오 레코드 생성 (id=1, initial_capital=5,000,000)
    op.execute(
        "INSERT INTO surge_portfolios (initial_capital, current_cash) "
        "VALUES (5000000, 5000000)"
    )


def downgrade() -> None:
    op.drop_index("idx_surge_trades_entry_date", table_name="surge_trades")
    op.drop_index("idx_surge_trades_stock_code", table_name="surge_trades")
    op.drop_index("idx_surge_trades_open", table_name="surge_trades")
    op.drop_table("surge_trades")
    op.drop_table("surge_portfolios")
