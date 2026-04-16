"""ks200_trades 테이블에 tranche 컬럼 추가 (분할 매수 차수).

1차 매수(tranche=1, 50%)와 2차 추가 매수(tranche=2, 나머지 50%)를 구분한다.

초기화 전략:
- 기존 오픈 포지션(is_open=true): tranche=2로 설정
  → 구 로직으로 전액(1천만원) 매수한 포지션이므로 "완성"으로 간주,
    추가 2차 매수가 발생하지 않도록 방지
- 기존 청산 포지션(is_open=false): tranche=1로 설정 (이력 참고용, 영향 없음)

Revision ID: 049
Revises: 048
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 컬럼 추가 (신규 레코드 기본값 1)
    op.add_column(
        "ks200_trades",
        sa.Column(
            "tranche",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    # 기존 오픈 포지션은 구 로직(전액 매수) 기반이므로 tranche=2로 표시
    # → 이후 신호 재발생 시 추가 매수가 일어나지 않도록 "완성" 처리
    op.execute(
        "UPDATE ks200_trades SET tranche = 2 WHERE is_open = true"
    )


def downgrade() -> None:
    op.drop_column("ks200_trades", "tranche")
