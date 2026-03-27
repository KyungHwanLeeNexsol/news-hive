"""ensure coal symbol is COAL (not BTU or MTF=F)

migration 023이 두 번 배포(MTF=F→BTU, BTU→COAL)로 인해
첫 번째 실행에서만 적용되어 BTU가 남아있을 수 있음.
이 migration이 BTU/MTF=F를 COAL로 확실히 통일.

Revision ID: 024
Revises: 023
Create Date: 2026-03-27
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BTU(Peabody) → COAL (Range Global Coal ETF)
    op.execute("""
        UPDATE commodities
        SET symbol = 'COAL',
            name_en = 'Coal (ETF proxy)',
            unit = 'USD'
        WHERE symbol = 'BTU'
          AND name_ko = '석탄'
    """)

    # 혹시 MTF=F가 남아있다면 COAL로 변경
    op.execute("""
        UPDATE commodities
        SET symbol = 'COAL',
            name_en = 'Coal (ETF proxy)',
            unit = 'USD'
        WHERE symbol = 'MTF=F'
    """)


def downgrade() -> None:
    pass
