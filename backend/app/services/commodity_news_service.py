"""원자재 뉴스 크롤링 및 분류 서비스.

기존 Naver/Google 크롤러를 재사용하여 원자재 관련 뉴스를 수집하고,
news_commodity_relations 테이블에 원자재-뉴스 매핑을 저장한다.
"""
import asyncio
import logging
import re

from sqlalchemy.orm import Session

from app.models.commodity import Commodity, SectorCommodityRelation
from app.models.news import NewsArticle
from app.models.news_commodity_relation import NewsCommodityRelation
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.services.ai_classifier import is_non_financial_article

logger = logging.getLogger(__name__)

# 원자재 뉴스 검색용 한국어 키워드
COMMODITY_KEYWORDS_KO: list[str] = [
    "유가", "금값", "금가격", "구리가격", "원자재", "철강가격", "원유", "천연가스",
    "곡물가격", "알루미늄", "리튬", "브렌트유", "WTI", "국제유가", "금선물",
    "원유선물", "비철금속", "철광석", "니켈", "아연", "납", "주석",
    "원자재가격", "에너지가격", "광물", "희토류",
]

# 원자재 뉴스 검색용 영어 키워드
COMMODITY_KEYWORDS_EN: list[str] = [
    "crude oil price", "gold price", "copper futures", "commodity market",
    "steel price", "natural gas", "oil price", "aluminum price",
    "wheat price", "corn futures", "soybean",
]

# 영향 방향 판별용 키워드 (한국어)
_IMPACT_PRICE_UP = ["급등", "상승", "인상", "고공행진", "치솟", "폭등", "강세", "사상최고"]
_IMPACT_PRICE_DOWN = ["급락", "하락", "인하", "폭락", "약세", "최저", "하락세"]
_IMPACT_SUPPLY_DISRUPTION = ["공급 차질", "감산", "제재", "수출 금지", "공급 부족", "생산 중단", "파업"]
_IMPACT_DEMAND_CHANGE = ["수요 증가", "수요 감소", "수요 둔화", "수요 급증", "수요 확대", "수요 위축"]
_IMPACT_POLICY_CHANGE = ["정책", "규제", "합의", "OPEC", "감산 합의", "관세", "무역"]


def get_commodity_search_queries() -> list[str]:
    """원자재 뉴스 크롤링용 검색 쿼리 목록 반환."""
    return COMMODITY_KEYWORDS_KO[:10]


def _determine_impact_direction(title: str) -> str:
    """뉴스 제목에서 원자재 가격 영향 방향을 결정한다."""
    title_lower = title.lower()

    for kw in _IMPACT_PRICE_UP:
        if kw in title_lower:
            return "price_up"
    for kw in _IMPACT_PRICE_DOWN:
        if kw in title_lower:
            return "price_down"
    for kw in _IMPACT_SUPPLY_DISRUPTION:
        if kw in title_lower:
            return "supply_disruption"
    for kw in _IMPACT_DEMAND_CHANGE:
        if kw in title_lower:
            return "demand_change"
    for kw in _IMPACT_POLICY_CHANGE:
        if kw in title_lower:
            return "policy_change"

    return "neutral"


# 1~2글자 원자재 이름의 오탐을 막기 위한 보강 키워드 목록
# "금" → "금값", "금가격" 등으로 대체하여 조사/복합어 오탐 방지
# "구리" → 광통신/반도체/전선 기사에서 "구리선" 비교 언급으로 오탐 다수
_COMMODITY_EXTRA_KEYWORDS: dict[str, list[str]] = {
    "금": ["금값", "금가격", "금선물", "국제금", "금시세", "귀금속", "금거래", "금 가격", "금 시세"],
    "은": ["은값", "은가격", "은선물", "귀금속", "은 가격", "은 시세"],
    "밀": ["밀가격", "밀 가격", "국제밀", "소맥", "밀 선물", "wheat price"],
    "구리": ["구리가격", "구리 가격", "구리값", "국제구리", "구리선물", "copper price", "구리 시장", "동 가격"],
}

