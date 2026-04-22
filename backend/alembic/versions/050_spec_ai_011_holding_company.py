"""stock_relations 지배구조 관계 타입 추가 (holding_company / subsidiary).

SPEC-AI-011: 지주사-자회사 구조 인식을 위해 holding_company 관계 타입 도입.
방향성 규약: target=지주사, source=자회사 (target에 뉴스 발생 시 source를 후보 풀 확장)

시드 데이터: HD현대(267250) → 4개 자회사
- HD한국조선해양 (009540)
- HD현대오일뱅크 (329180)
- 현대일렉트릭 (010620)
- HD현대미포 (010140)

Revision ID: 050
Revises: 049
Create Date: 2026-04-22
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None

_logger = logging.getLogger(__name__)

# SPEC-AI-011 시드 데이터 식별자 (downgrade 시 정확한 삭제를 위해 사용)
_SEED_REASON = "SPEC-AI-011: HD현대 지주사-자회사 관계"

# HD현대 지주사 코드 → 자회사 코드 목록
_HOLDING_CODE = "267250"
_SUBSIDIARY_CODES = ["009540", "329180", "010620", "010140"]


def upgrade() -> None:
    # 지주사 판별 쿼리 최적화 인덱스 (source_stock_id + relation_type 복합)
    op.create_index(
        "idx_stock_relations_source_type",
        "stock_relations",
        ["source_stock_id", "relation_type"],
    )

    conn = op.get_bind()

    parent_row = conn.execute(
        sa.text("SELECT id FROM stocks WHERE stock_code = :code LIMIT 1"),
        {"code": _HOLDING_CODE},
    ).fetchone()
    if not parent_row:
        raise RuntimeError(
            f"HD현대({_HOLDING_CODE}) 레코드를 찾을 수 없습니다. "
            "stocks 테이블에 해당 종목이 존재하는지 확인하세요."
        )
    parent_id = parent_row[0]

    for code in _SUBSIDIARY_CODES:
        sub_row = conn.execute(
            sa.text("SELECT id FROM stocks WHERE stock_code = :code LIMIT 1"),
            {"code": code},
        ).fetchone()
        if not sub_row:
            _logger.warning("자회사 %s 레코드를 찾을 수 없습니다. 해당 항목은 건너뜁니다.", code)
            continue
        sub_id = sub_row[0]

        # 중복 방지: 이미 존재하면 INSERT 스킵
        conn.execute(
            sa.text(
                """
                INSERT INTO stock_relations (
                    source_stock_id, target_stock_id, relation_type,
                    confidence, reason
                )
                SELECT :sub_id, :parent_id, 'holding_company', 1.0, :reason
                WHERE NOT EXISTS (
                    SELECT 1 FROM stock_relations
                    WHERE source_stock_id = :sub_id
                      AND target_stock_id = :parent_id
                      AND relation_type = 'holding_company'
                )
                """
            ),
            {"sub_id": sub_id, "parent_id": parent_id, "reason": _SEED_REASON},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # SPEC-AI-011 시드 데이터만 삭제 (다른 holding_company 행은 유지)
    conn.execute(
        sa.text(
            "DELETE FROM stock_relations WHERE reason = :reason",
        ),
        {"reason": _SEED_REASON},
    )

    op.drop_index("idx_stock_relations_source_type", table_name="stock_relations")
