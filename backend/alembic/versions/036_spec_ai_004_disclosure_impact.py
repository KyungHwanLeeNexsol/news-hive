"""disclosures 테이블에 공시 충격 스코어링 컬럼 추가, fund_signals에 signal_type/disclosure_id 추가

Revision ID: 036
Revises: 035
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # disclosures 테이블에 공시 충격 스코어링 컬럼 추가
    op.add_column(
        "disclosures",
        sa.Column("impact_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "disclosures",
        sa.Column("baseline_price", sa.Integer(), nullable=True),
    )
    op.add_column(
        "disclosures",
        sa.Column("reflected_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "disclosures",
        sa.Column("unreflected_gap", sa.Float(), nullable=True),
    )
    op.add_column(
        "disclosures",
        sa.Column(
            "ripple_checked",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "disclosures",
        sa.Column("disclosed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # fund_signals 테이블에 공시 기반 시그널 추적 컬럼 추가
    op.add_column(
        "fund_signals",
        sa.Column("signal_type", sa.String(30), nullable=True),
    )
    op.add_column(
        "fund_signals",
        sa.Column(
            "disclosure_id",
            sa.Integer(),
            sa.ForeignKey("disclosures.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("fund_signals", "disclosure_id")
    op.drop_column("fund_signals", "signal_type")
    op.drop_column("disclosures", "disclosed_at")
    op.drop_column("disclosures", "ripple_checked")
    op.drop_column("disclosures", "unreflected_gap")
    op.drop_column("disclosures", "reflected_pct")
    op.drop_column("disclosures", "baseline_price")
    op.drop_column("disclosures", "impact_score")
