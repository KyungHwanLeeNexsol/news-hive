"""replace MTF=F coal symbol with COAL ETF

MTF=F (Newcastle Coal Futures)는 yfinance에서 데이터가 없음.
Range Global Coal ETF(COAL)를 석탄 프록시로 교체.

Revision ID: 023
Revises: 022
Create Date: 2026-03-27
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # commodities 테이블: MTF=F → COAL
    op.execute("""
        UPDATE commodities
        SET symbol = 'COAL',
            name_en = 'Coal (ETF proxy)',
            unit = 'USD'
        WHERE symbol = 'MTF=F'
    """)

    # BTU가 이미 존재하면 COAL로 교체 (이전 배포에서 BTU가 추가된 경우)
    op.execute("""
        UPDATE commodities
        SET symbol = 'COAL',
            name_en = 'Coal (ETF proxy)'
        WHERE symbol = 'BTU'
          AND name_ko = '석탄'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE commodities
        SET symbol = 'MTF=F',
            name_en = 'Newcastle Coal',
            unit = 'metric ton'
        WHERE symbol = 'COAL'
          AND name_ko = '석탄'
    """)
