"""VIP투자자문 추종 매매 테이블 생성 (SPEC-VIP-001).

vip_disclosures, vip_portfolios, vip_trades 3개 테이블을 신규 생성한다.
기존 virtual_portfolios, virtual_trades 테이블과 완전히 분리된 독립 스키마.

Revision ID: 043
Revises: 042
Create Date: 2026-04-08
"""

import sqlalchemy as sa
from alembic import op

# revision 식별자
revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """VIP 추종 매매 테이블 3종 생성."""

    # vip_disclosures: VIP투자자문 대량보유 공시 원본 저장
    op.create_table(
        "vip_disclosures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rcept_no", sa.String(20), nullable=False),
        sa.Column("corp_name", sa.String(100), nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=True),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("stake_pct", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("disclosure_type", sa.String(20), nullable=False),
        sa.Column("rcept_dt", sa.String(10), nullable=False),
        sa.Column("flr_nm", sa.String(200), nullable=False),
        sa.Column("report_nm", sa.String(500), nullable=True),
        sa.Column("raw_xml", sa.Text(), nullable=True),
        sa.Column("processed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rcept_no"),
    )
    op.create_index("ix_vip_disclosures_stock_code", "vip_disclosures", ["stock_code"])
    op.create_index("ix_vip_disclosures_rcept_dt", "vip_disclosures", ["rcept_dt"])
    op.create_index("ix_vip_disclosures_processed", "vip_disclosures", ["processed"])

    # vip_portfolios: VIP 추종 포트폴리오 (단일 인스턴스)
    op.create_table(
        "vip_portfolios",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("initial_capital", sa.Integer(), nullable=False),
        sa.Column("current_cash", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # vip_trades: VIP 추종 개별 매매 기록
    op.create_table(
        "vip_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("vip_disclosure_id", sa.Integer(), nullable=False),
        sa.Column("split_sequence", sa.Integer(), nullable=False),
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
        sa.Column("partial_sold", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_open", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["vip_portfolios.id"]),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"]),
        sa.ForeignKeyConstraint(["vip_disclosure_id"], ["vip_disclosures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vip_trades_portfolio_id", "vip_trades", ["portfolio_id"])
    op.create_index("ix_vip_trades_stock_id", "vip_trades", ["stock_id"])
    op.create_index("ix_vip_trades_is_open", "vip_trades", ["is_open"])
    op.create_index("ix_vip_trades_entry_date", "vip_trades", ["entry_date"])


def downgrade() -> None:
    """VIP 추종 매매 테이블 3종 제거."""
    op.drop_index("ix_vip_trades_entry_date", table_name="vip_trades")
    op.drop_index("ix_vip_trades_is_open", table_name="vip_trades")
    op.drop_index("ix_vip_trades_stock_id", table_name="vip_trades")
    op.drop_index("ix_vip_trades_portfolio_id", table_name="vip_trades")
    op.drop_table("vip_trades")
    op.drop_table("vip_portfolios")
    op.drop_index("ix_vip_disclosures_processed", table_name="vip_disclosures")
    op.drop_index("ix_vip_disclosures_rcept_dt", table_name="vip_disclosures")
    op.drop_index("ix_vip_disclosures_stock_code", table_name="vip_disclosures")
    op.drop_table("vip_disclosures")
