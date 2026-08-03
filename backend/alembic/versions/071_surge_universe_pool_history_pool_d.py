"""surge_universe_pool_history 테이블에 pool_d_count 컬럼 추가 (SPEC-AI-096 REQ-AI096-002).

build_scan_universe()가 계산하는 pool_counts["pool_d"]가 호출부(persist_pool_counts)에서
누락되어 Pool D(뉴스 언급 기반) 관측 이력이 여러 거래일에 걸쳐 축적되지 않던 갭을 해소한다.
기존 pool_a/b/c_count와 동일한 타입/제약(Integer, nullable=False, default=0)으로 통일한다.

Revision ID: 071_surge_universe_pool_history_pool_d
Revises: 070_surge_pred_eval_high_based
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "071_surge_universe_pool_history_pool_d"
down_revision = "070_surge_pred_eval_high_based"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "surge_universe_pool_history",
        sa.Column(
            "pool_d_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="SPEC-AI-096 REQ-AI096-002: Pool D (뉴스 언급 기반) 종목 수",
        ),
    )


def downgrade() -> None:
    op.drop_column("surge_universe_pool_history", "pool_d_count")
