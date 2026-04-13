"""KRX 공매도 잔고 테이블 생성.

공매도 잔고 증감은 기관의 하락 베팅 강도를 나타내는 선행 지표이다.
analyze_stock() 프롬프트에서 종목별 공매도 추이를 제공하여 AI 판단 정확도를 높인다.

Revision ID: 047
Revises: 046
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """KRX 공매도 잔고 테이블 생성."""
    op.create_table(
        "krx_short_selling",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("short_volume", sa.BigInteger(), nullable=True),       # 당일 공매도 거래량
        sa.Column("short_amount", sa.BigInteger(), nullable=True),       # 당일 공매도 거래대금 (원)
        sa.Column("short_balance", sa.BigInteger(), nullable=True),      # 공매도 잔고 (주수)
        sa.Column("short_balance_amount", sa.BigInteger(), nullable=True),  # 공매도 잔고 금액 (원)
        sa.Column("short_ratio", sa.Float(), nullable=True),             # 공매도 비율 (%)
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "trade_date", name="uq_krx_short_stock_date"),
    )

    op.create_index("ix_krx_short_selling_stock_id", "krx_short_selling", ["stock_id"])
    op.create_index("ix_krx_short_selling_trade_date", "krx_short_selling", ["trade_date"])


def downgrade() -> None:
    """KRX 공매도 잔고 테이블 제거."""
    op.drop_index("ix_krx_short_selling_trade_date", table_name="krx_short_selling")
    op.drop_index("ix_krx_short_selling_stock_id", table_name="krx_short_selling")
    op.drop_table("krx_short_selling")