# 단독 사용 시 오탐이 많아 키워드로 등록하지 않을 이름 (한국어)
# 구리: "광통신 vs 구리선" 비교 문맥, 반도체 기사의 배선 언급 등으로 오탐
_SKIP_SHORT_NAMES_KO: set[str] = {"금", "은", "밀", "구리"}


def _build_commodity_keyword_map(commodities: list[Commodity]) -> dict[str, int]:
    """원자재 이름(한/영)으로부터 keyword -> commodity_id 매핑을 생성한다.

    1~2글자 한국어 이름(금, 은, 밀 등)은 한국어 조사/복합어에 오탐이 많아
    단독 키워드로 등록하지 않고 보강 키워드(_COMMODITY_EXTRA_KEYWORDS)를 사용한다.
    """
    kw_map: dict[str, int] = {}
    for c in commodities:
        name_ko = c.name_ko.lower()
        name_en = c.name_en.lower()

        # 1~2글자 한국어 이름은 오탐 위험 — 보강 키워드로 대체
        if name_ko not in _SKIP_SHORT_NAMES_KO:
            kw_map[name_ko] = c.id
        for extra_kw in _COMMODITY_EXTRA_KEYWORDS.get(name_ko, []):
            kw_map[extra_kw.lower()] = c.id

        # 영어 이름은 2글자 이상만 등록 (한국어 오탐 없음)
        if len(name_en) >= 3:
            kw_map[name_en] = c.id

        # 심볼에서 =F 제거한 것도 추가 (예: CL=F -> cl, GC=F -> gc)
        # 단, 너무 짧으면 영어 본문에서 오탐 가능 — 3글자 이상만
        symbol_clean = c.symbol.replace("=F", "").lower()
        if len(symbol_clean) >= 3:
            kw_map[symbol_clean] = c.id

    return kw_map


def classify_commodity_news(
    db: Session,
    news_id: int,
    title: str,
    content: str | None = None,
) -> list[NewsCommodityRelation]:
    """뉴스를 원자재에 매핑하고 영향 방향을 분류한다.

    Args:
        db: DB 세션
        news_id: 뉴스 기사 ID
        title: 뉴스 제목
        content: 뉴스 본문 (선택)

    Returns:
        생성된 NewsCommodityRelation 레코드 목록
    """
    # 정치/연예 등 비금융 기사 사전 차단
    if is_non_financial_article(title):
        logger.debug(f"원자재 분류 스킵 (비금융 기사): {title[:60]}")
        return []

    commodities = db.query(Commodity).all()
    if not commodities:
        return []

    kw_map = _build_commodity_keyword_map(commodities)
    title_lower = title.lower()
    text_to_check = title_lower
    if content:
        text_to_check = title_lower + " " + content[:500].lower()

    # 키워드 매칭: 제목(+본문)에 원자재 이름이 포함되는지 확인
    matched_commodity_ids: set[int] = set()
    relations: list[NewsCommodityRelation] = []

    for keyword, commodity_id in kw_map.items():
        if commodity_id in matched_commodity_ids:
            continue
        if keyword in text_to_check:
            # 제목에 직접 포함되면 direct, 본문에만 있으면 indirect
            relevance = "direct" if keyword in title_lower else "indirect"
            impact = _determine_impact_direction(title)

            rel = NewsCommodityRelation(
                news_id=news_id,
                commodity_id=commodity_id,
                relevance=relevance,
                impact_direction=impact,
                match_type="keyword",
            )
            db.add(rel)
            relations.append(rel)
            matched_commodity_ids.add(commodity_id)

    # 일반 원자재 키워드 매칭 (특정 원자재를 지정하지 못했을 때)
    # "원자재", "에너지가격" 등의 포괄 키워드로 전체 원자재 중 category 기반 매칭
    if not matched_commodity_ids:
        for kw in COMMODITY_KEYWORDS_KO:
            if kw in title_lower:
                # 카테고리 추론
                category = _infer_category_from_keyword(kw)
                if category:
                    for c in commodities:
                        if c.category == category and c.id not in matched_commodity_ids:
                            impact = _determine_impact_direction(title)
                            rel = NewsCommodityRelation(
                                news_id=news_id,
                                commodity_id=c.id,
                                relevance="indirect",
                                impact_direction=impact,
                                match_type="keyword",
                            )
                            db.add(rel)
                            relations.append(rel)
                            matched_commodity_ids.add(c.id)
                break  # 첫 매칭 카테고리만 사용

    if relations:
        db.flush()

    # 관련 섹터의 종목도 news_stock_relations에 자동 태깅
    _auto_tag_sector_stocks(db, news_id, matched_commodity_ids)

    return relations


