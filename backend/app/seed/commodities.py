"""원자재 초기 데이터 시드 + 섹터-원자재 관계 매핑."""

import logging

from sqlalchemy.orm import Session

from app.models.commodity import Commodity, SectorCommodityRelation
from app.models.sector import Sector

logger = logging.getLogger(__name__)

# 원자재 마스터 데이터 (yfinance 심볼 기준)
COMMODITIES_DATA = [
    {"symbol": "CL=F", "name_ko": "WTI 원유", "name_en": "WTI Crude Oil", "category": "energy", "unit": "barrel"},
    {"symbol": "BZ=F", "name_ko": "브렌트유", "name_en": "Brent Crude Oil", "category": "energy", "unit": "barrel"},
    {"symbol": "NG=F", "name_ko": "천연가스", "name_en": "Natural Gas", "category": "energy", "unit": "MMBtu"},
    {"symbol": "GC=F", "name_ko": "금", "name_en": "Gold", "category": "metal", "unit": "oz"},
    {"symbol": "SI=F", "name_ko": "은", "name_en": "Silver", "category": "metal", "unit": "oz"},
    {"symbol": "HG=F", "name_ko": "구리", "name_en": "Copper", "category": "metal", "unit": "lb"},
    {"symbol": "ALI=F", "name_ko": "알루미늄", "name_en": "Aluminum", "category": "metal", "unit": "metric ton"},
    {"symbol": "ZC=F", "name_ko": "옥수수", "name_en": "Corn", "category": "agriculture", "unit": "bushel"},
    {"symbol": "ZW=F", "name_ko": "밀", "name_en": "Wheat", "category": "agriculture", "unit": "bushel"},
    {"symbol": "ZS=F", "name_ko": "대두", "name_en": "Soybean", "category": "agriculture", "unit": "bushel"},
    # 에너지 — 석탄 (Range Global Coal ETF 프록시; 선물 yfinance 미지원)
    {"symbol": "COAL", "name_ko": "석탄", "name_en": "Coal (ETF proxy)", "category": "energy", "unit": "USD"},
    # 금속 — 리튬/희토류 (ETF 대용; 선물 미상장)
    {"symbol": "LIT", "name_ko": "리튬", "name_en": "Lithium (ETF proxy)", "category": "metal", "unit": "USD"},
    {"symbol": "REMX", "name_ko": "희토류", "name_en": "Rare Earth (ETF proxy)", "category": "metal", "unit": "USD"},
]

