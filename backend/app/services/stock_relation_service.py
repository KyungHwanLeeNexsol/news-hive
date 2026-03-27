"""AI 기반 종목/섹터 간 관계 추론 서비스.

Phase A: 섹터 간 공급망/설비/소재/고객사 관계 추론 (1회 배치)
Phase B: 섹터 내 경쟁사 관계 추론 (섹터별 순차)
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.models.stock_relation import StockRelation

logger = logging.getLogger(__name__)


# --- 프롬프트 템플릿 ---

INTER_SECTOR_INFERENCE_PROMPT = """당신은 한국 주식 시장 전문가입니다.
아래 섹터 목록을 보고, 섹터 간 공급망·설비·소재·고객사 관계가 있는 쌍을 찾아주세요.

섹터 목록:
{sector_list}

관계 유형:
- equipment: target 섹터가 source 섹터에게 생산설비를 공급 (예: 반도체장비 → 반도체)
- material: target 섹터가 source 섹터에게 원자재/부품을 공급 (예: 2차전지소재 → 2차전지)
- supplier: target 섹터가 source 섹터에게 중간재를 공급 (예: 자동차부품 → 자동차)
- customer: target 섹터가 source 섹터의 주요 고객 (예: 반도체 → 반도체장비)

신뢰도 0.6 미만 또는 관계가 불확실한 경우 포함하지 마세요.

