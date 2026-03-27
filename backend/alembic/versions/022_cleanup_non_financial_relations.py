"""cleanup non-financial article relations

정치/연예 관련 기사에 잘못 태깅된 news_stock_relations,
news_commodity_relations 레코드를 삭제한다.

Revision ID: 022
Revises: 021
Create Date: 2026-03-27
"""
from alembic import op

# revision identifiers
revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

# 비금융 기사 판별용 정규식 (PostgreSQL ~* 연산자)
_NON_FINANCIAL_REGEX = (
    "추경|추가경정|"
    "총선|대선|지선|보궐선거|지방선거|탄핵|국정감사|국정조사|"
    "아이돌|걸그룹|보이그룹|팬미팅|뮤직비디오|K팝|케이팝|케이-팝|컴백|"
    "연예인|연예계|예능프로|트로트|오디션"
)


def upgrade() -> None:
    # 비금융 기사에 달린 종목/섹터 관계 삭제
    op.execute(f"""
        DELETE FROM news_stock_relations
        WHERE news_id IN (
            SELECT id FROM news_articles
            WHERE title ~* '{_NON_FINANCIAL_REGEX}'
        )
    """)

    # 비금융 기사에 달린 원자재 관계 삭제
    op.execute(f"""
        DELETE FROM news_commodity_relations
        WHERE news_id IN (
            SELECT id FROM news_articles
            WHERE title ~* '{_NON_FINANCIAL_REGEX}'
        )
    """)


def downgrade() -> None:
    # 삭제된 데이터는 복구 불가 (재크롤링으로만 복원 가능)
    pass