def _infer_category_from_keyword(keyword: str) -> str | None:
    """포괄적 원자재 키워드에서 카테고리를 추론한다."""
    energy_keywords = ["유가", "원유", "천연가스", "에너지가격", "브렌트유", "WTI", "국제유가", "원유선물"]
    metal_keywords = ["금값", "금가격", "구리가격", "알루미늄", "리튬", "비철금속", "철광석", "니켈", "아연", "납", "주석", "금선물", "광물", "희토류", "철강가격"]
    agriculture_keywords = ["곡물가격"]

    keyword_lower = keyword.lower()
    if any(kw in keyword_lower for kw in energy_keywords):
        return "energy"
    if any(kw in keyword_lower for kw in metal_keywords):
        return "metal"
    if any(kw in keyword_lower for kw in agriculture_keywords):
        return "agriculture"
    # "원자재", "원자재가격" 등은 None 반환 (전체 카테고리)
    return None


def _auto_tag_sector_stocks(
    db: Session,
    news_id: int,
    commodity_ids: set[int],
) -> None:
    """매칭된 원자재와 연관된 섹터의 종목을 news_stock_relations에 자동 추가한다."""
    if not commodity_ids:
        return

    # SectorCommodityRelation을 통해 관련 섹터 찾기
    sector_rels = (
        db.query(SectorCommodityRelation)
        .filter(SectorCommodityRelation.commodity_id.in_(commodity_ids))
        .all()
    )
    if not sector_rels:
        return

    # 이미 존재하는 sector 관계 확인
    existing_sector_ids = set()
    existing = (
        db.query(NewsStockRelation.sector_id)
        .filter(NewsStockRelation.news_id == news_id, NewsStockRelation.sector_id.isnot(None))
        .all()
    )
    existing_sector_ids = {r[0] for r in existing}

    for rel in sector_rels:
        if rel.sector_id in existing_sector_ids:
            continue
        existing_sector_ids.add(rel.sector_id)
        db.add(NewsStockRelation(
            news_id=news_id,
            stock_id=None,
            sector_id=rel.sector_id,
            match_type="keyword",
            relevance="indirect",
        ))

    db.flush()


