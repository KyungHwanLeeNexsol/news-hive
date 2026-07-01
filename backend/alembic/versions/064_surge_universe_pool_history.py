"""SPEC-AI-065 REQ-5: 스캔 유니버스 pool 집계 히스토리 테이블 생성.

Revision ID: 064_surge_universe_pool_history
Revises: 063_surge_universe_expansion
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "064_surge_universe_pool_history"
down_revision = "063_surge_universe_expansion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_universe_pool_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "pool_a_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: Pool A (DART 공시 당일) 종목 수",
        ),
        sa.Column(
            "pool_b_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: Pool B (거래량 200%+ 당일) 종목 수",
        ),
        sa.Column(
            "pool_c_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: Pool C (등락률 5%+ 당일) 종목 수",
        ),
        sa.Column(
            "scan_universe_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="SPEC-AI-065 REQ-5: 최종 스캔 유니버스 크기 (max_scan_universe 적용 후)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_surge_universe_pool_history_date"),
    )
    op.create_index(
        "ix_surge_universe_pool_history_date",
        "surge_universe_pool_history",
        ["date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_universe_pool_history_date",
        table_name="surge_universe_pool_history",
    )
    op.drop_table("surge_universe_pool_history")
