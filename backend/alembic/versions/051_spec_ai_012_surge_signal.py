"""SPEC-AI-012: 급등 징후 탐지 시그널 메타데이터 컬럼 추가.

FundSignal 테이블에 surge_metadata (Text, nullable) 컬럼을 추가한다.
signal_type은 이미 String(30)이므로 스키마 변경 없이 "surge_candidate" 값을 사용 가능.

Revision ID: 051
Revises: 050
Create Date: 2026-05-07
"""

import sqlalchemy as sa
from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # surge_metadata: 급등 징후 탐지 앙상블 점수 및 탐지 근거 (JSON string)
    op.add_column(
        "fund_signals",
        sa.Column("surge_metadata", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_signals", "surge_metadata")
