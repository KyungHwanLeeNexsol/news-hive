"""SPEC-FOLLOW-001: 기업 팔로잉 시스템 — stock_followings, stock_keywords, keyword_notifications 테이블 생성.

Revision ID: 040
Revises: 039
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op

# revision 식별자
revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """팔로잉 시스템 테이블 및 users 컬럼 추가."""

    # stock_followings 테이블 생성
    op.create_table(
        "stock_followings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "stock_id", name="uq_stock_following"),
    )
    op.create_index(op.f("ix_stock_followings_user_id"), "stock_followings", ["user_id"])

    # stock_keywords 테이블 생성
    op.create_table(
        "stock_keywords",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("following_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["following_id"], ["stock_followings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("following_id", "keyword", name="uq_stock_keyword"),
    )
    op.create_index(op.f("ix_stock_keywords_following_id"), "stock_keywords", ["following_id"])

    # keyword_notifications 테이블 생성
    op.create_table(
        "keyword_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("content_title", sa.String(500), nullable=False),
        sa.Column("content_url", sa.String(1000), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyword_id"], ["stock_keywords.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "content_type", "content_id", name="uq_keyword_notification"),
    )
    op.create_index(op.f("ix_keyword_notifications_user_id"), "keyword_notifications", ["user_id"])

    # users 테이블에 telegram_chat_id 컬럼 추가
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(50), nullable=True))


def downgrade() -> None:
    """팔로잉 시스템 테이블 및 users 컬럼 제거."""

    # users 컬럼 제거
    op.drop_column("users", "telegram_chat_id")

    # 인덱스 및 테이블 제거 (의존성 역순)
    op.drop_index(op.f("ix_keyword_notifications_user_id"), table_name="keyword_notifications")
    op.drop_table("keyword_notifications")

    op.drop_index(op.f("ix_stock_keywords_following_id"), table_name="stock_keywords")
    op.drop_table("stock_keywords")

    op.drop_index(op.f("ix_stock_followings_user_id"), table_name="stock_followings")
    op.drop_table("stock_followings")