# @MX:ANCHOR: [AUTO] 원자재 뉴스 크롤링 진입점 (스케줄러, 수동 새로고침에서 호출)
# @MX:REASON: fan_in >= 3 - scheduler, refresh endpoint, crawl_all_news에서 사용
async def crawl_commodity_news(db: Session) -> int:
    """원자재 뉴스 전용 크롤링 실행.

    기존 Naver/Google 크롤러를 재사용하여 원자재 키워드로 뉴스를 수집한다.
    수집된 뉴스는 news_articles 테이블에 저장되고,
    원자재 관계는 news_commodity_relations 테이블에 저장된다.

    Returns:
        새로 저장된 기사 수
    """
    from app.services.crawlers.naver import search_naver_news
    from app.services.crawlers.google import search_google_news

    queries = get_commodity_search_queries()
    if not queries:
        return 0

    logger.info(f"원자재 뉴스 크롤링 시작: {len(queries)}개 쿼리")

    # 기존 URL로 중복 방지
    existing_urls: set[str] = set()
    for row in db.query(NewsArticle.url).yield_per(500):
        existing_urls.add(row[0])

    all_articles: list[dict] = []
    semaphore = asyncio.Semaphore(5)

    async def _search_one(query: str) -> list[dict]:
        async with semaphore:
            results = await asyncio.gather(
                search_naver_news(query, display=10),
                search_google_news(query, num=10),
                return_exceptions=True,
            )
            articles = []
            for result in results:
                if isinstance(result, list):
                    for a in result:
                        a["_commodity_query"] = query
                    articles.extend(result)
                elif isinstance(result, Exception):
                    logger.debug(f"원자재 뉴스 크롤링 실패 ({query}): {result}")
            return articles

    tasks = [_search_one(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    # URL 기반 중복 제거
    seen_urls: set[str] = set()
    unique_articles: list[dict] = []
    for article in all_articles:
        url = article.get("url", "")
        if not url or url in seen_urls or url in existing_urls:
            continue
        seen_urls.add(url)
        unique_articles.append(article)

    if not unique_articles:
        logger.info("원자재 뉴스: 새 기사 없음")
        return 0

    logger.info(f"원자재 뉴스: {len(unique_articles)}개 신규 기사 저장 시작")

    # 기사 저장 및 원자재 분류
    from sqlalchemy import text as sa_text
    from app.services.ai_classifier import classify_sentiment

    saved_count = 0
    batch_size = 20

    for i in range(0, len(unique_articles), batch_size):
        batch = unique_articles[i:i + batch_size]

        # news_articles 테이블에 벌크 삽입
        values_parts = []
        params: dict = {}
        for j, ad in enumerate(batch):
            values_parts.append(
                f"(:t{j}, :sm{j}, :u{j}, :sr{j}, :pa{j}, :se{j})"
            )
            params[f"t{j}"] = ad["title"][:500]
            params[f"sm{j}"] = (ad.get("description") or "")[:2000]
            params[f"u{j}"] = ad["url"][:1000]
            params[f"sr{j}"] = ad.get("source", "naver")
            params[f"pa{j}"] = ad.get("published_at")
            params[f"se{j}"] = classify_sentiment(ad["title"])

        sql = sa_text(
            f"""INSERT INTO news_articles (title, summary, url, source, published_at, sentiment)
            VALUES {', '.join(values_parts)}
            ON CONFLICT (url) DO NOTHING
            RETURNING id, url"""
        )

        try:
            result = db.execute(sql, params)
            url_to_id = {row[1]: row[0] for row in result.fetchall()}
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"원자재 뉴스 배치 삽입 실패: {e}")
            continue

        if not url_to_id:
            continue

        # 각 기사에 대해 원자재 분류 수행
        for ad in batch:
            article_id = url_to_id.get(ad["url"])
            if not article_id:
                continue

            relations = classify_commodity_news(
                db, article_id, ad["title"], ad.get("description"),
            )
            if relations:
                saved_count += 1

        # supply_disruption 감지 시 MacroAlert 생성
        _check_supply_disruption_alerts(db, batch, url_to_id)

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"원자재 뉴스 관계 저장 실패: {e}")

    logger.info(f"원자재 뉴스 크롤링 완료: {saved_count}개 기사 저장")
    return saved_count


def _check_supply_disruption_alerts(
    db: Session,
    batch: list[dict],
    url_to_id: dict[str, int],
) -> None:
    """supply_disruption 영향의 뉴스가 있으면 MacroAlert를 생성한다."""
    from app.models.macro_alert import MacroAlert

    disruption_articles = []
    for ad in batch:
        article_id = url_to_id.get(ad["url"])
        if not article_id:
            continue
        impact = _determine_impact_direction(ad["title"])
        if impact == "supply_disruption":
            disruption_articles.append(ad)

    if not disruption_articles:
        return

    # 최근 24시간 내 동일 키워드 알림이 있으면 중복 방지
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_alert = (
        db.query(MacroAlert)
        .filter(
            MacroAlert.keyword == "원자재 공급 차질",
            MacroAlert.created_at >= cutoff,
        )
        .first()
    )
    if recent_alert:
        return

    titles = [a["title"][:100] for a in disruption_articles[:3]]
    alert = MacroAlert(
        level="warning",
        keyword="원자재 공급 차질",
        title=f"원자재 공급 차질 뉴스 {len(disruption_articles)}건 감지",
        description="\n".join(titles),
        article_count=len(disruption_articles),
    )
    db.add(alert)
    logger.info(f"원자재 공급 차질 알림 생성: {len(disruption_articles)}건")