# 섹터명 → 관련 원자재 매핑 (sector name은 seed/sectors.py _SNAPSHOT 기준)
# correlation_type: positive(가격 상승 시 호재), negative(가격 상승 시 악재), neutral
SECTOR_COMMODITY_RELATIONS = [
    # 에너지/석유 관련
    {"sector_name": "석유와가스", "symbol": "CL=F", "correlation_type": "positive", "description": "유가 상승 → 석유/가스 기업 수익 증가"},
    {"sector_name": "석유와가스", "symbol": "BZ=F", "correlation_type": "positive", "description": "브렌트유 연동"},
    {"sector_name": "석유와가스", "symbol": "NG=F", "correlation_type": "positive", "description": "천연가스 가격 연동"},
    {"sector_name": "에너지장비및서비스", "symbol": "CL=F", "correlation_type": "positive", "description": "유가 상승 → 에너지 설비 투자 확대"},
    {"sector_name": "가스유틸리티", "symbol": "NG=F", "correlation_type": "negative", "description": "가스 원가 상승 → 유틸리티 마진 축소"},
    # 화학/소재
    {"sector_name": "화학", "symbol": "CL=F", "correlation_type": "negative", "description": "유가 상승 → 나프타 등 원재료 비용 증가"},
    {"sector_name": "화학", "symbol": "NG=F", "correlation_type": "negative", "description": "천연가스 원료 비용 상승"},
    # 철강/비철금속
    {"sector_name": "철강", "symbol": "HG=F", "correlation_type": "positive", "description": "구리/금속 가격 동반 상승 추세"},
    {"sector_name": "비철금속", "symbol": "HG=F", "correlation_type": "positive", "description": "구리 가격 직접 연동"},
    {"sector_name": "비철금속", "symbol": "ALI=F", "correlation_type": "positive", "description": "알루미늄 가격 직접 연동"},
    {"sector_name": "비철금속", "symbol": "GC=F", "correlation_type": "positive", "description": "귀금속 가격 연동"},
    {"sector_name": "비철금속", "symbol": "SI=F", "correlation_type": "positive", "description": "은 가격 연동"},
    # 전자/반도체 (금속 원재료)
    {"sector_name": "반도체와반도체장비", "symbol": "HG=F", "correlation_type": "negative", "description": "구리 원재료 비용 증가"},
    {"sector_name": "전자장비와기기", "symbol": "HG=F", "correlation_type": "negative", "description": "구리 원재료 비용 증가"},
    {"sector_name": "전자장비와기기", "symbol": "ALI=F", "correlation_type": "negative", "description": "알루미늄 원재료 비용 증가"},
    # 식품/농업
    {"sector_name": "식품", "symbol": "ZC=F", "correlation_type": "negative", "description": "옥수수 원재료 비용 증가"},
    {"sector_name": "식품", "symbol": "ZW=F", "correlation_type": "negative", "description": "밀 원재료 비용 증가"},
    {"sector_name": "식품", "symbol": "ZS=F", "correlation_type": "negative", "description": "대두 원재료 비용 증가"},
    {"sector_name": "식품과기본식료품소매", "symbol": "ZC=F", "correlation_type": "negative", "description": "곡물 가격 상승 → 소매 원가 증가"},
    {"sector_name": "식품과기본식료품소매", "symbol": "ZW=F", "correlation_type": "negative", "description": "밀 가격 상승 → 소매 원가 증가"},
    # 운송 (유가 영향)
    {"sector_name": "항공사", "symbol": "CL=F", "correlation_type": "negative", "description": "유가 상승 → 항공 연료비 증가"},
    {"sector_name": "해운사", "symbol": "CL=F", "correlation_type": "negative", "description": "유가 상승 → 해운 연료비 증가"},
    {"sector_name": "도로와철도운송", "symbol": "CL=F", "correlation_type": "negative", "description": "유가 상승 → 운송비 증가"},
    # 건설
    {"sector_name": "건설", "symbol": "HG=F", "correlation_type": "negative", "description": "구리/건자재 원가 상승"},
    {"sector_name": "건설", "symbol": "ALI=F", "correlation_type": "negative", "description": "알루미늄 건자재 원가 상승"},
    {"sector_name": "건축자재", "symbol": "HG=F", "correlation_type": "negative", "description": "구리 원재료 비용 상승"},
    # 자동차
    {"sector_name": "자동차", "symbol": "ALI=F", "correlation_type": "negative", "description": "알루미늄 차체 원가 상승"},
    {"sector_name": "자동차", "symbol": "HG=F", "correlation_type": "negative", "description": "구리 배선/전장 부품 원가 상승"},
    {"sector_name": "자동차부품", "symbol": "ALI=F", "correlation_type": "negative", "description": "알루미늄 부품 원가 상승"},
    # 전기/유틸리티
    {"sector_name": "전기유틸리티", "symbol": "NG=F", "correlation_type": "negative", "description": "천연가스 발전 연료비 증가"},
    {"sector_name": "전기유틸리티", "symbol": "CL=F", "correlation_type": "negative", "description": "유가 상승 → 발전 원가 상승"},
    # 석탄
    {"sector_name": "전기유틸리티", "symbol": "COAL", "correlation_type": "negative", "description": "석탄 발전 연료비 증가"},
    {"sector_name": "철강", "symbol": "COAL", "correlation_type": "negative", "description": "코킹탄 원가 상승 → 철강 제조원가 증가"},
    {"sector_name": "석유와가스", "symbol": "COAL", "correlation_type": "positive", "description": "석탄 가격 상승 → 에너지 대체재 수요 증가"},
    # 리튬
    {"sector_name": "자동차", "symbol": "LIT", "correlation_type": "negative", "description": "리튬 가격 상승 → EV 배터리 원가 증가"},
    {"sector_name": "자동차부품", "symbol": "LIT", "correlation_type": "negative", "description": "리튬 원재료 비용 증가"},
    {"sector_name": "비철금속", "symbol": "LIT", "correlation_type": "positive", "description": "리튬 수요·가격 증가 → 비철금속 섹터 호재"},
    # 희토류
    {"sector_name": "반도체와반도체장비", "symbol": "REMX", "correlation_type": "negative", "description": "희토류 공급 차질 → 반도체 생산 원가 증가"},
    {"sector_name": "전자장비와기기", "symbol": "REMX", "correlation_type": "negative", "description": "희토류 원재료 비용 증가"},
    {"sector_name": "자동차", "symbol": "REMX", "correlation_type": "negative", "description": "희토류 가격 상승 → EV 모터 원가 증가"},
    {"sector_name": "비철금속", "symbol": "REMX", "correlation_type": "positive", "description": "희토류 수요·가격 증가 → 비철금속 섹터 호재"},
]


def seed_commodities(db: Session) -> None:
    """원자재 마스터 데이터를 시드한다. 이미 존재하면 스킵."""
    existing_symbols = {c.symbol for c in db.query(Commodity.symbol).all()}

    added = 0
    for data in COMMODITIES_DATA:
        if data["symbol"] not in existing_symbols:
            db.add(Commodity(**data))
            added += 1

    if added:
        db.commit()
        logger.info(f"원자재 시드 완료: {added}개 추가")
    else:
        logger.info(f"원자재 이미 존재: {len(existing_symbols)}개")


def seed_sector_commodity_relations(db: Session) -> None:
    """섹터-원자재 관계를 시드한다. 누락된 관계만 추가 (upsert 방식)."""
    # 섹터명 → ID 매핑
    sector_map = {s.name: s.id for s in db.query(Sector).all()}
    # 원자재 심볼 → ID 매핑
    commodity_map = {c.symbol: c.id for c in db.query(Commodity).all()}

    # 기존 관계 (sector_id, commodity_id) 셋
    existing_pairs = {
        (r.sector_id, r.commodity_id)
        for r in db.query(SectorCommodityRelation.sector_id, SectorCommodityRelation.commodity_id).all()
    }

    added = 0
    for rel in SECTOR_COMMODITY_RELATIONS:
        sector_id = sector_map.get(rel["sector_name"])
        commodity_id = commodity_map.get(rel["symbol"])
        if not sector_id:
            logger.debug(f"섹터 '{rel['sector_name']}' 미발견 — 관계 스킵")
            continue
        if not commodity_id:
            logger.debug(f"원자재 '{rel['symbol']}' 미발견 — 관계 스킵")
            continue
        if (sector_id, commodity_id) in existing_pairs:
            continue
        db.add(SectorCommodityRelation(
            sector_id=sector_id,
            commodity_id=commodity_id,
            correlation_type=rel["correlation_type"],
            description=rel.get("description"),
        ))
        added += 1

    if added:
        db.commit()
        logger.info(f"섹터-원자재 관계 시드 완료: {added}개 추가")
    else:
        logger.info("섹터-원자재 관계: 추가할 신규 항목 없음")
