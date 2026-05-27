"""SPEC-AI-018: MarketRegime 테이블에 raw_regime 컬럼 추가.

히스테리시스 억제 전 원본 분류 레짐을 기록하는 nullable String 컬럼.
히스테리시스로 플립이 억제된 경우 분류된 레짐 값이 저장되고,
억제 없이 그대로 적용된 경우 NULL이 된다.

Revision ID: 054_spec_ai_018_raw_regime
Revises: 053_spec_ai_015_market_regime
Create Date: 2026-05-27
"""

import sqlalchemy as sa
from alembic import op

revision = "054_spec_ai_018_raw_regime"
down_revision = "053_spec_ai_015_market_regime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_regimes",
        sa.Column("raw_regime", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_regimes", "raw_regime")
