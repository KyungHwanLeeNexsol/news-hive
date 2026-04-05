"""기존 virtual_trades의 null target_price/stop_loss를 기본값으로 보정

프로덕션에 target_price=null, stop_loss=null인 포지션 20건 존재.
entry_price 기준으로 기본값(+10%, -5%) 일괄 적용.

Revision ID: 037
Revises: 036
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # target_price가 null인 오픈 포지션: entry_price * 1.10
    op.execute(
        sa.text(
            """
            UPDATE virtual_trades
            SET target_price = CAST(entry_price * 1.10 AS INTEGER)
            WHERE target_price IS NULL AND is_open = true
            """
        )
    )
    # stop_loss가 null인 오픈 포지션: entry_price * 0.95
    op.execute(
        sa.text(
            """
            UPDATE virtual_trades
            SET stop_loss = CAST(entry_price * 0.95 AS INTEGER)
            WHERE stop_loss IS NULL AND is_open = true
            """
        )
    )


def downgrade() -> None:
    # 되돌리기: 보정된 값을 다시 null로 (정확한 롤백은 불가하므로 noop)
    pass
