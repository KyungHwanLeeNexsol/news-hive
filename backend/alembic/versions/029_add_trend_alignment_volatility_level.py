"""SPEC-AI-002 Phase 1: trend_alignment, volatility_level 컬럼 추가

fund_signals 테이블에 멀티 타임프레임 분석 결과(trend_alignment)와
시장 변동성 레벨(volatility_level)을 저장하는 NULLABLE 컬럼 추가.

Revision ID: 029
Revises: 028
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # REQ-AI-014: 멀티 타임프레임 추세 정렬 결과
    # 값: aligned / divergent / mixed
    op.add_column(
        "fund_signals",
        sa.Column("trend_alignment", sa.String(20), nullable=True),
    )
    # REQ-AI-020: 시장 변동성 레벨
    # 값: low / normal / high / extreme
    op.add_column(
        "fund_signals",
        sa.Column("volatility_level", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_signals", "volatility_level")
    op.drop_column("fund_signals", "trend_alignment")
