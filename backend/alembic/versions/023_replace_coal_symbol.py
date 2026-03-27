"""replace MTF=F coal symbol with BTU

MTF=F (Newcastle Coal Futures)는 yfinance에서 데이터가 없음.
Peabody Energy(BTU)를 석탄 프록시로 교체.

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
    # commodities 테이블: MTF=F → BTU
    op.execute("""
        UPDATE commodities
        SET symbol = 'BTU',
            name_en = 'Coal (Peabody proxy)',
            unit = 'USD'
        WHERE symbol = 'MTF=F'
    """)

    # sector_commodity_relations: MTF=F commodity_id 참조는 CASCADE로 자동 업데이트됨
    # (symbol은 commodities PK가 아닌 일반 컬럼이므로 위 UPDATE로 충분)


def downgrade() -> None:
    op.execute("""
        UPDATE commodities
        SET symbol = 'MTF=F',
            name_en = 'Newcastle Coal',
            unit = 'metric ton'
        WHERE symbol = 'BTU'
          AND name_ko = '석탄'
    """)
