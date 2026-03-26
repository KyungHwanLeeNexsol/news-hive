"""Add commodity tracking tables (commodities, commodity_prices, sector_commodity_relations)

Revision ID: 017
Revises: 016
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commodities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name_ko", sa.String(length=50), nullable=False),
        sa.Column("name_en", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=5), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )

    op.create_table(
        "commodity_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("commodity_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "sector_commodity_relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sector_id", sa.Integer(), nullable=False),
        sa.Column("commodity_id", sa.Integer(), nullable=False),
        sa.Column("correlation_type", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["sector_id"], ["sectors.id"]),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # 가격 조회 성능을 위한 인덱스
    op.create_index("ix_commodity_prices_commodity_id", "commodity_prices", ["commodity_id"])
    op.create_index("ix_commodity_prices_recorded_at", "commodity_prices", ["recorded_at"])
    op.create_index("ix_sector_commodity_relations_sector_id", "sector_commodity_relations", ["sector_id"])


def downgrade() -> None:
    op.drop_index("ix_sector_commodity_relations_sector_id", table_name="sector_commodity_relations")
    op.drop_index("ix_commodity_prices_recorded_at", table_name="commodity_prices")
    op.drop_index("ix_commodity_prices_commodity_id", table_name="commodity_prices")
    op.drop_table("sector_commodity_relations")
    op.drop_table("commodity_prices")
    op.drop_table("commodities")
