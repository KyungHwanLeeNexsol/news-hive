"""SPEC-AI-015: 시장 레짐 분류 테이블 생성.

market_regimes 테이블과 ENUM 타입을 생성한다.
날짜별 UNIQUE 제약조건으로 중복 레짐 분류를 방지한다.

Revision ID: 053_spec_ai_015_market_regime
Revises: 052_spec_ai_013_surge_portfolio
Create Date: 2026-05-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func

revision = "053_spec_ai_015_market_regime"
down_revision = "052_spec_ai_013_surge_portfolio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ENUM 타입 먼저 생성 (PostgreSQL 전용)
    market_regime_type = sa.Enum(
        "BULL", "BEAR", "SIDEWAYS",
        name="market_regime_type",
    )
    market_regime_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "market_regimes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column(
            "regime",
            sa.Enum("BULL", "BEAR", "SIDEWAYS", name="market_regime_type", create_type=False),
            nullable=False,
        ),
        sa.Column("kospi_5d_return", sa.Float, nullable=False),
        sa.Column("kospi_20d_ma_position", sa.Float, nullable=False),
        sa.Column("volatility_index", sa.Float, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )

    # 날짜 UNIQUE 제약조건
    op.create_unique_constraint(
        "uq_market_regimes_date",
        "market_regimes",
        ["date"],
    )
    # 날짜 인덱스
    op.create_index(
        "ix_market_regimes_date",
        "market_regimes",
        ["date"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_regimes_date", table_name="market_regimes")
    op.drop_constraint("uq_market_regimes_date", "market_regimes", type_="unique")
    op.drop_table("market_regimes")

    # ENUM 타입 제거 (PostgreSQL 전용)
    sa.Enum(name="market_regime_type").drop(op.get_bind(), checkfirst=True)
