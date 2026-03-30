"""이메일 인증 코드 컬럼 길이 확장 (6 → 64).

Revision ID: 034
Revises: 033
Create Date: 2026-03-30

링크 클릭 방식 전환으로 인증 코드를 URL-safe 토큰(43자)으로 변경.
"""

from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "email_verification_codes",
        "code",
        type_=sa.String(64),
        existing_type=sa.String(6),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "email_verification_codes",
        "code",
        type_=sa.String(6),
        existing_type=sa.String(64),
        nullable=False,
    )
