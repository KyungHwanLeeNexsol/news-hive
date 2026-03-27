"""add stock_relations table

Revision ID: 019
Revises: 018
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_stock_id", sa.Integer(), nullable=True),
        sa.Column("source_sector_id", sa.Integer(), nullable=True),
        sa.Column("target_stock_id", sa.Integer(), nullable=True),
        sa.Column("target_sector_id", sa.Integer(), nullable=True),
        sa.Column("relation_type", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["source_stock_id"], ["stocks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_sector_id"], ["sectors.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_stock_id"], ["stocks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_sector_id"], ["sectors.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "source_stock_id IS NOT NULL OR source_sector_id IS NOT NULL",
            name="source_not_all_null",
        ),
        sa.CheckConstraint(
            "target_stock_id IS NOT NULL OR target_sector_id IS NOT NULL",
            name="target_not_all_null",
        ),
        sa.UniqueConstraint(
            "source_stock_id",
            "source_sector_id",
            "target_stock_id",
            "target_sector_id",
            "relation_type",
            name="uq_stock_relations_pair_type",
        ),
    )
    op.create_index(
        "idx_stock_relations_target_stock",
        "stock_relations",
        ["target_stock_id"],
    )
    op.create_index(
        "idx_stock_relations_target_sector",
        "stock_relations",
        ["target_sector_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_stock_relations_target_sector", table_name="stock_relations")
    op.drop_index("idx_stock_relations_target_stock", table_name="stock_relations")
    op.drop_table("stock_relations")
