"""ensure coal symbol is COAL (not BTU or MTF=F)

DB에 BTU와 COAL이 동시에 존재하는 경우:
- UPDATE BTU→COAL은 unique violation 발생
- 대신 BTU 관련 레코드를 삭제 (COAL이 이미 대체)

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
    # BTU와 COAL이 둘 다 있으면 BTU 관련 데이터 삭제 (COAL이 대체)
    op.execute("""
        DELETE FROM sector_commodity_relations
        WHERE commodity_id = (
            SELECT id FROM commodities WHERE symbol = 'BTU' AND name_ko = '석탄'
        )
    """)
    op.execute("""
        DELETE FROM commodity_prices
        WHERE commodity_id = (
            SELECT id FROM commodities WHERE symbol = 'BTU' AND name_ko = '석탄'
        )
    """)
    op.execute("""
        DELETE FROM news_commodity_relations
        WHERE commodity_id = (
            SELECT id FROM commodities WHERE symbol = 'BTU' AND name_ko = '석탄'
        )
    """)
    op.execute("""
        DELETE FROM commodities
        WHERE symbol = 'BTU'
          AND name_ko = '석탄'
    """)

    # MTF=F가 남아있고 COAL이 없으면 UPDATE, 둘 다 있으면 MTF=F 삭제
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM commodities WHERE symbol = 'COAL') THEN
                DELETE FROM sector_commodity_relations
                WHERE commodity_id = (SELECT id FROM commodities WHERE symbol = 'MTF=F');
                DELETE FROM commodity_prices
                WHERE commodity_id = (SELECT id FROM commodities WHERE symbol = 'MTF=F');
                DELETE FROM commodities WHERE symbol = 'MTF=F';
            ELSE
                UPDATE commodities
                SET symbol = 'COAL', name_en = 'Coal (ETF proxy)', unit = 'USD'
                WHERE symbol = 'MTF=F';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    pass
