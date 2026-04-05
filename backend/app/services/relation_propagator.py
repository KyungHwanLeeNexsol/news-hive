"""뉴스 전파 엔진 - 관련 종목/섹터로 뉴스를 전파한다.

직접 매칭된 뉴스를 stock_relations 테이블을 기반으로
관련 종목/섹터에 전파하며, 경쟁사의 경우 감성을 반전시킨다.
"""

import logging

from sqlalchemy.orm import Session

from app.models.stock_relation import StockRelation

logger = logging.getLogger(__name__)

# 전파 관계당 최대 생성 수
MAX_PROPAGATED_PER_NEWS = 20


def _invert_sentiment(sentiment: str) -> str:
    """경쟁사 관계에서 감성을 반전한다."""
    if sentiment == "positive":
        return "negative"
    elif sentiment == "negative":
        return "positive"
    return "neutral"


def _build_impact_reason(relation_type: str, source_name: str, target_name: str) -> str:
    """전파 사유 문자열을 생성한다."""
    templates = {
        "competitor": f"{source_name}의 경쟁사 {target_name}에 간접 영향 (경쟁 관계)",
        "equipment": f"{source_name}에 설비를 공급하는 {target_name}에 간접 영향 (설비 공급)",
        "material": f"{source_name}에 소재를 공급하는 {target_name}에 간접 영향 (소재 공급)",
        "supplier": f"{source_name}에 중간재를 공급하는 {target_name}에 간접 영향 (공급망)",
        "customer": f"{source_name}의 주요 고객인 {target_name}에 간접 영향 (고객 관계)",
    }
    return templates.get(relation_type, f"{source_name} 관련 {target_name}에 간접 영향")


def propagate_news(
    db: Session,
    news_id: int,
    article_sentiment: str,
    direct_relations: list[dict],
) -> list[dict]:
    """뉴스를 관련 종목/섹터로 전파한다.

    Args:
        db: SQLAlchemy 세션
        news_id: 뉴스 기사 ID
        article_sentiment: 기사 감성 ('positive' / 'negative' / 'neutral')
        direct_relations: 직접 매칭된 관계 목록
            [{"stock_id": int|None, "sector_id": int|None, "stock_name": str, "sector_name": str}, ...]

    Returns:
        전파된 관계 dict 목록 (news_crawler의 bulk INSERT에 추가할 데이터)
        [{"stock_id": int|None, "sector_id": int|None, "match_type": "propagated",
          "relevance": "indirect", "relation_sentiment": str,
          "propagation_type": "propagated", "impact_reason": str}, ...]
    """
    if not direct_relations:
        return []

    # 직접 타겟 수집 (중복 전파 방지용)
    direct_stock_ids: set[int] = set()
    direct_sector_ids: set[int] = set()
    # stock_id/sector_id -> name 매핑 (impact_reason용)
    stock_name_map: dict[int, str] = {}
    sector_name_map: dict[int, str] = {}

    for rel in direct_relations:
        sid = rel.get("stock_id")
        sec_id = rel.get("sector_id")
        if sid:
            direct_stock_ids.add(sid)
            if rel.get("stock_name"):
                stock_name_map[sid] = rel["stock_name"]
        if sec_id:
            direct_sector_ids.add(sec_id)
            if rel.get("sector_name"):
                sector_name_map[sec_id] = rel["sector_name"]

    if not direct_stock_ids and not direct_sector_ids:
        return []

    # stock_relations에서 직접 타겟과 관련된 관계 조회
    # target_stock_id 또는 target_sector_id가 직접 타겟에 포함되는 관계를 찾는다
    query = db.query(StockRelation)
    conditions = []

    if direct_stock_ids:
        conditions.append(StockRelation.target_stock_id.in_(list(direct_stock_ids)))
    if direct_sector_ids:
        conditions.append(StockRelation.target_sector_id.in_(list(direct_sector_ids)))

    if len(conditions) == 1:
        query = query.filter(conditions[0])
    else:
        from sqlalchemy import or_
        query = query.filter(or_(*conditions))

    stock_relations = query.all()

    if not stock_relations:
        return []

    # source 이름 조회를 위해 필요한 ID 수집
    source_stock_ids_to_fetch = set()
    source_sector_ids_to_fetch = set()
    for sr in stock_relations:
        if sr.source_stock_id and sr.source_stock_id not in stock_name_map:
            source_stock_ids_to_fetch.add(sr.source_stock_id)
        if sr.source_sector_id and sr.source_sector_id not in sector_name_map:
            source_sector_ids_to_fetch.add(sr.source_sector_id)

    # 이름 조회
    if source_stock_ids_to_fetch:
        from app.models.stock import Stock
        stocks = db.query(Stock.id, Stock.name).filter(
            Stock.id.in_(list(source_stock_ids_to_fetch))
        ).all()
        for s in stocks:
            stock_name_map[s.id] = s.name

    if source_sector_ids_to_fetch:
        from app.models.sector import Sector
        sectors = db.query(Sector.id, Sector.name).filter(
            Sector.id.in_(list(source_sector_ids_to_fetch))
        ).all()
        for s in sectors:
            sector_name_map[s.id] = s.name

    propagated: list[dict] = []
    seen_propagated: set[tuple] = set()

    for sr in stock_relations:
        source_stock_id = sr.source_stock_id
        source_sector_id = sr.source_sector_id

        # 이미 직접 타겟인 경우 스킵 (중복 방지)
        if source_stock_id and source_stock_id in direct_stock_ids:
            continue
        if source_sector_id and source_sector_id in direct_sector_ids:
            continue

        # 이미 전파된 동일 대상 스킵
        prop_key = (source_stock_id, source_sector_id)
        if prop_key in seen_propagated:
            continue
        seen_propagated.add(prop_key)

        # 감성 계산: 경쟁사는 반전, 나머지는 동일
        if sr.relation_type == "competitor":
            propagated_sentiment = _invert_sentiment(article_sentiment)
        else:
            propagated_sentiment = article_sentiment

        # impact_reason 생성
        # target = 뉴스가 직접 매칭된 종목/섹터
        target_name = ""
        if sr.target_stock_id:
            target_name = stock_name_map.get(sr.target_stock_id, f"종목#{sr.target_stock_id}")
        elif sr.target_sector_id:
            target_name = sector_name_map.get(sr.target_sector_id, f"섹터#{sr.target_sector_id}")

        # source = 전파될 종목/섹터
        source_name = ""
        if source_stock_id:
            source_name = stock_name_map.get(source_stock_id, f"종목#{source_stock_id}")
        elif source_sector_id:
            source_name = sector_name_map.get(source_sector_id, f"섹터#{source_sector_id}")

        impact_reason = _build_impact_reason(sr.relation_type, target_name, source_name)

        propagated.append({
            "stock_id": source_stock_id,
            "sector_id": source_sector_id,
            "match_type": "propagated",
            "relevance": "indirect",
            "relation_sentiment": propagated_sentiment,
            "propagation_type": "propagated",
            "impact_reason": impact_reason,
        })

        # 최대 전파 수 제한
        if len(propagated) >= MAX_PROPAGATED_PER_NEWS:
            logger.info(f"뉴스 {news_id}: 전파 관계 {MAX_PROPAGATED_PER_NEWS}건 도달, 추가 전파 중단")
            break

    if propagated:
        logger.debug(f"뉴스 {news_id}: {len(propagated)}건 전파 관계 생성")

    return propagated
