"""증권사 리포트 본문 content 컬럼 추가.

애널리스트 리포트 HTML 페이지에서 추출한 본문 텍스트를 저장한다.
키워드 AI 생성 시 제목+메타데이터만이 아닌 실제 투자포인트 내용을 활용하기 위함.

Revision ID: 042
Revises: 041
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op

# revision 식별자
revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """증권사 리포트 본문 컬럼 추가."""
    op.add_column(
        "securities_reports",
        sa.Column("content", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """증권사 리포트 본문 컬럼 제거."""
    op.drop_column("securities_reports", "content")
