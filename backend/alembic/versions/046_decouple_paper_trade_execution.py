"""페이퍼 트레이딩 체결 분리 — fund_signals.paper_executed 컬럼 추가.

신호 생성(08:30 KST)과 페이퍼 트레이딩 체결(09:05 KST)을 분리하기 위해
FundSignal에 paper_executed 플래그를 추가한다.
기존 미체결 시그널은 이미 즉시 체결되었으므로 True로 백필한다.

Revision ID: 046
Revises: 045
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # paper_executed 컬럼 추가 (기본값 false)
    op.add_column(
        "fund_signals",
        sa.Column(
            "paper_executed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    # 기존 레코드는 이미 즉시 체결 방식으로 처리되었으므로 True로 백필
    op.execute("UPDATE fund_signals SET paper_executed = TRUE")


def downgrade() -> None:
    op.drop_column("fund_signals", "paper_executed")
