"""SPEC-AI-022: 테마 그룹 테이블 생성 및 시드 데이터 삽입.

theme_groups: LG그룹, 삼성그룹, 현대차그룹, SK그룹 초기 데이터 포함.
stock_theme_groups: 종목-그룹 연결 테이블.

Revision ID: 055_spec_ai_022_theme_groups
Revises: 054_spec_ai_018_raw_regime
Create Date: 2026-05-29
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

revision = "055_spec_ai_022_theme_groups"
down_revision = "054_spec_ai_018_raw_regime"
branch_labels = None
depends_on = None

# 시드 데이터: {그룹명: (앵커종목코드, [멤버종목코드 목록])}
_THEME_GROUPS_SEED: dict[str, tuple[str, list[str]]] = {
    "LG그룹": (
        "066570",  # LG전자
        ["003550", "066570", "011070", "064400", "051910", "373220", "034220", "032640", "336370"],
    ),
    "삼성그룹": (
        "005930",  # 삼성전자
        ["005930", "006400", "018260", "009150", "207940", "028260", "032830"],
    ),
    "현대차그룹": (
        "005380",  # 현대차
        ["005380", "000270", "012330", "307950", "086280", "000720"],
    ),
    "SK그룹": (
        "000660",  # SK하이닉스
        ["000660", "017670", "096770", "402340", "034730", "011790"],
    ),
}


def upgrade() -> None:
    """theme_groups, stock_theme_groups 테이블 생성 및 시드 데이터 삽입."""
    # theme_groups 테이블 생성
    op.create_table(
        "theme_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "anchor_stock_id",
            sa.Integer(),
            sa.ForeignKey("stocks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_theme_groups_name"),
    )

    # stock_theme_groups 테이블 생성
    op.create_table(
        "stock_theme_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "stock_id",
            sa.Integer(),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "theme_group_id",
            sa.Integer(),
            sa.ForeignKey("theme_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "theme_group_id", name="uq_stock_theme_group"),
    )

    # 시드 데이터 삽입
    conn = op.get_bind()
    _insert_seed_data(conn)


def _insert_seed_data(conn) -> None:
    """시드 데이터를 삽입한다. 존재하지 않는 종목코드는 건너뜀."""
    for group_name, (anchor_code, member_codes) in _THEME_GROUPS_SEED.items():
        try:
            # 앵커 종목 조회
            anchor_row = conn.execute(
                text("SELECT id FROM stocks WHERE stock_code = :code"),
                {"code": anchor_code},
            ).fetchone()
            anchor_id = anchor_row[0] if anchor_row else None

            # 테마 그룹 삽입
            result = conn.execute(
                text(
                    "INSERT INTO theme_groups (name, anchor_stock_id) "
                    "VALUES (:name, :anchor_id) "
                    "RETURNING id"
                ),
                {"name": group_name, "anchor_id": anchor_id},
            )
            group_id = result.fetchone()[0]
            logger.info("[마이그레이션] 테마그룹 '%s' 생성 (id=%d, 앵커=%s)", group_name, group_id, anchor_code)

            # 멤버 종목 연결
            inserted = 0
            for code in member_codes:
                try:
                    stock_row = conn.execute(
                        text("SELECT id FROM stocks WHERE stock_code = :code"),
                        {"code": code},
                    ).fetchone()
                    if stock_row is None:
                        logger.debug("[마이그레이션] 종목코드 '%s' 미존재, 스킵", code)
                        continue

                    conn.execute(
                        text(
                            "INSERT INTO stock_theme_groups (stock_id, theme_group_id, weight) "
                            "VALUES (:stock_id, :group_id, 1.0) "
                            "ON CONFLICT (stock_id, theme_group_id) DO NOTHING"
                        ),
                        {"stock_id": stock_row[0], "group_id": group_id},
                    )
                    inserted += 1
                except Exception as e:
                    logger.warning("[마이그레이션] 종목 '%s' 연결 실패, 스킵: %s", code, e)

            logger.info("[마이그레이션] '%s' 그룹에 %d개 종목 연결 완료", group_name, inserted)

        except Exception as e:
            logger.error("[마이그레이션] 그룹 '%s' 시드 실패 (계속 진행): %s", group_name, e)


def downgrade() -> None:
    """stock_theme_groups, theme_groups 테이블 삭제."""
    op.drop_table("stock_theme_groups")
    op.drop_table("theme_groups")
