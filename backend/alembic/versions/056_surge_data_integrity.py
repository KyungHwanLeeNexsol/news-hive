"""fund_signals 테이블에 originally_created_at 컬럼 추가.

시그널이 매일 재탐지(upsert)될 때 created_at은 오늘 날짜로 갱신되므로
최초 생성 시각을 보존하는 별도 컬럼이 필요하다.
originally_created_at은 한 번 기록 후 절대 변경되지 않는다.

Revision ID: 056_surge_data_integrity
Revises: 055_spec_ai_022_theme_groups
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "056_surge_data_integrity"
down_revision = "055_spec_ai_022_theme_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # originally_created_at 컬럼 추가 (nullable, 기본값 없음)
    op.add_column(
        "fund_signals",
        sa.Column("originally_created_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 기존 레코드 백필: originally_created_at이 NULL인 행은 created_at으로 초기화
    op.execute(
        "UPDATE fund_signals SET originally_created_at = created_at WHERE originally_created_at IS NULL"
    )

    # 인덱스 생성
    op.create_index(
        "ix_fund_signals_originally_created_at",
        "fund_signals",
        ["originally_created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fund_signals_originally_created_at", table_name="fund_signals")
    op.drop_column("fund_signals", "originally_created_at")