응답은 반드시 순수 JSON 배열만 반환하세요 (```json 마크다운 없이):
[
  {{
    "source_sector_id": <공급하는 섹터 ID>,
    "target_sector_id": <공급받는 섹터 ID>,
    "relation_type": "equipment",
    "confidence": 0.9,
    "reason": "반도체 생산 공정에 필요한 노광장비 등을 공급"
  }}
]
관계가 없으면 []을 반환하세요."""

COMPETITOR_INFERENCE_PROMPT = """당신은 한국 주식 시장 전문가입니다.
아래 섹터의 기업들 중 직접 경쟁 관계인 쌍을 찾아주세요.

섹터: {sector_name}
기업 목록:
{stock_list}

신뢰도 0.6 미만인 경우 포함하지 마세요.

응답은 반드시 순수 JSON 배열만 반환하세요 (```json 마크다운 없이):
[
  {{
    "stock_a_id": <종목 ID>,
    "stock_b_id": <종목 ID>,
    "confidence": 0.85,
    "reason": "두 기업 모두 동일 제품을 생산하는 직접 경쟁사"
  }}
]
경쟁 관계가 없으면 []을 반환하세요."""


def _parse_ai_json(text: str | None) -> list[dict]:
    """AI 응답에서 JSON 배열을 파싱한다. 마크다운 코드 블록 처리 포함."""
    if not text:
        return []

    cleaned = text.strip()

    # 마크다운 코드 블록 제거
    if cleaned.startswith("```"):
        # ```json ... ``` 또는 ``` ... ```
        lines = cleaned.split("\n")
        # 첫줄과 마지막줄 제거
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1])
        else:
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        return []
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"AI JSON 파싱 실패: {e}, text={cleaned[:200]}")
        return []


def should_run_inference(db: Session) -> bool:
    """stock_relations 테이블이 비어있으면 True 반환."""
    count = db.query(StockRelation.id).limit(1).count()
    return count == 0


async def run_full_inference(db: Session) -> dict[str, int]:
    """전체 AI 추론 실행 (Phase A + Phase B).

    Returns:
        {"inter_sector": N, "intra_sector": M} - 저장된 관계 수
    """
    stats = {"inter_sector": 0, "intra_sector": 0}

    # Phase A: 섹터 간 관계 추론
    try:
        inter_count = await _infer_inter_sector_relations(db)
        stats["inter_sector"] = inter_count
        logger.info(f"Phase A 완료: 섹터 간 {inter_count}건 관계 저장")
    except Exception as e:
        logger.error(f"Phase A (섹터 간 관계 추론) 실패: {e}")

    # Phase B: 섹터 내 경쟁사 추론
    try:
        intra_count = await _infer_intra_sector_competitors(db)
        stats["intra_sector"] = intra_count
        logger.info(f"Phase B 완료: 섹터 내 {intra_count}건 경쟁 관계 저장")
    except Exception as e:
        logger.error(f"Phase B (섹터 내 경쟁 추론) 실패: {e}")

    logger.info(f"관계 추론 완료: 섹터 간 {stats['inter_sector']}건, 섹터 내 {stats['intra_sector']}건")
    return stats


async def run_incremental_inference(db: Session) -> dict[str, int]:
    """증분 추론 - 최근 7일 내 추가된 섹터/종목만 처리."""
    stats = {"inter_sector": 0, "intra_sector": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # 최근 추가된 섹터가 있으면 섹터 간 관계 재추론
    new_sectors = db.query(Sector).filter(Sector.created_at >= cutoff).all()
    if new_sectors:
        logger.info(f"증분 추론: 신규 섹터 {len(new_sectors)}개 발견, 섹터 간 관계 재추론")
        try:
            inter_count = await _infer_inter_sector_relations(db)
            stats["inter_sector"] = inter_count
        except Exception as e:
            logger.error(f"증분 섹터 간 추론 실패: {e}")

    # 최근 추가된 종목의 섹터에 대해 경쟁 관계 추론
    new_stocks = db.query(Stock).filter(Stock.created_at >= cutoff).all()
    if new_stocks:
        sector_ids = set(s.sector_id for s in new_stocks)
        logger.info(f"증분 추론: 신규 종목 {len(new_stocks)}개 발견 ({len(sector_ids)}개 섹터)")
        for sector_id in sector_ids:
            try:
                count = await _infer_competitors_for_sector(db, sector_id)
                stats["intra_sector"] += count
            except Exception as e:
                logger.warning(f"섹터 {sector_id} 경쟁 추론 실패: {e}")
            await asyncio.sleep(1)

    return stats


async def _infer_inter_sector_relations(db: Session) -> int:
    """Phase A: DB의 전체 섹터 목록으로 섹터 간 관계를 AI 추론."""
    from app.services.ai_client import ask_ai

    sectors = db.query(Sector).all()
    if len(sectors) < 2:
        logger.info("섹터가 2개 미만이므로 섹터 간 추론 스킵")
        return 0

    sector_list = "\n".join(f"- {s.name} (id={s.id})" for s in sectors)
    prompt = INTER_SECTOR_INFERENCE_PROMPT.format(sector_list=sector_list)

    text = await ask_ai(prompt, max_retries=3)
    relations = _parse_ai_json(text)

    if not relations:
        logger.info("AI가 섹터 간 관계를 찾지 못했습니다")
        return 0

    # 유효 섹터 ID 세트
    valid_sector_ids = {s.id for s in sectors}
    saved = 0

    for rel in relations:
        source_id = rel.get("source_sector_id")
        target_id = rel.get("target_sector_id")
        rtype = rel.get("relation_type", "")
        confidence = rel.get("confidence", 0.0)
        reason = rel.get("reason")

        # 유효성 검증
        if not source_id or not target_id:
            continue
        if source_id not in valid_sector_ids or target_id not in valid_sector_ids:
            continue
        if source_id == target_id:
            continue
        if confidence < 0.6:
            continue
        if rtype not in ("equipment", "material", "supplier", "customer"):
            continue

        # ON CONFLICT DO NOTHING (UNIQUE 제약 활용)
        try:
            sql = sa_text(
                """INSERT INTO stock_relations
                   (source_sector_id, target_sector_id, relation_type, confidence, reason)
                   VALUES (:src, :tgt, :rt, :conf, :reason)
                   ON CONFLICT ON CONSTRAINT uq_stock_relations_pair_type DO NOTHING"""
            )
            result = db.execute(sql, {
                "src": source_id,
                "tgt": target_id,
                "rt": rtype,
                "conf": confidence,
                "reason": reason,
            })
            if result.rowcount > 0:
                saved += 1
        except Exception as e:
            logger.warning(f"섹터 간 관계 INSERT 실패: {e}")
            db.rollback()
            continue

    db.commit()
    return saved


async def _infer_intra_sector_competitors(db: Session) -> int:
    """Phase B: 각 섹터별로 종목 간 경쟁 관계를 AI 추론."""
    sectors = db.query(Sector).all()
    total_saved = 0

    for sector in sectors:
        try:
            count = await _infer_competitors_for_sector(db, sector.id)
            total_saved += count
        except Exception as e:
            logger.warning(f"섹터 '{sector.name}' (id={sector.id}) 경쟁 추론 실패 (스킵): {e}")

        # Rate limit 방지
        await asyncio.sleep(1)

    return total_saved


async def _infer_competitors_for_sector(db: Session, sector_id: int) -> int:
    """단일 섹터의 종목 간 경쟁 관계를 AI로 추론."""
    from app.services.ai_client import ask_ai

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        return 0

    stocks = db.query(Stock).filter(Stock.sector_id == sector_id).all()
    if len(stocks) < 2:
        return 0

    stock_list = "\n".join(f"- {s.name} (id={s.id})" for s in stocks)
    prompt = COMPETITOR_INFERENCE_PROMPT.format(
        sector_name=sector.name,
        stock_list=stock_list,
    )

    text = await ask_ai(prompt, max_retries=3)
    relations = _parse_ai_json(text)

    if not relations:
        return 0

    valid_stock_ids = {s.id for s in stocks}
    saved = 0

    for rel in relations:
        stock_a_id = rel.get("stock_a_id")
        stock_b_id = rel.get("stock_b_id")
        confidence = rel.get("confidence", 0.0)
        reason = rel.get("reason")

        # 유효성 검증
        if not stock_a_id or not stock_b_id:
            continue
        if stock_a_id not in valid_stock_ids or stock_b_id not in valid_stock_ids:
            continue
        if stock_a_id == stock_b_id:
            continue
        if confidence < 0.6:
            continue

        # 양방향 INSERT (A->B, B->A)
        for src, tgt in [(stock_a_id, stock_b_id), (stock_b_id, stock_a_id)]:
            try:
                sql = sa_text(
                    """INSERT INTO stock_relations
                       (source_stock_id, target_stock_id, relation_type, confidence, reason)
                       VALUES (:src, :tgt, 'competitor', :conf, :reason)
                       ON CONFLICT ON CONSTRAINT uq_stock_relations_pair_type DO NOTHING"""
                )
                result = db.execute(sql, {
                    "src": src,
                    "tgt": tgt,
                    "conf": confidence,
                    "reason": reason,
                })
                if result.rowcount > 0:
                    saved += 1
            except Exception as e:
                logger.warning(f"경쟁 관계 INSERT 실패 (src={src}, tgt={tgt}): {e}")
                db.rollback()
                continue

    db.commit()
    return saved
