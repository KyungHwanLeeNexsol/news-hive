"""종목토론방(종토방) 테이블 생성 (SPEC-AI-008).

종토방 게시글 개별 레코드와 시간별 집계 메트릭을 저장한다.
역발상 지표(과열 경보, 볼륨 급등) 산출의 기반 데이터로 활용된다.

Revision ID: 048
Revises: 047
Create Date: 2026-04-14
"""

import sqlalchemy as sa
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """종토방 게시글 및 시간별 집계 테이블 생성."""
    # ── stock_forum_posts ────────────────────────────────────────────────────
    op.create_table(
        "stock_forum_posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("content", sa.String(200), nullable=True),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column("post_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agree_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disagree_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sentiment", sa.String(20), nullable=False, server_default="neutral"),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"], ["stocks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_code", "post_date", "nickname", name="uq_forum_post"),
    )

    op.create_index("ix_forum_posts_stock_id", "stock_forum_posts", ["stock_id"])
    op.create_index("ix_forum_posts_collected_at", "stock_forum_posts", ["collected_at"])
    op.create_index("ix_forum_posts_stock_code", "stock_forum_posts", ["stock_code"])

    # ── stock_forum_hourly ───────────────────────────────────────────────────
    op.create_table(
        "stock_forum_hourly",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("aggregated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_posts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bullish_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bearish_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neutral_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bullish_ratio", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("comment_volume", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_7d_volume", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("volume_surge", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("overheating_alert", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(
            ["stock_id"], ["stocks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "aggregated_at", name="uq_forum_hourly"),
    )

    op.create_index("ix_forum_hourly_stock_id", "stock_forum_hourly", ["stock_id"])
    op.create_index("ix_forum_hourly_aggregated_at", "stock_forum_hourly", ["aggregated_at"])


def downgrade() -> None:
    """종토방 테이블 제거."""
    op.drop_index("ix_forum_hourly_aggregated_at", table_name="stock_forum_hourly")
    op.drop_index("ix_forum_hourly_stock_id", table_name="stock_forum_hourly")
    op.drop_table("stock_forum_hourly")

    op.drop_index("ix_forum_posts_stock_code", table_name="stock_forum_posts")
    op.drop_index("ix_forum_posts_collected_at", table_name="stock_forum_posts")
    op.drop_index("ix_forum_posts_stock_id", table_name="stock_forum_posts")
    op.drop_table("stock_forum_posts")
