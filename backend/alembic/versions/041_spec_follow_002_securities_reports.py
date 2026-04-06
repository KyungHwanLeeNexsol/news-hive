"""SPEC-FOLLOW-002: 증권사 리포트 수집 — securities_reports 테이블 생성.

Revision ID: 041
Revises: 040
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op

# revision 식별자
revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """증권사 리포트 테이블 생성."""

    op.create_table(
        "securities_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=True),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("securities_firm", sa.String(100), nullable=False),
        sa.Column("opinion", sa.String(50), nullable=True),
        sa.Column("target_price", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_securities_reports_url"),
    )

    # 인덱스 생성
    op.create_index(
        op.f("ix_securities_reports_stock_id"),
        "securities_reports",
        ["stock_id"],
    )
    op.create_index(
        op.f("ix_securities_reports_collected_at"),
        "securities_reports",
        ["collected_at"],
    )


def downgrade() -> None:
    """증권사 리포트 테이블 제거."""

    # 인덱스 제거
    op.drop_index(
        op.f("ix_securities_reports_collected_at"),
        table_name="securities_reports",
    )
    op.drop_index(
        op.f("ix_securities_reports_stock_id"),
        table_name="securities_reports",
    )

    # 테이블 제거
    op.drop_table("securities_reports")
