"""SPEC-AI-002 Phase 2: sector_momentum, sector_rotation_events 테이블 추가

섹터별 모멘텀 추적(REQ-AI-016)과 섹터 로테이션 감지(REQ-AI-017)를 위한 테이블 생성.

Revision ID: 030
Revises: 029
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 섹터 모멘텀 테이블 (REQ-AI-016)
    op.create_table(
        "sector_momentum",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sector_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("avg_return_5d", sa.Float(), nullable=True),
        sa.Column("volume_change_5d", sa.Float(), nullable=True),
        sa.Column("momentum_tag", sa.String(30), nullable=True),
        sa.Column("capital_inflow", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sector_id"], ["sectors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # 같은 섹터의 같은 날짜에 중복 레코드 방지
    op.create_index(
        "ix_sector_momentum_sector_date",
        "sector_momentum",
        ["sector_id", "date"],
        unique=True,
    )

    # 섹터 로테이션 이벤트 테이블 (REQ-AI-017)
    op.create_table(
        "sector_rotation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_sector_id", sa.Integer(), nullable=False),
        sa.Column("to_sector_id", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.ForeignKeyConstraint(["from_sector_id"], ["sectors.id"]),
        sa.ForeignKeyConstraint(["to_sector_id"], ["sectors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sector_rotation_detected_at",
        "sector_rotation_events",
        ["detected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sector_rotation_detected_at", table_name="sector_rotation_events")
    op.drop_table("sector_rotation_events")
    op.drop_index("ix_sector_momentum_sector_date", table_name="sector_momentum")
    op.drop_table("sector_momentum")
