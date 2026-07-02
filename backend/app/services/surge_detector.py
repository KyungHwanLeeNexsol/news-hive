"""SPEC-AI-012: 급등 징후 탐지 서비스.

4가지 탐지기(테마 뉴스 클러스터링, 거래량 이상+뉴스 콤보, 공시 급등 패턴,
즉각 공시 이벤트)와 앙상블 스코어링을 제공한다.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import and_, nullslast, or_
from sqlalchemy.orm import Session

from app.surge_config.surge_settings import SurgeDetectionConfig
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# 종목명 별칭 매핑: DB 공식명 → 뉴스에서 자주 쓰는 약칭 목록
# 한글 풀네임과 영문/혼용 약칭 모두 매칭하기 위해 사용
_STOCK_NAME_ALIASES: dict[str, list[str]] = {
    "삼성에스디에스": ["삼성SDS"],
    "에스케이텔레콤": ["SKT", "SK텔레콤"],
    "에스케이하이닉스": ["SK하이닉스"],
    "에스케이이노베이션": ["SK이노베이션"],
    "엘지에너지솔루션": ["LG에너지솔루션"],
    "엘지전자": ["LG전자"],
    "엘지화학": ["LG화학"],
    "엘지디스플레이": ["LG디스플레이"],
    "현대모비스": ["MOBIS"],
    "카카오뱅크": ["카카오 뱅크"],
    "카카오페이": ["카카오 페이"],
}


def _get_name_variants(name: str) -> list[str]:
    """종목명의 모든 변형(공식명 + 별칭)을 반환한다."""
    variants = [name]
    variants.extend(_STOCK_NAME_ALIASES.get(name, []))
    return variants


# @MX:WARN: [AUTO] 모듈 수준 전역 가변 상태 — 급등률 캐시
# @MX:REASON: Redis 없는 베어메탈 환경에서 DB 반복 쿼리 방지. TTL 만료 시 자동 갱신. 스레드 안전성은 GIL에 의존.
_surge_rate_cache: dict[str, float] = {}
_cache_loaded_at: datetime | None = None


@dataclass
class SurgeCandidate:
    """급등 징후 탐지 후보 종목."""

    stock_code: str
    stock_name: str
    theme_cluster_score: float = 0.0
    combo_score: float = 0.0
    pattern_score: float = 0.0
    legacy_score: float = 0.0
    # P3: 자사주 소각/취득, 계약 수주, 합병 등 즉각 이벤트 공시 점수
    immediate_disclosure_score: float = 0.0
    active_detectors: list[str] = field(default_factory=list)
    # SPEC-AI-018 REQ-005 fix: 최근 급등 페널티용 5일 수익률 (legacy_lookup 의존 제거)
    price_5d_trend: float | None = None
    # @MX:NOTE: SPEC-AI-020: per/pbr data-only observability; 필터링에 사용하지 않음
    # SPEC-AI-020: data-only observability; no filtering applied
    per: float | None = None
    pbr: float | None = None
    # SPEC-AI-028: 공시 감성 추적 (bullish/bearish/neutral)
    # bearish=페널티 적용, bullish=정상 시그널, neutral=공시 미관여
    disclosure_sentiment: str = "neutral"
    # SPEC-AI-039 REQ-039-002: 뉴스 지연 반응 점수 (24-72h 고임팩트 뉴스 기반)
    news_delayed_score: float = 0.0
    # SPEC-AI-051 REQ-AI051-001: 볼린저 밴드 스퀴즈 점수 (0.0~1.0)
    squeeze_score: float = 0.0
    # 거래량 폭발 소형주 탐지기 점수 — 뉴스 없이 거래량 비율로만 계산
    volume_breakout_score: float = 0.0
    # SPEC-AI-063 REQ-063-003: bypass 경로에서 주입된 composite_score 대체값
    # None이면 일반 앙상블 경로 (fund_manager가 build_surge_factor_scores 결과 사용)
    # 값이 있으면 bypass 경로: composite_score = volume_breakout_score
    bypass_composite_score: float | None = None
    # SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기 점수 (전일 등락률 5~15% 기반)
    momentum_continuation_score: float = 0.0
    # SPEC-AI-065 REQ-2: 후보 유입 풀 태그 (pool_a/pool_b/pool_c/existing)
    entry_pool: str = "existing"


def _sigmoid(x: float) -> float:
    """시그모이드 함수."""
    return 1.0 / (1.0 + math.exp(-x))


def _extract_valuation(
    stock_code: str,
    market_data: dict | None = None,
) -> tuple[float | None, float | None]:
    """시장 데이터 캐시에서 PER, PBR을 추출한다 (observability 전용).

    # @MX:NOTE: SPEC-AI-020: 데이터 수집 전용 헬퍼 — 필터링 로직 없음
    # 외부 API 신규 호출 없이 이미 조회된 market_data 딕셔너리에서 piggy-back 추출.
    # 값이 없거나 0/음수이면 None 반환 (의미없는 값 제외).

    Args:
        stock_code: 종목 코드 (로그용)
        market_data: 이미 조회된 시장 데이터 딕셔너리.
                     per, pbr 키 또는 eps/bps + price 키를 포함할 수 있음.

    Returns:
        (per, pbr) 튜플. 값이 없거나 의미없으면 None.
    """
    if not market_data:
        return None, None

    per: float | None = None
    pbr: float | None = None

    # 직접 per/pbr 키가 있으면 우선 사용
    raw_per = market_data.get("per")
    raw_pbr = market_data.get("pbr")

    if raw_per is not None:
        try:
            v = float(raw_per)
            per = v if v > 0 else None
        except (TypeError, ValueError):
            pass

    if raw_pbr is not None:
        try:
            v = float(raw_pbr)
            pbr = v if v > 0 else None
        except (TypeError, ValueError):
            pass

    # per/pbr이 없으면 eps/bps + price로 계산 시도 (piggy-back)
    if per is None or pbr is None:
        price = market_data.get("current_price") or market_data.get("price")
        eps = market_data.get("eps")
        bps = market_data.get("bps")

        if per is None and price and eps:
            try:
                p = float(price)
                e = float(eps)
                if e > 0 and p > 0:
                    per = round(p / e, 2)
            except (TypeError, ValueError):
                pass

        if pbr is None and price and bps:
            try:
                p = float(price)
                b = float(bps)
                if b > 0 and p > 0:
                    pbr = round(p / b, 2)
            except (TypeError, ValueError):
                pass

    return per, pbr


def _positive_sentiment_score(sentiment: str | None) -> float:
    """뉴스 감성 레이블을 0~1 점수로 변환한다.

    strong_positive=1.0, positive=0.7, mixed=0.4, neutral=0.2,
    negative/strong_negative=0.0
    """
    mapping = {
        "strong_positive": 1.0,
        "positive": 0.7,
        "mixed": 0.4,
        "neutral": 0.2,
        "negative": 0.0,
        "strong_negative": 0.0,
    }
    return mapping.get(sentiment or "neutral", 0.0)


# ---------------------------------------------------------------------------
# SPEC-AI-066: 촉매 확신도(Catalyst Conviction) 산출
# ---------------------------------------------------------------------------

# 확신도 tier 상수 — 두 개의 운영 tier(HIGH vs 그 외). NONE은 촉매 근거 전무를 명시적으로 표기.
CONVICTION_HIGH = "HIGH"
CONVICTION_LOW = "LOW"
CONVICTION_NONE = "NONE"


@dataclass
class ConvictionEvidence:
    """SPEC-AI-066 REQ-AI066-001: 종목별 확신도 산출 근거.

    combo 탐지기가 이미 조회한 NewsStockRelation 행 집합의 인메모리 집계로 채워진다
    (신규 쿼리 없음). 필드는 REQ-001 (a)~(e)에 대응한다.
    """

    article_count: int = 0            # (a) 커버리지 기사 수
    coverage_hours: float = 0.0       # (b) 첫~마지막 기사 시간 span (시간)
    sentiment_score: float = 0.0      # (c) 감성 강도 집계 (최대)
    has_high_impact_keyword: bool = False  # (d) 고임팩트 촉매 키워드 존재
    has_backing_disclosure: bool = False   # (e) 당일/밤새 공시 뒷받침


def _has_catalyst_keyword(text: str, config: SurgeDetectionConfig) -> bool:
    """텍스트에 고임팩트 촉매 키워드(인수/합병/경영권 + 기술이전/임상/수주)가 있는지 판정한다.

    SPEC-AI-066 REQ-001 (d): 기존 SPEC-AI-039 high_impact_news 키워드 집합을 재사용·확장한다.
    """
    if not text:
        return False
    catalyst = config.catalyst_conviction
    for kw in catalyst.acquisition_keywords:
        if kw in text:
            return True
    hi = config.high_impact_news
    for kw in (*hi.tech_transfer, *hi.clinical, *hi.contract):
        if kw in text:
            return True
    return False


# @MX:ANCHOR: [AUTO] SPEC-AI-066 REQ-001 — 확신도 판별 순수 함수. combo/disclosure/event 재스캔 3경로가 공유
# @MX:REASON: 확신도 HIGH만이 REQ-002 과열완화·REQ-003 페널티완화·REQ-007 이벤트트리거를 여는 단일 판별점. 경계 변경 시 3경로 동시 영향
# @MX:SPEC: SPEC-AI-066 REQ-AI066-001
def compute_catalyst_conviction(
    evidence: ConvictionEvidence,
    config: SurgeDetectionConfig,
) -> str:
    """확신도 근거로부터 tier(HIGH/LOW/NONE)를 산출한다 (Option A: 2단 이산).

    - 촉매 근거 전무(기사 0 + 공시 없음) → NONE (결코 HIGH가 되지 않음, AC-1.3)
    - HIGH 조건: 지속적 다출처 뉴스 커버리지 + 고임팩트 촉매 키워드 (뉴스 경로)
                또는 공시 뒷받침 + 고임팩트 키워드 + 감성 요건 (공시 경로)
    - 그 외 → LOW (비HIGH, 레거시 게이트 그대로)

    Args:
        evidence: 확신도 산출 근거 (기사 수/지속시간/감성/키워드/공시)
        config: SurgeDetectionConfig (catalyst_conviction 임계값)

    Returns:
        CONVICTION_HIGH / CONVICTION_LOW / CONVICTION_NONE 중 하나
    """
    cfg = config.catalyst_conviction

    if evidence.article_count <= 0 and not evidence.has_backing_disclosure:
        return CONVICTION_NONE

    # 뉴스 경로: 기사 수 + 지속시간 + 감성 강도 + 고임팩트 키워드 모두 충족
    news_qualifies = (
        evidence.article_count >= cfg.min_article_count_high
        and evidence.coverage_hours >= cfg.min_coverage_hours_high
        and evidence.sentiment_score >= cfg.min_sentiment_high
        and evidence.has_high_impact_keyword
    )
    # 공시 경로: 공시 뒷받침 + 고임팩트 키워드 + 감성 요건 (Option B 장점 흡수)
    disclosure_qualifies = (
        evidence.has_backing_disclosure
        and evidence.has_high_impact_keyword
        and evidence.sentiment_score >= cfg.min_sentiment_high
    )
    if news_qualifies or disclosure_qualifies:
        return CONVICTION_HIGH
    return CONVICTION_LOW


# ---------------------------------------------------------------------------
# 탐지기 1: 테마 뉴스 클러스터링
# ---------------------------------------------------------------------------

def detect_theme_news_cluster(
    db: Session,
    recent_news: list[NewsArticle],
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """테마 뉴스 클러스터링으로 급등 후보를 탐지한다 (AC-SURGE-001).

    cluster_window_hours 내 뉴스를 DB에서 직접 조회하여 테마 키워드가
    min_article_count개 이상 감지되면 해당 섹터 종목을 후보로 반환한다.

    # @MX:NOTE: recent_news 파라미터는 하위 호환성을 위해 유지하나 미사용.
    # DB 직접 조회로 브리핑 50건 제한 우회. (SPEC-AI-012 신호 생성 복구)

    Args:
        db: SQLAlchemy 동기 세션
        recent_news: 미사용 (하위 호환성 유지)
        config: SurgeDetectionConfig 설정

    Returns:
        SurgeCandidate 목록 (theme_cluster_score 채워짐)
    """
    cfg = config.theme_cluster
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.cluster_window_hours)
    cutoff_naive = cutoff.replace(tzinfo=None)

    # 1. DB에서 직접 기준 시간 내 뉴스 조회 (브리핑 50건 제한 우회)
    window_news = (
        db.query(NewsArticle)
        .filter(NewsArticle.published_at >= cutoff_naive)
        .order_by(NewsArticle.published_at.desc())
        .limit(1000)
        .all()
    )

    if not window_news:
        logger.debug("[테마클러스터] 기준 시간(%dh) 내 뉴스 없음", cfg.cluster_window_hours)
        return []

    # 2. 키워드별 기사 수 카운트
    keyword_counts: dict[str, int] = {kw: 0 for kw in cfg.keywords}
    for article in window_news:
        text = (article.title or "") + " " + (article.content or "") + " " + (article.summary or "")
        for kw in cfg.keywords:
            if kw in text:
                keyword_counts[kw] += 1

    # 3. 활성 테마 식별 (min_article_count 이상)
    active_themes: dict[str, int] = {
        kw: cnt for kw, cnt in keyword_counts.items()
        if cnt >= cfg.min_article_count
    }

    if not active_themes:
        logger.debug("[테마클러스터] 활성 테마 없음 (min=%d)", cfg.min_article_count)
        return _comention_supplement(db, window_news, config)

    logger.info("[테마클러스터] 활성 테마 %d개: %s", len(active_themes), list(active_themes.keys()))

    # 4. 활성 테마의 관련 섹터 목록 수집
    theme_to_sectors: dict[str, list[str]] = {}
    for theme, cnt in active_themes.items():
        sectors = cfg.sector_theme_map.get(theme, [])
        if sectors:
            theme_to_sectors[theme] = sectors

    if not theme_to_sectors:
        return _comention_supplement(db, window_news, config)

    all_sector_names: set[str] = set()
    for sectors in theme_to_sectors.values():
        all_sector_names.update(sectors)

    # 5. 해당 섹터의 종목 조회 (시가총액 필터 포함)
    # @MX:NOTE: market_cap 단위는 억원 (DB 기준), min_market_cap_krw는 원 단위 → 억원으로 환산
    min_market_cap_eok = cfg.min_market_cap_krw // 100_000_000

    sectors_in_db = db.query(Sector).filter(Sector.name.in_(all_sector_names)).all()
    sector_id_to_name = {s.id: s.name for s in sectors_in_db}

    sector_ids = [s.id for s in sectors_in_db]
    if not sector_ids:
        logger.debug("[테마클러스터] DB에서 관련 섹터를 찾지 못함: %s", all_sector_names)
        return _comention_supplement(db, window_news, config)

    # SPEC-AI-038 성능 패치: NULL 시총 종목을 무조건 포함하면 수천 건의 불필요한 가격 API 호출 발생.
    # 해결: 뉴스 창 내 언급된 종목코드를 먼저 수집 → NULL 시총 종목은 언급된 것만 포함.
    _news_mentioned_codes: set[str] = set()
    for _a in window_news:
        _combined = (_a.title or "") + " " + (_a.content or "")
        # 6자리 숫자 코드 언급 여부: 간단한 포함 검사
        for _tok in _combined.split():
            if len(_tok) == 6 and _tok.isdigit():
                _news_mentioned_codes.add(_tok)

    stocks = (
        db.query(Stock)
        .filter(
            Stock.sector_id.in_(sector_ids),
            # SPEC-AI-038 REQ-038-PF1: NULL 시총 종목은 뉴스 언급된 것만 포함 (성능 개선)
            # 기존: or_(market_cap >= floor, market_cap IS NULL) → 최대 2000건 초과
            # 변경: NULL은 뉴스 언급 종목만 → NULL 포함 수를 수십 건으로 제한
            or_(
                Stock.market_cap >= min_market_cap_eok,
                and_(Stock.market_cap.is_(None), Stock.stock_code.in_(_news_mentioned_codes))
                if _news_mentioned_codes else Stock.market_cap >= min_market_cap_eok,
            ),
        )
        .all()
    )

    if not stocks:
        logger.debug("[테마클러스터] 시총 필터(%d억 이상) 통과 종목 없음", min_market_cap_eok)
        return _comention_supplement(db, window_news, config)

    # 6. 종목별 SurgeCandidate 생성
    # @MX:NOTE: [AUTO] 종목 수준 개인화: stock_article_score를 40%로 theme_base_score에 블렌딩
    # @MX:SPEC: SPEC-AI-014 REQ-001/002/003
    results: list[SurgeCandidate] = []
    for stock in stocks:
        stock_sector_name = sector_id_to_name.get(stock.sector_id, "")

        # 가장 높은 테마 점수를 사용 (종목이 여러 테마에 포함될 수 있음)
        best_score = 0.0
        best_theme_base = 0.0
        best_sector_relevance = 0.0

        for theme, cnt in active_themes.items():
            theme_sectors = theme_to_sectors.get(theme, [])
            if not theme_sectors:
                continue

            # 섹터 관련성 가중치: 종목 섹터가 테마 섹터 목록에 있으면 1.0, 아니면 0.5
            if stock_sector_name in theme_sectors:
                sector_relevance = 1.0
            else:
                sector_relevance = 0.5

            theme_base = min(1.0, cnt / 10)
            # 임시 점수로 가장 높은 테마 선택 (sector_relevance 반영 전 base로 비교)
            temp_score = theme_base * sector_relevance
            if temp_score > best_score:
                best_score = temp_score
                best_theme_base = theme_base
                best_sector_relevance = sector_relevance

        if best_score <= 0:
            continue

        # REQ-AI014-001: 종목 전용 기사 카운트 계산
        # 종목명(별칭 포함) 또는 종목코드가 제목/본문에 포함된 기사를 종목 전용 기사로 판별
        _name_variants = _get_name_variants(stock.name)
        stock_articles = [
            a for a in window_news
            if any(v in (a.title or "") + " " + (a.content or "") for v in _name_variants)
            or stock.stock_code in (a.title or "") + " " + (a.content or "")
        ]
        stock_specific_count = len(stock_articles)
        stock_article_score = min(1.0, stock_specific_count / 5)

        # REQ-AI014-001: 종목 전용 기사 유무에 따른 블렌딩 공식 적용
        if stock_specific_count >= 1:
            # 종목 전용 기사 있음: 60%/40% 블렌딩
            theme_cluster_score = (best_theme_base * 0.6) + (stock_article_score * 0.4)
        else:
            # 섹터 전용(종목 기사 없음): 0.5× 페널티
            theme_cluster_score = best_theme_base * 0.5

        # sector_relevance 곱하기 (기존과 동일)
        theme_cluster_score *= best_sector_relevance

        # SPEC-AI-038 성능 패치 최종판: detect_theme_news_cluster에서 가격 API 호출 완전 제거
        # 근거:
        #   - price_bonus 최대 +0.10 (테마 점수 0.85+ 종목에 영향 미미)
        #   - 921종목 × 0.6s/call = 550초 → timeout 직접 원인
        #   - per/pbr valuation은 observability-only (필터링 없음, @MX:NOTE SPEC-AI-020)
        # 효과: O(N×API_latency) → O(N) 순수 메모리 연산, 예상 실행 시간 < 10초
        price_bonus = 0.0  # 가격 보너스 미적용 (테마 기반 점수만 사용)

        theme_cluster_score += price_bonus

        # REQ-AI014-003: 뉴스 감성 통합
        # 종목 전용 기사가 있으면 평균 감성 점수로 배율 적용
        sentiment_factor = 1.0
        if stock_specific_count >= 1:
            avg_sentiment = statistics.mean(
                _positive_sentiment_score(a.sentiment) for a in stock_articles
            )
            sentiment_factor = 0.8 + (0.4 * avg_sentiment)
            theme_cluster_score *= sentiment_factor

        theme_cluster_score = min(1.0, max(0.0, theme_cluster_score))

        logger.debug(
            "[테마클러스터] code=%s theme_base=%.2f stock_news=%.2f price_bonus=%.2f "
            "sentiment=%.2f theme_cluster=%.2f",
            stock.stock_code,
            best_theme_base,
            stock_article_score,
            price_bonus,
            sentiment_factor,
            theme_cluster_score,
        )

        # @MX:NOTE: SPEC-AI-020: piggy-back per/pbr 수집 (observability) — 필터링 없음
        # SPEC-AI-038 성능 패치: per/pbr 조회 생략 (가격 API 호출 없음)
        _per, _pbr = None, None

        results.append(
            SurgeCandidate(
                stock_code=stock.stock_code,
                stock_name=stock.name,
                theme_cluster_score=theme_cluster_score,
                active_detectors=["theme_cluster"],
                per=_per,
                pbr=_pbr,
            )
        )

    # SPEC-AI-066 REQ-004: 뉴스 공동언급 기반 임시 테마 자동 확장 (기본 비활성).
    # 키워드→섹터 맵에 없는 이벤트 촉매(M&A 클러스터 등)를 co-mention으로 보강한다.
    if config.catalyst_conviction.comention_theme_enabled:
        try:
            _existing_codes = {c.stock_code for c in results}
            _comention_candidates = _derive_comention_theme_candidates(
                db, window_news, config, _existing_codes
            )
            if _comention_candidates:
                results.extend(_comention_candidates)
                logger.info(
                    "[테마클러스터] co-mention 보강 후보 %d개 추가", len(_comention_candidates)
                )
        except Exception as _ce:
            logger.debug("[테마클러스터] co-mention 파생 실패 (무시): %s", _ce)

    logger.info("[테마클러스터] 후보 %d개 탐지", len(results))
    return results


# @MX:NOTE: [AUTO] SPEC-AI-066 REQ-004 — group_cascade(AI-027/035) 접두사 매칭과 동일한 최소 접두사 길이
# @MX:SPEC: SPEC-AI-066 REQ-AI066-004
_COMENTION_GROUP_PREFIX_LEN = 2


def _comention_supplement(
    db: Session,
    window_news: list[NewsArticle],
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """SPEC-AI-066 REQ-004: 키워드→섹터 맵 경로가 조기 종료해도 co-mention 보강이 동작하도록
    하는 래퍼. 기능 비활성(comention_theme_enabled=false)이면 빈 목록 반환 (레거시 동등).
    """
    if not config.catalyst_conviction.comention_theme_enabled:
        return []
    try:
        return _derive_comention_theme_candidates(db, window_news, config, set())
    except Exception as _ce:
        logger.debug("[테마클러스터] co-mention 파생 실패 (무시): %s", _ce)
        return []


def _shares_group_prefix(name_a: str, name_b: str, min_prefix_len: int) -> bool:
    """두 종목명이 공통 선행 접두사를 min_prefix_len 이상 공유하는지 판정한다.

    SPEC-AI-027/035 group_cascade가 계열사 cascade를 소유하므로, co-mention 클러스터에서
    동일 그룹 계열사 쌍은 제외해 이중 카운트를 방지한다.
    """
    if not name_a or not name_b:
        return False
    common = 0
    for ca, cb in zip(name_a, name_b):
        if ca == cb:
            common += 1
        else:
            break
    return common >= min_prefix_len


def _derive_comention_theme_candidates(
    db: Session,
    window_news: list[NewsArticle],
    config: SurgeDetectionConfig,
    existing_codes: set[str],
) -> list[SurgeCandidate]:
    """SPEC-AI-066 REQ-004: 동일 기사에서 반복 공동언급되는 비계열 종목 클러스터를 파생한다.

    - 기사별 NewsStockRelation 종목 집합에서 종목 쌍 co-occurrence를 카운트.
    - comention_min_pairs 이상 동반 등장한 쌍만 클러스터 에지로 채택.
    - 동일 그룹 계열사 쌍(접두사 공유)은 group_cascade 소관 → 제외 (이중 카운트 방지).
    - 이미 키워드→섹터 맵으로 탐지된 종목(existing_codes)은 중복 추가하지 않음.

    Returns:
        비계열 co-mention 클러스터 구성원에 대한 theme_cluster_score 보강 후보 목록.
    """
    from collections import defaultdict

    catalyst = config.catalyst_conviction
    article_ids = [a.id for a in window_news if a.id is not None]
    if not article_ids:
        return []

    from app.models.news_relation import NewsStockRelation

    rows = (
        db.query(NewsStockRelation.news_id, Stock.stock_code, Stock.name)
        .join(Stock, Stock.id == NewsStockRelation.stock_id)
        .filter(NewsStockRelation.news_id.in_(article_ids))
        .all()
    )
    if not rows:
        return []

    article_stocks: dict[int, set[str]] = defaultdict(set)
    name_map: dict[str, str] = {}
    for news_id, code, name in rows:
        article_stocks[news_id].add(code)
        name_map[code] = name

    # 종목 쌍 co-occurrence 카운트
    pair_count: dict[tuple[str, str], int] = defaultdict(int)
    for codes in article_stocks.values():
        ordered = sorted(codes)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                pair_count[(ordered[i], ordered[j])] += 1

    # 임계 이상 + 비계열 쌍만 채택 → union-find로 클러스터 구성
    parent: dict[str, str] = {}

    def _find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    member_strength: dict[str, int] = defaultdict(int)
    for (a, b), cnt in pair_count.items():
        if cnt < catalyst.comention_min_pairs:
            continue
        if _shares_group_prefix(name_map.get(a, ""), name_map.get(b, ""), _COMENTION_GROUP_PREFIX_LEN):
            continue  # 계열사 쌍 → group_cascade 소관, 제외
        _union(a, b)
        member_strength[a] = max(member_strength[a], cnt)
        member_strength[b] = max(member_strength[b], cnt)

    if not member_strength:
        return []

    # 클러스터 크기 >= 2 인 구성원만 채택
    cluster_size: dict[str, int] = defaultdict(int)
    for code in member_strength:
        cluster_size[_find(code)] += 1

    candidates: list[SurgeCandidate] = []
    for code, strength in member_strength.items():
        if cluster_size[_find(code)] < 2:
            continue
        if code in existing_codes:
            continue  # 키워드 맵으로 이미 탐지됨 → 이중 카운트 방지
        # 공동언급 강도에 비례한 modest theme 점수 (보강 근거)
        score = min(0.5, 0.2 + 0.05 * strength)
        candidates.append(
            SurgeCandidate(
                stock_code=code,
                stock_name=name_map.get(code, code),
                theme_cluster_score=round(score, 4),
                active_detectors=["theme_cluster"],
            )
        )
    return candidates


def _fetch_price_change_sync(stock_code: str) -> dict | None:
    """비동기 fetch_current_price_with_change를 동기 컨텍스트에서 실행하는 래퍼.

    # @MX:NOTE: [AUTO] REQ-AI014-002 가격 변동 조회용 sync 어댑터
    # @MX:SPEC: SPEC-AI-014
    테스트에서는 _price_change_provider를 주입하여 모킹 가능.
    """
    global _price_change_provider
    if _price_change_provider is not None:
        return _price_change_provider(stock_code)

    try:
        from app.services.naver_finance import fetch_current_price_with_change_sync
        return fetch_current_price_with_change_sync(stock_code)
    except Exception:
        return None


# 테스트 주입용 프로바이더 — None이면 운영 경로 사용
_price_change_provider: Callable[[str], dict | None] | None = None


# ---------------------------------------------------------------------------
# SPEC-AI-050 REQ-1: 동적 뉴스 윈도우 헬퍼
# ---------------------------------------------------------------------------

def _resolve_dynamic_news_window(base_hours: int, run_dt: datetime) -> int:
    """주말/연휴 직후 뉴스 윈도우를 동적으로 확장한다.

    # @MX:NOTE: [AUTO] SPEC-AI-050 REQ-1 — 월요일 또는 직전 거래일과 2역일 이상 차이 시 윈도우 4배 확장 (최대 72h)
    # @MX:SPEC: SPEC-AI-050 REQ-1

    Args:
        base_hours: 기본 news_window_hours (레짐 파라미터에서 가져옴)
        run_dt: 실행 시각 (datetime)

    Returns:
        확장된 news_window_hours (역일 차이 < 2이면 base_hours 그대로)
    """
    from app.services.surge_trading_service import _get_prev_business_day

    run_date = run_dt.date() if hasattr(run_dt, "date") else run_dt
    prev_biz = _get_prev_business_day(run_date)
    calendar_diff = (run_date - prev_biz).days

    if calendar_diff >= 2:
        expanded = min(72, base_hours * 4)
        logger.info(
            "[동적윈도우] 주말/연휴 직후 확장 적용: %dh → %dh (직전 거래일 %d역일 전)",
            base_hours,
            expanded,
            calendar_diff,
        )
        return expanded
    return base_hours


def _is_weekend_gap_up_day(run_dt: datetime) -> bool:
    """주말/연휴 직후 갭업 탐지 대상일 여부를 반환한다.

    # @MX:NOTE: [AUTO] SPEC-AI-050 REQ-5 — 직전 거래일과 2역일 이상 차이 시 True
    # @MX:SPEC: SPEC-AI-050 REQ-5
    """
    from app.services.surge_trading_service import _get_prev_business_day

    run_date = run_dt.date() if hasattr(run_dt, "date") else run_dt
    prev_biz = _get_prev_business_day(run_date)
    return (run_date - prev_biz).days >= 2


# ---------------------------------------------------------------------------
# 탐지기 2: 거래량 이상 + 뉴스 콤보
# ---------------------------------------------------------------------------

def detect_volume_surge_news_combo(
    db: Session,
    config: SurgeDetectionConfig,
    market_regime: str = "SIDEWAYS",
) -> list[SurgeCandidate]:
    """거래량 z-score 이상 + 긍정 뉴스 콤보로 급등 후보를 탐지한다 (AC-SURGE-002).

    거래량 z-score > volume_zscore_threshold AND
    최근 news_window_hours 내 긍정 뉴스(sentiment_score >= min_news_sentiment)가 있는 종목.

    거래량 데이터는 FundSignal.price_at_signal 연속 레코드로 대체할 수 없으므로
    naver_finance 히스토리에 의존한다. 데이터 없는 경우 해당 종목 스킵.

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정
        market_regime: 현재 시장 레짐 (REQ-018-004, 기본 'SIDEWAYS')

    Returns:
        SurgeCandidate 목록 (combo_score 채워짐)
    """
    # P1a: enabled=False이면 즉시 반환 — 탐지기 완전 비활성화
    if not config.volume_news_combo.enabled:
        return []

    # REQ-018-004: 레짐별 파라미터 오버라이드
    # @MX:NOTE: [AUTO] SIDEWAYS/미등록 레짐은 volume_news_combo 기본값 사용
    cfg = config.volume_news_combo
    regime_params = config.regime_detector_params.get(market_regime)
    if regime_params is not None:
        # SPEC-AI-050 REQ-1: 주말/연휴 직후 동적 윈도우 확장 적용
        from zoneinfo import ZoneInfo as _ZI
        _KST = _ZI("Asia/Seoul")
        _run_dt = datetime.now(_KST)
        _dynamic_window = _resolve_dynamic_news_window(regime_params.news_window_hours, _run_dt)

        # Pydantic 모델이므로 직접 필드 접근 (copy + 오버라이드)
        from app.surge_config.surge_settings import VolumeNewsComboConfig
        cfg = VolumeNewsComboConfig(
            volume_zscore_threshold=regime_params.volume_zscore_threshold,
            volume_baseline_days=cfg.volume_baseline_days,
            news_window_hours=_dynamic_window,
            min_news_sentiment=regime_params.min_news_sentiment,
        )
    # @MX:NOTE: 운영환경(PostgreSQL)은 timezone-aware, 테스트(SQLite)는 naive — 양쪽 호환
    news_cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.news_window_hours)
    news_cutoff_naive = news_cutoff.replace(tzinfo=None)

    # 최근 뉴스에서 긍정 감성 종목 코드 수집
    positive_news_stocks: dict[str, float] = {}  # stock_code -> max sentiment score

    # news_stock_relations를 통해 뉴스와 연결된 종목 조회
    from app.models.news_relation import NewsStockRelation

    # N+1 해소: 단일 JOIN 쿼리로 뉴스→관계→종목 일괄 조회
    # SPEC-AI-066 REQ-001: 확신도 산출을 위해 published_at/collected_at/title 컬럼을 함께 조회한다
    # (동일 행 집합의 인메모리 집계 확장 — 종목당 신규 쿼리 없음).
    news_stock_rows = (
        db.query(
            NewsArticle.sentiment,
            Stock.stock_code,
            NewsArticle.published_at,
            NewsArticle.collected_at,
            NewsArticle.title,
            NewsArticle.ai_summary,
        )
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .join(Stock, Stock.id == NewsStockRelation.stock_id)
        .filter(
            NewsArticle.collected_at >= news_cutoff_naive,
            NewsArticle.sentiment.in_(["positive", "strong_positive", "mixed"]),
        )
        .all()
    )

    # SPEC-AI-066 REQ-001: 종목별 확신도 근거 집계 (기사 수/시간 span/최대 감성/키워드)
    _conviction_agg: dict[str, dict] = {}

    for sentiment, stock_code, published_at, collected_at, title, ai_summary in news_stock_rows:
        score = _positive_sentiment_score(sentiment)

        # 확신도 집계는 min_news_sentiment 필터 이전의 전체 행에 대해 수행 (커버리지 정직성)
        agg = _conviction_agg.get(stock_code)
        if agg is None:
            agg = {"count": 0, "min_ts": None, "max_ts": None, "max_sent": 0.0, "keyword": False}
            _conviction_agg[stock_code] = agg
        agg["count"] += 1
        agg["max_sent"] = max(agg["max_sent"], score)
        _ts = published_at or collected_at
        if _ts is not None:
            _ts_naive = _ts.replace(tzinfo=None) if _ts.tzinfo is not None else _ts
            if agg["min_ts"] is None or _ts_naive < agg["min_ts"]:
                agg["min_ts"] = _ts_naive
            if agg["max_ts"] is None or _ts_naive > agg["max_ts"]:
                agg["max_ts"] = _ts_naive
        if not agg["keyword"]:
            _text = (title or "") + " " + (ai_summary or "")
            if _has_catalyst_keyword(_text, config):
                agg["keyword"] = True

        if score < cfg.min_news_sentiment:
            continue
        existing = positive_news_stocks.get(stock_code, 0.0)
        positive_news_stocks[stock_code] = max(existing, score)

    if not positive_news_stocks:
        logger.debug("[거래량콤보] 긍정 뉴스 관련 종목 없음")
        return []

    # SPEC-AI-038 성능 패치: 거래량 히스토리 조회는 종목당 3 HTTP 요청 → 상위 20개로 제한
    # 수백 종목 처리 시 수천 API 호출 발생 → timeout 원인 (50→20으로 축소: 최악 750s→300s)
    _MAX_COMBO_CANDIDATES = 20
    if len(positive_news_stocks) > _MAX_COMBO_CANDIDATES:
        positive_news_stocks = dict(
            sorted(positive_news_stocks.items(), key=lambda x: x[1], reverse=True)[:_MAX_COMBO_CANDIDATES]
        )
        logger.info("[거래량콤보] 감성점수 상위 %d개로 제한 (성능 패치)", _MAX_COMBO_CANDIDATES)

    # SPEC-AI-066 REQ-001 (e): 후보 종목의 당일/밤새 공시 뒷받침 여부를 1회 배치 조회로 확인
    # (종목당 신규 쿼리 없음 — 최종 후보 집합에 대한 단일 IN 쿼리).
    _backing_disclosure_codes: set[str] = set()
    if config.catalyst_conviction.enabled:
        try:
            from app.models.news_relation import NewsStockRelation as _NSR  # noqa: F401
            _disc_cutoff = (datetime.now(timezone.utc) - timedelta(hours=cfg.news_window_hours)).strftime("%Y%m%d")
            _disc_rows = (
                db.query(Stock.stock_code)
                .join(Disclosure, Disclosure.stock_id == Stock.id)
                .filter(
                    Stock.stock_code.in_(list(positive_news_stocks.keys())),
                    Disclosure.rcept_dt >= _disc_cutoff,
                )
                .all()
            )
            _backing_disclosure_codes = {r.stock_code for r in _disc_rows}
        except Exception as _de:
            logger.debug("[거래량콤보] 공시 뒷받침 조회 실패 (무시): %s", _de)

    # SPEC-AI-066 REQ-001/002: 종목별 확신도 tier 산출 (인메모리 집계 → 순수 함수)
    _conviction_tiers: dict[str, str] = {}
    for _code in positive_news_stocks:
        _agg = _conviction_agg.get(_code, {})
        _min_ts, _max_ts = _agg.get("min_ts"), _agg.get("max_ts")
        _hours = 0.0
        if _min_ts is not None and _max_ts is not None:
            _hours = (_max_ts - _min_ts).total_seconds() / 3600.0
        _evidence = ConvictionEvidence(
            article_count=_agg.get("count", 0),
            coverage_hours=_hours,
            sentiment_score=_agg.get("max_sent", 0.0),
            has_high_impact_keyword=_agg.get("keyword", False),
            has_backing_disclosure=_code in _backing_disclosure_codes,
        )
        _conviction_tiers[_code] = compute_catalyst_conviction(_evidence, config)

    # 거래량 z-score 계산 — naver_finance 히스토리 사용
    # @MX:NOTE: 동기 컨텍스트에서 비동기 함수 호출 불가 → 캐시된 데이터 또는 스킵
    # 실제 운영 환경에서는 fund_manager의 비동기 컨텍스트에서 호출되므로
    # 여기서는 FundSignal 이력에서 volume 대용 데이터를 사용하거나 종목별 처리 스킵
    # 테스트 환경에서는 _volume_provider 주입으로 대체 가능
    results: list[SurgeCandidate] = []

    # 종목명 일괄 조회 (N+1 방지)
    if positive_news_stocks:
        stock_name_rows = (
            db.query(Stock.stock_code, Stock.name)
            .filter(Stock.stock_code.in_(list(positive_news_stocks.keys())))
            .all()
        )
        stock_names: dict[str, str] = {r.stock_code: r.name for r in stock_name_rows}
    else:
        stock_names: dict[str, str] = {}

    for stock_code, sentiment_score in positive_news_stocks.items():
        volumes = _get_volume_history(stock_code, cfg.volume_baseline_days)
        if not volumes or len(volumes) < 5:
            # 거래량 데이터 부족 시 스킵
            logger.debug("[거래량콤보] %s 거래량 데이터 부족 (%d개)", stock_code, len(volumes) if volumes else 0)
            continue

        mean_vol = statistics.mean(volumes[:-1])  # 마지막 제외한 baseline
        std_vol = statistics.stdev(volumes[:-1]) if len(volumes[:-1]) > 1 else 0.0
        # SPEC-AI-067 REQ-002: 당일(오늘) 원소를 장중 실시간 값으로 교정. baseline(volumes[:-1])은
        # 위에서 이미 계산되어 sise_day 값 그대로 불변. 위메이드형 stale 64,418 → 실시간 258,945로
        # z-score 부호 오류(-1.63 → +1.05)를 교정한다. 게이트 임계/구조는 불변(SPEC-AI-030 소유).
        current_vol = _resolve_today_volume(stock_code, volumes[-1], config)
        # Gate 2(신선도)가 동일한 교정된 당일값을 보도록 리스트 말단만 동기화 (baseline 원소 불변).
        if current_vol != volumes[-1]:
            volumes = [*volumes[:-1], current_vol]

        if std_vol == 0:
            logger.debug("[거래량콤보] %s 거래량 표준편차 0 — 스킵", stock_code)
            continue

        z_score = (current_vol - mean_vol) / std_vol

        if z_score <= cfg.volume_zscore_threshold:
            logger.debug("[거래량콤보] %s z-score=%.2f (임계=%.1f) 미달", stock_code, z_score, cfg.volume_zscore_threshold)
            continue

        # 두 조건 모두 충족
        combo_score = _sigmoid((z_score - cfg.volume_zscore_threshold) / 1.0) * max(0.0, min(1.0, sentiment_score))

        stock_name = stock_names.get(stock_code, stock_code)

        # @MX:NOTE: SPEC-AI-020: piggy-back per/pbr 수집 (observability) — 필터링 없음
        _vol_price_data = None
        try:
            _vol_price_data = _fetch_price_change_sync(stock_code)
        except Exception:
            pass
        _per, _pbr = _extract_valuation(stock_code, _vol_price_data)

        # SPEC-AI-030: 추격매수 방지 게이트 (REQ-AI030-001~003)
        # @MX:NOTE: [AUTO] SPEC-AI-030 — cfg_guard.enabled=False이면 4개 게이트 전부 우회
        # @MX:SPEC: SPEC-AI-030
        cfg_guard = config.combo_chase_guard
        if cfg_guard.enabled:
            change_rate = None
            if _vol_price_data is not None:
                change_rate = _vol_price_data.get("change_rate")

            # Gate 1 (REQ-AI030-001): 당일 과열 필터
            # SPEC-AI-066 REQ-002: 확신도 HIGH일 때만 과열 상한을 상향한다 (non-HIGH는 기존 5% 유지).
            # catalyst_conviction.enabled=False이면 tier 무관하게 기본 상한 사용 (SPEC-AI-030 레거시 복원).
            _overheat_ceiling = cfg_guard.overheat_change_pct
            if (
                config.catalyst_conviction.enabled
                and _conviction_tiers.get(stock_code) == CONVICTION_HIGH
            ):
                _overheat_ceiling = cfg_guard.overheat_change_pct_high_conviction
            if change_rate is None and cfg_guard.exclude_on_price_unavailable:
                logger.debug("[거래량콤보] %s 가격 조회 실패 — 제외", stock_code)
                continue
            if change_rate is not None and change_rate >= _overheat_ceiling:
                logger.debug(
                    "[거래량콤보] %s 과열 제외 change_rate=%.2f%% (상한=%.1f, tier=%s)",
                    stock_code, change_rate, _overheat_ceiling,
                    _conviction_tiers.get(stock_code),
                )
                continue

            # Gate 2 (REQ-AI030-002): 거래량 신선도 검증
            if len(volumes) >= 2 and volumes[-2] > 0:
                freshness = volumes[-1] / volumes[-2]
                if freshness < cfg_guard.min_freshness_ratio:
                    logger.debug(
                        "[거래량콤보] %s stale 제외 freshness=%.2f",
                        stock_code, freshness,
                    )
                    continue
            # volumes[-2] == 0이고 volumes[-1] > 0이면 신선 → 통과

            # Gate 3 (REQ-AI030-003): 분산 패턴 거부 (음수 등락률)
            if change_rate is not None and change_rate < cfg_guard.distribution_change_pct:
                logger.debug(
                    "[거래량콤보] %s 분산패턴 제외 change_rate=%.2f%%",
                    stock_code, change_rate,
                )
                continue

        results.append(
            SurgeCandidate(
                stock_code=stock_code,
                stock_name=stock_name,
                combo_score=combo_score,
                active_detectors=["volume_news_combo"],
                per=_per,
                pbr=_pbr,
            )
        )
        logger.info("[거래량콤보] %s z-score=%.2f, combo_score=%.3f", stock_code, z_score, combo_score)

    logger.info("[거래량콤보] 후보 %d개 탐지", len(results))
    return results


def _get_volume_history(stock_code: str, baseline_days: int) -> list[float]:
    """종목 거래량 히스토리를 반환한다.

    운영 환경: naver_finance 캐시에서 동기적으로 읽거나 빈 리스트 반환.
    테스트 환경: _volume_provider 전역 함수를 통해 목 데이터 주입 가능.

    Returns:
        거래량 리스트 (가장 오래된 순, 마지막이 최신)
    """
    global _volume_provider
    if _volume_provider is not None:
        return _volume_provider(stock_code, baseline_days)

    # 운영 환경: naver_finance 캐시 조회 → 미스 시 동기 HTTP 폴백
    try:
        from app.services.naver_finance import _price_cache, fetch_stock_price_history_sync

        cached = _price_cache.data.get(stock_code)
        if not cached:
            # SPEC-AI-038 성능 패치: pages=3→1로 축소 (20일 baseline에 1페이지 충분, 3→1 HTTP 절감)
            cached = fetch_stock_price_history_sync(stock_code, pages=1)
        if cached:
            # Naver sise_day는 최신순(newest-first) → 역순으로 변환 후 최근 N일 슬라이스.
            # 반환 리스트의 마지막 원소(volumes[-1])가 "오늘"이며, SPEC-AI-067 REQ-002가 이 원소만
            # 장중 실시간 값으로 교정한다. 그 앞 원소(baseline)는 이전 거래일 데이터로, 완결된 것으로
            # 가정한다 — 오늘 실측한 것은 당일 행의 지연이며, 과거 행의 정확성은 별도로 검증되지 않았다
            # (SPEC-AI-067 REQ-006 spot-check 대상). baseline은 계속 sise_day에서 온다.
            records = list(reversed(cached))[-baseline_days:]
            return [float(r.volume) for r in records]
    except Exception as e:
        logger.debug("[거래량콤보] %s 거래량 조회 실패: %s", stock_code, e)

    return []


# @MX:NOTE: [AUTO] 테스트 주입용 프로바이더 — None이면 운영 경로(Naver API)를 사용
# @MX:SPEC: SPEC-AI-012
# 테스트 주입용 프로바이더 — None이면 운영 경로 사용
_volume_provider: Callable[[str, int], list[float]] | None = None


# ---------------------------------------------------------------------------
# SPEC-AI-067: 장중 실시간 당일 거래량 공유 메커니즘 (combo/breakout/PoolB 재사용)
# ---------------------------------------------------------------------------

# 스캔당 실시간 조회 예산 카운터 — gather_surge_candidates 진입 시 리셋 (REQ-005/007).
# @MX:NOTE: [AUTO] SPEC-AI-067 REQ-007 — 모듈 레벨 인메모리 카운터. 스캔 사이클 경계에서 초기화.
_live_volume_fetch_count: int = 0

# 테스트 주입용 프로바이더 — None이면 운영 경로(naver_finance.fetch_live_today_volume_sync) 사용.
_live_volume_provider: Callable[[str], int | None] | None = None


def _reset_live_volume_budget() -> None:
    """스캔 사이클 시작 시 실시간 거래량 조회 예산 카운터를 0으로 초기화한다 (SPEC-AI-067 REQ-005)."""
    global _live_volume_fetch_count
    _live_volume_fetch_count = 0


# @MX:ANCHOR: [AUTO] SPEC-AI-067 당일 거래량 교정 단일 결정 지점 — combo/breakout/PoolB 3개 호출부 공유
# @MX:REASON: fan_in=3. 장중 게이트·fail-open·예산 상한·단조 보정을 한 곳에 집중. 어느 한 경로라도
#   폴백을 빠뜨리면 그 탐지기가 중단될 수 있으므로 이 계약(예외 미전파, sise_day 폴백)은 불변이어야 한다.
# @MX:SPEC: SPEC-AI-067 REQ-AI067-001/005
def _resolve_today_volume(
    stock_code: str,
    sise_day_today: float,
    config: SurgeDetectionConfig,
) -> float:
    """당일(오늘) 거래량을 장중 실시간 모바일 값으로 교정한다 (SPEC-AI-067 공유 메커니즘).

    REQ-001/005: 세 호출부(combo `volumes[-1]`, breakout/PoolB `history[0].volume`)가
    재사용하는 단일 결정 지점. 장중 게이트·실시간 fetch·fail-open 폴백·예산 상한·단조
    비감소 보정을 한 곳에 집중하여 3중 복제로 인한 드리프트(폴백 누락 → 탐지 중단)를 방지한다.

    결정 규칙:
    - enabled=false → sise_day 값 그대로 (레거시 동등, REQ-007)
    - market_hours_only=true & 장외(_is_market_open()=false) → 모바일 미호출, sise_day 값
    - 스캔당 상한(max_live_fetches_per_scan) 초과 → sise_day 폴백 (REQ-005)
    - 모바일 실패/None/0 → sise_day 폴백 (fail-open, REQ-005)
    - 성공 → max(live, sise_day) (누적 거래량 단조 비감소 원칙, REQ-005)

    Args:
        stock_code: 종목 코드
        sise_day_today: sise_day에서 읽은 당일 거래량 (폴백 기준값)
        config: SurgeDetectionConfig (intraday_live_volume 섹션 사용)

    Returns:
        교정된 당일 거래량 (float). 어떤 경우에도 예외를 던지지 않는다.
    """
    global _live_volume_fetch_count
    cfg = config.intraday_live_volume

    # 마스터 스위치 off → 레거시(sise_day) 값
    if not cfg.enabled:
        return sise_day_today

    # 장중 게이팅: 장외에는 완결된 sise_day 값이 이미 정확하므로 모바일 호출 불필요
    if cfg.market_hours_only:
        try:
            from app.services.naver_finance import _is_market_open

            if not _is_market_open():
                return sise_day_today
        except Exception:
            return sise_day_today

    # 스캔당 예산 상한 초과 → sise_day 폴백 (레이트리밋 유계)
    if _live_volume_fetch_count >= cfg.max_live_fetches_per_scan:
        return sise_day_today

    # 실시간 취득 (fail-open) — 시도 자체를 예산에 계상
    _live_volume_fetch_count += 1
    try:
        if _live_volume_provider is not None:
            live = _live_volume_provider(stock_code)
        else:
            from app.services.naver_finance import fetch_live_today_volume_sync

            live = fetch_live_today_volume_sync(stock_code)
    except Exception as e:
        logger.debug("[실시간거래량] %s 조회 실패 — sise_day 폴백: %s", stock_code, e)
        return sise_day_today

    # None/0/음수는 무효 → sise_day 폴백
    if not live or live <= 0:
        return sise_day_today

    # 누적 거래량 단조 비감소: 더 큰(더 정확한) 값 채택
    return max(float(live), sise_day_today)


# ---------------------------------------------------------------------------
# 탐지기 3: 공시 급등 패턴
# ---------------------------------------------------------------------------

def compute_disclosure_type_surge_rates(
    db: Session,
    config: SurgeDetectionConfig,
) -> dict[str, float]:
    """공시 유형별 과거 급등률을 계산한다 (AC-SURGE-003).

    FundSignal 레코드 중 signal_type="disclosure_impact"인 것들에서
    price_after_5d / price_at_signal 비율로 급등 여부를 판정한다.

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정

    Returns:
        report_type → surge_rate (0.0~1.0) 매핑
    """
    cfg = config.disclosure_pattern
    surge_threshold = 1.0 + cfg.historical_surge_threshold_pct / 100.0

    # disclosure_impact 시그널 중 가격 검증 완료된 레코드 조회
    # @MX:NOTE: SPEC-AI-004 disclosure_impact_scorer.py의 로직을 중복 구현하지 않음
    #           price_after_5d 및 price_at_signal 필드는 SPEC-AI-004에서 채워짐
    signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.signal_type == "disclosure_impact",
            FundSignal.price_at_signal.isnot(None),
            FundSignal.price_after_5d.isnot(None),
        )
        .all()
    )

    # report_type별 집계: disclosure_id를 통해 Disclosure.report_type 조회
    type_stats: dict[str, dict[str, int]] = {}  # report_type -> {total, surge_count}

    for signal in signals:
        if not signal.disclosure_id:
            continue
        disclosure = db.query(Disclosure).filter(Disclosure.id == signal.disclosure_id).first()
        if not disclosure or not disclosure.report_type:
            continue

        rtype = disclosure.report_type
        if rtype not in type_stats:
            type_stats[rtype] = {"total": 0, "surge_count": 0}

        type_stats[rtype]["total"] += 1

        # 급등 판정: 5일 후 가격 / 시그널 시점 가격 >= surge_threshold
        if signal.price_at_signal and signal.price_at_signal > 0:
            ratio = (signal.price_after_5d or 0) / signal.price_at_signal
            if ratio >= surge_threshold:
                type_stats[rtype]["surge_count"] += 1

    # 최소 샘플 수 이상인 유형만 급등률 계산
    surge_rates: dict[str, float] = {}
    for rtype, stats in type_stats.items():
        if stats["total"] >= cfg.min_sample_size:
            surge_rates[rtype] = stats["surge_count"] / stats["total"]

    logger.info("[공시패턴] 유형별 급등률 계산 완료: %d개 유형", len(surge_rates))
    return surge_rates


def _get_cached_surge_rates(db: Session, config: SurgeDetectionConfig) -> dict[str, float]:
    """공시 유형별 급등률을 캐시에서 반환하거나 (만료 시) 재계산한다."""
    global _surge_rate_cache, _cache_loaded_at

    ttl = timedelta(hours=config.disclosure_pattern.cache_ttl_hours)
    now = datetime.now(timezone.utc)

    if _cache_loaded_at is None or now - _cache_loaded_at > ttl:
        _surge_rate_cache = compute_disclosure_type_surge_rates(db, config)
        _cache_loaded_at = now
        logger.debug("[공시패턴] 급등률 캐시 갱신 완료")

    return _surge_rate_cache


def detect_disclosure_surge_pattern(
    db: Session,
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """공시 유형별 과거 급등 패턴 기반 후보 탐지 (AC-SURGE-003).

    최근 24시간 공시 중 과거 급등률이 min_surge_rate 이상인 유형의 공시를 발행한 종목.

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정

    Returns:
        SurgeCandidate 목록 (pattern_score 채워짐)
    """
    cfg = config.disclosure_pattern

    # 캐시된 공시 유형별 급등률 조회
    surge_rates = _get_cached_surge_rates(db, config)

    if not surge_rates:
        logger.debug("[공시패턴] 급등률 데이터 없음")
        return []

    # 최근 공시 조회 (window 크기는 config에서 읽음)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=cfg.disclosure_window_hours)
    cutoff_str = cutoff_dt.strftime("%Y%m%d")

    recent_disclosures = (
        db.query(Disclosure)
        .filter(
            Disclosure.rcept_dt >= cutoff_str,
            Disclosure.report_type.isnot(None),
            Disclosure.stock_id.isnot(None),
        )
        .all()
    )

    # 종목별 최고 패턴 점수 집계
    stock_scores: dict[int, dict] = {}  # stock_id -> {score, stock_code, stock_name}

    for disc in recent_disclosures:
        rtype = disc.report_type
        surge_rate = surge_rates.get(rtype)
        if surge_rate is None or surge_rate < cfg.min_surge_rate:
            logger.debug("[공시패턴] %s 유형 급등률=%.2f (임계=%.2f) 미달", rtype, surge_rate or 0.0, cfg.min_surge_rate)
            continue

        # 패턴 점수: 최소 급등률(0.40) 초과분을 나머지 범위(0.60)로 정규화
        pattern_score = (surge_rate - cfg.min_surge_rate) / (1.0 - cfg.min_surge_rate)
        pattern_score = min(1.0, max(0.0, pattern_score))

        if disc.stock_id not in stock_scores or stock_scores[disc.stock_id]["score"] < pattern_score:
            stock = db.query(Stock).filter(Stock.id == disc.stock_id).first()
            if stock:
                stock_scores[disc.stock_id] = {
                    "score": pattern_score,
                    "stock_code": stock.stock_code,
                    "stock_name": stock.name,
                }

    # 성능 패치: 가격 API 호출 종목 수 제한 (공시패턴 탐지기 — cap 없어 월요일 누적 공시 시 hang 발생)
    _MAX_DISCLOSURE_CANDIDATES = 30
    if len(stock_scores) > _MAX_DISCLOSURE_CANDIDATES:
        stock_scores = dict(
            sorted(stock_scores.items(), key=lambda x: x[1]["score"], reverse=True)[
                :_MAX_DISCLOSURE_CANDIDATES
            ]
        )
        logger.info("[공시패턴] 점수 상위 %d개로 제한 (성능 패치)", _MAX_DISCLOSURE_CANDIDATES)

    results: list[SurgeCandidate] = []
    for _, info in stock_scores.items():
        # @MX:NOTE: SPEC-AI-020: piggy-back per/pbr 수집 (observability) — 필터링 없음
        _disc_price_data = None
        try:
            _disc_price_data = _fetch_price_change_sync(info["stock_code"])
        except Exception:
            pass
        _per, _pbr = _extract_valuation(info["stock_code"], _disc_price_data)

        results.append(
            SurgeCandidate(
                stock_code=info["stock_code"],
                stock_name=info["stock_name"],
                pattern_score=info["score"],
                active_detectors=["disclosure_pattern"],
                per=_per,
                pbr=_pbr,
            )
        )
        logger.info("[공시패턴] %s 패턴점수=%.3f", info["stock_code"], info["score"])

    logger.info("[공시패턴] 후보 %d개 탐지", len(results))
    return results


# ---------------------------------------------------------------------------
# 탐지기 4: 즉각 공시 이벤트 시그널 (P3 — 통계 없이 이벤트 발생 즉시)
# ---------------------------------------------------------------------------

# 즉각 급등 가능성이 높은 공시 이벤트 키워드 → 시그널 점수 매핑
# report_name에 키워드 포함 시 해당 점수를 immediate_disclosure_score로 부여
# @MX:NOTE: [AUTO] 키워드는 DART 공시 표준 명칭 기준. 추가 이벤트는 이 목록에 append
# @MX:NOTE: [AUTO] DART 공시에서 · 는 ㆍ(U+318D 한국어 아래아) 사용 — 두 형태 모두 포함
_IMMEDIATE_EVENT_PATTERNS: list[tuple[str, float]] = [
    # 자사주 소각: 유통 주식 수 감소 → 강한 주가 부양 효과
    ("자기주식소각", 0.90),
    ("자기주식 소각", 0.90),
    ("주식소각결정", 0.90),      # DART 실제 명칭: "주식소각결정"
    ("보통주식소각", 0.88),
    # 단일판매·공급계약 수주: DART는 ㆍ(U+318D) 사용 — 두 형태 등록
    ("단일판매ㆍ공급계약체결", 0.82),  # DART 실제 명칭 (ㆍ U+318D)
    ("단일판매·공급계약체결", 0.82),   # 중간점(·) 변형 대비
    ("수주계약체결", 0.78),
    # 흡수합병·합병 결정: 피합병법인 기준 인수 프리미엄 기대
    ("흡수합병결정", 0.82),
    ("흡수합병", 0.80),
    ("합병결정", 0.78),
    # 자사주 취득 결정: 소각 전 단계 — 덜 강하지만 주주환원 신호
    ("자기주식취득결정", 0.70),
    ("자기주식 취득 결정", 0.70),
]

# SPEC-AI-066 REQ-003: "positive-or-stronger" 감성 기준 (positive=0.7)
_ACQUISITION_MIN_SENTIMENT = 0.7


def _is_acquisition_exempt_disclosure(
    db: Session,
    stock_id: int,
    combined: str,
    config: SurgeDetectionConfig,
) -> bool:
    """SPEC-AI-066 REQ-003: 페널티 대상 공시가 전략적 인수 호재 맥락인지 판정한다.

    3중 조건 동시 충족 시에만 예외(부분 완화) 적용:
      (1) 인수/합병/경영권 키워드가 공시 텍스트(report_name+ai_summary)에 존재
      (2) 종목의 최근 뉴스 감성이 positive 이상 (>= 0.7)
      (3) 당일 change_rate >= 0 (하락 중 아님)

    스위치(catalyst_conviction.enabled / acquisition_exemption_enabled)가 하나라도 off면 False.
    하나라도 불충족이면 False → SPEC-AI-028 전면 페널티(0.3) 유지.

    # @MX:NOTE: [AUTO] SPEC-AI-066 REQ-003 — 부실 매각형 최대주주변경은 페널티 유지, 인수 호재만 부분완화
    # @MX:SPEC: SPEC-AI-066 REQ-AI066-003
    """
    disc_filter = config.disclosure_type_filter
    catalyst = config.catalyst_conviction
    if not (catalyst.enabled and disc_filter.acquisition_exemption_enabled):
        return False
    # (1) 인수 키워드
    if not any(kw in combined for kw in catalyst.acquisition_keywords):
        return False
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if stock is None:
        return False
    # (3) change_rate >= 0
    _price = None
    try:
        _price = _fetch_price_change_sync(stock.stock_code)
    except Exception:
        _price = None
    _change_rate = _price.get("change_rate") if _price else None
    if _change_rate is None or _change_rate < 0:
        return False
    # (2) positive 이상 뉴스 감성
    from app.models.news_relation import NewsStockRelation as _NSR
    _cfg = config.disclosure_pattern
    _cutoff = (datetime.now(timezone.utc) - timedelta(hours=_cfg.disclosure_window_hours)).replace(tzinfo=None)
    _sent_rows = (
        db.query(NewsArticle.sentiment)
        .join(_NSR, _NSR.news_id == NewsArticle.id)
        .filter(
            _NSR.stock_id == stock_id,
            NewsArticle.collected_at >= _cutoff,
        )
        .all()
    )
    _max_sent = max((_positive_sentiment_score(r[0]) for r in _sent_rows), default=0.0)
    if _max_sent < _ACQUISITION_MIN_SENTIMENT:
        return False
    return True


def detect_immediate_disclosure_signal(
    db: Session,
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """즉각 공시 이벤트(자사주 소각, 수주, 합병) 기반 급등 후보 탐지 (P3).

    과거 통계 없이 공시 발생 즉시 시그널을 생성한다.
    _IMMEDIATE_EVENT_PATTERNS에 정의된 키워드가 report_name에 포함된 공시를 조회해
    해당 종목에 즉각 시그널 점수(immediate_disclosure_score)를 부여한다.

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정

    Returns:
        SurgeCandidate 목록 (immediate_disclosure_score 채워짐)
    """
    cfg = config.disclosure_pattern
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=cfg.disclosure_window_hours)
    cutoff_str = cutoff_dt.strftime("%Y%m%d")

    # 최근 공시 조회 (stock_id 연결된 것만)
    recent_disclosures = (
        db.query(Disclosure)
        .filter(
            Disclosure.rcept_dt >= cutoff_str,
            Disclosure.stock_id.isnot(None),
        )
        .all()
    )

    # 종목별 최고 시그널 점수 집계
    stock_scores: dict[int, dict] = {}
    # SPEC-AI-028 REQ-001: 페널티 적용 종목 추적 (bearish sentiment 설정용)
    penalized_stocks: set[int] = set()

    for disc in recent_disclosures:
        rname = disc.report_name or ""
        ai_sum = disc.ai_summary or ""
        combined = rname + " " + ai_sum

        # REQ-AI028-001: 역신호 키워드 사전 필터 — 제외 키워드 우선 체크
        # @MX:NOTE: [AUTO] SPEC-AI-028 — 악재 공시 사전 차단. 제외 키워드 우선 체크
        disc_filter = config.disclosure_type_filter
        if any(kw in combined for kw in disc_filter.exclusion_patterns):
            logger.debug("[즉각공시] %s 역신호 제외: %s", disc.stock_id, rname[:30])
            continue

        penalty_applied = any(kw in combined for kw in disc_filter.penalty_patterns)

        best_score = 0.0
        for keyword, score in _IMMEDIATE_EVENT_PATTERNS:
            if keyword in rname:
                best_score = max(best_score, score)
        if best_score == 0.0:
            continue

        if penalty_applied:
            # SPEC-AI-066 REQ-003: 전략적 인수 호재 맥락이면 페널티 부분완화(0.3→0.7), bearish 표기도 해제.
            # 부실 매각/경영권 분쟁성(호재 근거 없음)은 SPEC-AI-028 전면 페널티(0.3)+bearish 유지.
            _exempt = (
                disc.stock_id is not None
                and _is_acquisition_exempt_disclosure(db, disc.stock_id, combined, config)
            )
            _factor = disc_filter.acquisition_penalty_factor if _exempt else disc_filter.penalty_factor
            best_score = round(best_score * _factor, 4)
            logger.debug(
                "[즉각공시] %s 페널티 적용 factor=%.2f exempt=%s (%.3f)",
                disc.stock_id, _factor, _exempt, best_score,
            )
            if disc.stock_id is not None and not _exempt:
                penalized_stocks.add(disc.stock_id)

        if disc.stock_id not in stock_scores or stock_scores[disc.stock_id]["score"] < best_score:
            stock = db.query(Stock).filter(Stock.id == disc.stock_id).first()
            if stock:
                stock_scores[disc.stock_id] = {
                    "score": best_score,
                    "stock_code": stock.stock_code,
                    "stock_name": stock.name,
                    "report_name": rname,
                }

    # P3: 대형주 공시 가중치 — 시총 상위 종목 1.2배 배율
    # @MX:NOTE: [AUTO] market_cap 단위는 억원 — 5조=50,000억원 기준으로 대형주 판별
    # KOSPI 시총 상위 ~50개 종목이 대략 50,000억원 이상
    _LARGE_CAP_THRESHOLD_EOKWON = 50_000  # 50,000억원 = 5조원
    _LARGE_CAP_MULTIPLIER = 1.2

    for stock_id, info in stock_scores.items():
        stock = db.query(Stock).filter(Stock.stock_code == info["stock_code"]).first()
        if stock and stock.market_cap and stock.market_cap >= _LARGE_CAP_THRESHOLD_EOKWON:
            old_score = info["score"]
            info["score"] = min(1.0, info["score"] * _LARGE_CAP_MULTIPLIER)
            logger.info(
                "[즉각공시] %s 대형주 배율 적용 %.3f→%.3f",
                info["stock_code"], old_score, info["score"],
            )

    results: list[SurgeCandidate] = []
    for stock_id, info in stock_scores.items():
        # SPEC-AI-028 REQ-001: 페널티 적용 종목은 bearish, 나머지는 bullish
        sentiment = "bearish" if stock_id in penalized_stocks else "bullish"
        results.append(
            SurgeCandidate(
                stock_code=info["stock_code"],
                stock_name=info["stock_name"],
                immediate_disclosure_score=info["score"],
                active_detectors=["immediate_disclosure"],
                disclosure_sentiment=sentiment,
            )
        )
        logger.info(
            "[즉각공시] %s '%s' → 시그널점수=%.3f",
            info["stock_code"],
            info["report_name"][:30],
            info["score"],
        )

    logger.info("[즉각공시] 후보 %d개 탐지", len(results))
    return results


# ---------------------------------------------------------------------------
# M5: 앙상블 스코어링
# ---------------------------------------------------------------------------

def compute_ensemble_score(candidate: SurgeCandidate, config: SurgeDetectionConfig) -> float:
    """앙상블 스코어를 계산한다 (AC-SURGE-004).

    각 탐지기 점수에 설정 가중치를 곱해 합산한 뒤,
    활성 그룹 수에 따른 컨센서스 배율을 적용한다.

    # @MX:NOTE: [AUTO] 컨센서스 배율: 활성 그룹 1/2/3개 → 1.00/1.30/1.55
    # @MX:NOTE: [AUTO] SPEC-AI-018 REQ-009: news(theme+combo)/disclosure/technical 3개 그룹으로 묶어
    #           동일 이벤트 중복 보상 방지 (기존 탐지기 개별 카운트 → 그룹 단위 카운트)
    # @MX:SPEC: SPEC-AI-014 REQ-004, SPEC-AI-018 REQ-009

    Args:
        candidate: SurgeCandidate 객체
        config: SurgeDetectionConfig 설정

    Returns:
        0.0~1.0 범위의 앙상블 점수
    """
    w = config.ensemble.weights
    # P3: immediate_disclosure_score와 pattern_score 중 높은 값을 공시 가중치에 적용
    best_disclosure_score = max(candidate.pattern_score, candidate.immediate_disclosure_score)
    weighted_sum = (
        w.theme_cluster * candidate.theme_cluster_score
        + w.volume_news_combo * candidate.combo_score
        + w.disclosure_pattern * best_disclosure_score
        + w.legacy_detectors * candidate.legacy_score
        # SPEC-AI-039 REQ-039-002: 뉴스 지연 반응 점수 추가
        + w.news_delayed * candidate.news_delayed_score
        # 거래량 폭발 탐지기 점수 추가
        + w.volume_breakout * candidate.volume_breakout_score
        # SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기 점수 추가 (가중치 0.12)
        + w.momentum_continuation * candidate.momentum_continuation_score
    )

    # SPEC-AI-018 REQ-009: 탐지기 그룹 단위 컨센서스 배율 (동일 이벤트 중복 보상 방지)
    # news 그룹(theme+combo)은 모두 뉴스 이벤트에 반응 → 동일 그룹으로 묶음
    # disclosure 그룹: best_disclosure_score (공시 이벤트)
    # technical 그룹: legacy_score + volume_breakout + momentum_continuation (기술적 신호)
    detector_groups = {
        "news": [candidate.theme_cluster_score, candidate.combo_score],
        "disclosure": [best_disclosure_score],
        "technical": [
            candidate.legacy_score,
            candidate.volume_breakout_score,
            candidate.momentum_continuation_score,
        ],
    }
    active_groups = sum(
        1 for scores in detector_groups.values() if any(s > 0 for s in scores)
    )

    # SPEC-AI-017 REQ-002: 컨센서스 배율을 config에서 읽어 적용
    if active_groups >= 3:
        multiplier = config.ensemble.consensus_multiplier_three_plus
    elif active_groups == 2:
        multiplier = config.ensemble.consensus_multiplier_two
    else:
        multiplier = 1.00

    final_score = min(1.0, weighted_sum * multiplier)

    logger.debug(
        "[앙상블] code=%s weighted_sum=%.4f consensus=%.2f final=%.4f (active_groups=%d)",
        candidate.stock_code,
        weighted_sum,
        multiplier,
        final_score,
        active_groups,
    )

    return final_score


def _recent_surge_penalty(score: float, price_5d_trend: float | None) -> float:
    """5일 수익률 기반 최근 급등 페널티를 적용한다 (REQ-AI018-005).

    Args:
        score: 적용 전 앙상블 점수
        price_5d_trend: 최근 5일 수익률(%). None이면 페널티 없음.

    Returns:
        페널티 적용 후 점수

    # @MX:NOTE: [AUTO] SPEC-AI-018 REQ-005: 최근 급등 페널티 — 이미 급등한 종목 재선정 방지
    # @MX:SPEC: SPEC-AI-018
    """
    if price_5d_trend is None:
        return score
    if price_5d_trend > 20.0:
        return score * 0.6
    if price_5d_trend > 12.0:
        return score * 0.8
    return score


# @MX:ANCHOR: [AUTO] detect_news_delayed_response — 뉴스 지연 반응 탐지기 진입점
# @MX:REASON: gather_surge_candidates, 테스트, 외부 API 총 3곳 이상에서 호출될 예정인 공개 탐지기
# @MX:SPEC: SPEC-AI-039 REQ-039-002
def detect_news_delayed_response(
    db: "Session",
    config: "SurgeDetectionConfig",
    market_regime: str = "NEUTRAL",
) -> list[SurgeCandidate]:
    """최근 24-72시간 내 고임팩트 뉴스 발생 종목을 탐지한다 (지연 반응 패턴).

    한올바이오파마 사례: 6/3 "1조 로열티" 뉴스 → 6/5 +6.5% 급등 패턴 포착용.
    당일(24h 이내) 동일 종목 기사 있으면 skip (즉각 반응은 다른 탐지기가 처리).
    DB 쿼리 실패 시 조용히 빈 목록 반환 (기존 탐지기 패턴 준수).

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig (high_impact_news 설정 포함)
        market_regime: 시장 레짐 (현재 미사용, 향후 레짐별 감도 조정용)

    Returns:
        news_delayed_score가 채워진 SurgeCandidate 목록
    """
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation
    from app.models.stock import Stock

    try:
        now = datetime.now(timezone.utc)
        # 24-72h 창: 당일 뉴스(24h 이내)는 다른 탐지기가 처리하므로 제외
        window_start = now - timedelta(hours=72)
        window_end = now - timedelta(hours=24)

        # 1. 24-72h 이내 발행된 기사 조회
        articles = (
            db.query(NewsArticle)
            .filter(
                NewsArticle.published_at >= window_start,
                NewsArticle.published_at < window_end,
            )
            .all()
        )

        if not articles:
            return []

        hi_cfg = config.high_impact_news

        results: list[SurgeCandidate] = []
        # 종목 코드 → 최고 점수 병합용
        best_scores: dict[str, tuple[float, str, str]] = {}  # code → (score, name, stock_code)

        # 2. 고임팩트 키워드 필터 + news_stock_relations 조회
        for article in articles:
            search_text = article.title or ""
            if article.ai_summary:
                search_text = search_text + " " + article.ai_summary

            multiplier = hi_cfg.get_multiplier(search_text)
            if multiplier == 1.0:
                # 고임팩트 키워드 없는 기사는 skip
                continue

            # 3. 해당 기사와 연결된 종목 추출
            relations = (
                db.query(NewsStockRelation)
                .filter(
                    NewsStockRelation.news_id == article.id,
                    NewsStockRelation.stock_id.isnot(None),
                )
                .all()
            )

            for rel in relations:
                # 4. 당일 24h 이내 동일 종목 기사 있으면 skip (즉각 반응 탐지기에서 처리)
                today_news = (
                    db.query(NewsArticle)
                    .filter(
                        NewsArticle.published_at >= window_end,  # 최근 24h
                        NewsArticle.relations.any(
                            NewsStockRelation.stock_id == rel.stock_id
                        ),
                    )
                    .first()
                )
                if today_news:
                    continue

                # 5. 종목 정보 조회
                stock = db.query(Stock).filter(Stock.id == rel.stock_id).first()
                if not stock:
                    continue

                # recency_factor: 뉴스 발행 시각에 따른 가중 (48h 전이 최고)
                hours_ago = (now - article.published_at).total_seconds() / 3600
                if hours_ago <= 48:
                    recency_factor = 1.2
                else:
                    recency_factor = 1.0

                # 6. score 산출: base(0.3) × multiplier × recency_factor
                base_score = 0.3
                score = round(min(1.0, base_score * multiplier * recency_factor), 4)

                # 최고 점수 종목만 보관 (동일 종목 복수 기사 시 병합)
                existing = best_scores.get(stock.stock_code)
                if existing is None or score > existing[0]:
                    best_scores[stock.stock_code] = (score, stock.name, stock.stock_code)

        # 7. 임계값(0.25) 이상 종목 SurgeCandidate 변환
        for stock_code, (score, stock_name, _) in best_scores.items():
            if score >= 0.25:
                results.append(
                    SurgeCandidate(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        news_delayed_score=score,
                        active_detectors=["news_delayed"],
                    )
                )

        logger.info("[뉴스지연] %d개 후보 반환 (24-72h 고임팩트 뉴스 기반)", len(results))
        return results

    except Exception as e:
        # DB 쿼리 실패 시 조용히 빈 목록 반환 (기존 탐지기 패턴 준수)
        logger.warning("[뉴스지연] 탐지 실패: %s", e)
        return []


# @MX:NOTE: [AUTO] SPEC-AI-061 — sector_contagion 예방 게이트: 섹터 하락 비율 > threshold 종목 억제
# @MX:SPEC: SPEC-AI-061 REQ-AI061-D01
def _compute_sector_decline_ratio(
    db: Session,
    sector_id: int,
    prev_trading_date: date,
    sector_min_stocks: int = 5,
) -> float | None:
    """전날 섹터 하락 비율을 계산한다.

    Args:
        db: SQLAlchemy 동기 세션
        sector_id: 섹터 ID
        prev_trading_date: 조회 기준 전일 날짜
        sector_min_stocks: 통계 유효성 최소 종목 수 (미만이면 None 반환)

    Returns:
        하락 비율 (0.0 ~ 1.0), 데이터 부족 또는 오류 시 None (fail-open)
    """
    try:
        from app.models.surge_actual_outcome import SurgeActualOutcome

        rows = (
            db.query(SurgeActualOutcome.change_rate)
            .join(Stock, Stock.stock_code == SurgeActualOutcome.stock_code)
            .filter(
                Stock.sector_id == sector_id,
                SurgeActualOutcome.trading_date == prev_trading_date,
            )
            .all()
        )
        total_count = len(rows)
        # 섹터 내 종목 수 부족 — 통계적으로 유의미하지 않으므로 fail-open
        if total_count < sector_min_stocks:
            return None
        decline_count = sum(1 for r in rows if r.change_rate is not None and r.change_rate < 0)
        return decline_count / total_count
    except Exception as e:
        logger.warning("[sector_contagion] 섹터 하락 비율 조회 실패 (fail-open): %s", e)
        return None


# @MX:NOTE: [AUTO] SPEC-AI-012 앙상블 파이프라인 진입점 — fund_manager._gather_surge_candidates에서 호출
# @MX:SPEC: SPEC-AI-012
def gather_surge_candidates(
    db: Session,
    recent_news: list,
    config: SurgeDetectionConfig,
    legacy_candidates: list[dict],
    market_regime: str = "NEUTRAL",
) -> list[SurgeCandidate]:
    """모든 탐지기를 실행하고 앙상블 점수로 후보를 선정한다 (AC-SURGE-004).

    3개 탐지기 결과를 종목 코드 기준으로 병합한 후,
    레거시 탐지기 점수를 추가하여 앙상블 점수 >= min_score_for_signal 인 후보만 반환.

    Args:
        db: SQLAlchemy 동기 세션
        recent_news: 미사용 (detect_theme_news_cluster가 DB 직접 조회)
        config: SurgeDetectionConfig 설정
        legacy_candidates: _gather_leading_candidates 결과 (dict 목록)

    Returns:
        앙상블 점수 기준 정렬된 SurgeCandidate 목록
    """
    # SPEC-AI-067 REQ-005: 스캔 사이클 시작 시 실시간 거래량 조회 예산 카운터 초기화.
    # combo/breakout/PoolB가 이 스캔 안에서 소비하는 모바일 실시간 조회를 max_live_fetches_per_scan로 유계.
    _reset_live_volume_budget()

    # 각 탐지기 실행
    theme_results = detect_theme_news_cluster(db, [], config)
    combo_results = detect_volume_surge_news_combo(db, config, market_regime=market_regime)
    pattern_results = detect_disclosure_surge_pattern(db, config)
    # P3: 즉각 공시 이벤트 탐지기 (자사주 소각, 수주, 합병)
    immediate_results = detect_immediate_disclosure_signal(db, config)
    # SPEC-AI-039 REQ-039-002: 뉴스 지연 반응 탐지기 (24-72h 고임팩트 뉴스 기반)
    delayed_results = detect_news_delayed_response(db, config, market_regime=market_regime)

    # 종목 코드 기준 병합
    merged: dict[str, SurgeCandidate] = {}

    for candidate in theme_results:
        merged[candidate.stock_code] = candidate

    for candidate in combo_results:
        if candidate.stock_code in merged:
            existing = merged[candidate.stock_code]
            existing.combo_score = candidate.combo_score
            if "volume_news_combo" not in existing.active_detectors:
                existing.active_detectors.append("volume_news_combo")
        else:
            merged[candidate.stock_code] = candidate

    for candidate in pattern_results:
        if candidate.stock_code in merged:
            existing = merged[candidate.stock_code]
            existing.pattern_score = candidate.pattern_score
            if "disclosure_pattern" not in existing.active_detectors:
                existing.active_detectors.append("disclosure_pattern")
        else:
            merged[candidate.stock_code] = candidate

    # P3: 즉각 공시 이벤트 병합
    for candidate in immediate_results:
        if candidate.stock_code in merged:
            existing = merged[candidate.stock_code]
            existing.immediate_disclosure_score = candidate.immediate_disclosure_score
            if "immediate_disclosure" not in existing.active_detectors:
                existing.active_detectors.append("immediate_disclosure")
        else:
            merged[candidate.stock_code] = candidate

    # SPEC-AI-039 REQ-039-002: 뉴스 지연 반응 탐지기 결과 병합
    for candidate in delayed_results:
        if candidate.stock_code in merged:
            existing = merged[candidate.stock_code]
            existing.news_delayed_score = candidate.news_delayed_score
            if "news_delayed" not in existing.active_detectors:
                existing.active_detectors.append("news_delayed")
        else:
            merged[candidate.stock_code] = candidate

    # 거래량 폭발 탐지기 결과 병합 (뉴스 없이 거래량만으로 소형주 탐지)
    breakout_results = detect_volume_breakout(db, config)
    for candidate in breakout_results:
        if candidate.stock_code in merged:
            existing = merged[candidate.stock_code]
            existing.volume_breakout_score = candidate.volume_breakout_score
            if "volume_breakout" not in existing.active_detectors:
                existing.active_detectors.append("volume_breakout")
        else:
            merged[candidate.stock_code] = candidate

    # SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기 결과 병합
    momentum_results = detect_momentum_continuation(db, config, market_regime=market_regime)
    for candidate in momentum_results:
        if candidate.stock_code in merged:
            existing = merged[candidate.stock_code]
            existing.momentum_continuation_score = candidate.momentum_continuation_score
            if "momentum_continuation" not in existing.active_detectors:
                existing.active_detectors.append("momentum_continuation")
        else:
            merged[candidate.stock_code] = candidate

    # SPEC-AI-065 REQ-2: 스캔 유니버스 entry_pool 태깅
    # 기존 탐지기 결과로 entry_pool='existing' 설정, Pool A/B/C는 별도 탐지기에서 태깅됨
    existing_codes = set(merged.keys())
    try:
        _universe_codes, _entry_pool_map, _pool_counts = build_scan_universe(
            db, config, existing_codes=existing_codes
        )
        # 기존 merged 후보에 entry_pool 태깅 (Pool A/B/C 소속이면 갱신)
        for code, candidate in merged.items():
            pool_tag = _entry_pool_map.get(code, "existing")
            if candidate.entry_pool == "existing":
                candidate.entry_pool = pool_tag

        # SPEC-AI-065 REQ-5 버그픽스: 라이브 시그널 생성(10:00/15:20 KST) 중 계산된
        # 이 pool_counts가 실제 예측 시점의 스캔 유니버스 집계다. 별도 16:00 KST
        # 사전 빌드 잡(_run_surge_universe_build)의 결과는 폐기되는 값이라 평가용으로
        # 부적절하므로 사용하지 않는다. 날짜별로 저장해 두면 T+1의 18:30 평가 잡이
        # T-1(예측일) 값을 읽어 evaluate_surge_predictions(pool_counts=...)에 전달한다.
        try:
            from app.services.surge_universe_pool_service import (
                persist_pool_counts,
                persist_universe_members,
            )

            persist_pool_counts(
                db,
                date.today(),
                {
                    "pool_a": _pool_counts.get("pool_a", 0),
                    "pool_b": _pool_counts.get("pool_b", 0),
                    "pool_c": _pool_counts.get("pool_c", 0),
                    "scan_universe_size": len(_universe_codes),
                },
            )

            # @MX:NOTE: [AUTO] SPEC-AI-068 REQ-001 — 유니버스 멤버 영속화 훅. 위
            # persist_pool_counts와 동일 트랜잭션(동일 try 블록, 커밋 시점 공유)에서
            # 종목코드+entry_pool을 일자당 replace로 기록한다. build_scan_universe 자체의
            # 우선순위/상한 로직은 변경하지 않으며, 이미 확정된 _universe_codes/_entry_pool_map
            # 결과만 저장한다(Scannable Recall/Coverage 계산용, SPEC-AI-068).
            # @MX:SPEC: SPEC-AI-068 REQ-AI068-001
            persist_universe_members(
                db,
                date.today(),
                _universe_codes,
                _entry_pool_map,
            )
        except Exception as _pe:
            logger.warning("[스캔유니버스] pool_counts/유니버스멤버 영속화 실패 (무시): %s", _pe)
    except Exception as _ue:
        logger.warning("[스캔유니버스] 유니버스 빌드 실패 (무시): %s", _ue)
        try:
            db.rollback()
        except Exception:
            pass
        _pool_counts = {"pool_a": 0, "pool_b": 0, "pool_c": 0}

    # 레거시 탐지기 점수 계산
    # @MX:NOTE: legacy_score = min(1.0, 레거시 탐지기 발동 수 / 4)
    #           leading_signals 키로 몇 개의 선행 탐지기가 발동했는지 확인
    legacy_score_map: dict[str, float] = {}
    # SPEC-AI-018 REQ-005: price_5d_trend 조회용 룩업 딕셔너리 (종목코드 → legacy dict)
    legacy_lookup: dict[str, dict] = {}
    for lc in legacy_candidates:
        code = lc.get("code") or lc.get("stock_code")
        if not code:
            continue
        signals = lc.get("leading_signals", [])
        num_triggered = len(signals) if signals else 1  # 후보로 있으면 최소 1개
        legacy_score_map[code] = min(1.0, num_triggered / 4)
        legacy_lookup[code] = lc

    for code, candidate in merged.items():
        if code in legacy_score_map:
            candidate.legacy_score = legacy_score_map[code]
            if "legacy" not in candidate.active_detectors:
                candidate.active_detectors.append("legacy")

    # SPEC-AI-065 REQ-1: z-score 정규화 적용
    # 기준선(rolling_mean, rolling_std)이 충분한 경우 절대값 대신 z-score로 정규화
    _DETECTOR_SCORE_ATTRS = [
        ("theme_cluster", "theme_cluster_score"),
        ("volume_news_combo", "combo_score"),
        ("disclosure_pattern", "pattern_score"),
        ("news_delayed", "news_delayed_score"),
        ("volume_breakout", "volume_breakout_score"),
        ("momentum_continuation", "momentum_continuation_score"),
    ]
    try:
        from app.services.surge_baseline_service import (
            get_baselines,
            compute_zscore,
            zscore_to_score,
            Observation,
            update_baselines,
        )

        _all_codes = list(merged.keys())
        _all_detectors = [d for d, _ in _DETECTOR_SCORE_ATTRS]
        _baselines = get_baselines(db, _all_codes, _all_detectors)

        _observations: list[Observation] = []
        _min_samples = config.zscore_min_baseline_samples

        for code, candidate in merged.items():
            _zscore_meta: dict[str, str] = {}
            for det_name, score_attr in _DETECTOR_SCORE_ATTRS:
                raw = getattr(candidate, score_attr)
                baseline = _baselines.get((code, det_name))
                _observations.append(Observation(code, det_name, raw))

                if baseline and raw > 0:
                    z = compute_zscore(raw, baseline, min_samples=_min_samples)
                    if z is not None:
                        normalized = zscore_to_score(z)
                        setattr(candidate, score_attr, normalized)
                        _zscore_meta[det_name] = f"z={z:.2f}→{normalized:.3f}"
                    else:
                        _zscore_meta[det_name] = "cold_start"
                elif raw > 0:
                    _zscore_meta[det_name] = "no_baseline"

            if _zscore_meta:
                logger.debug("[z-score] %s %s", code, _zscore_meta)

        # 오늘 관측값으로 기준선 업데이트 (비동기 없이 동기 flush)
        update_baselines(db, _observations)

    except Exception as _ze:
        logger.debug("[z-score] 기준선 적용 실패 (무시): %s", _ze)

    # SPEC-AI-038 성능 패치 3단계: price_5d_trend 조회(HTTP) 전 상위 N개로 사전 필터
    # 이유: 테마클러스터가 수백 개 후보 반환 시 모든 종목 HTTP 호출 → 300s 타임아웃 초과
    # 수정: 기존 점수(HTTP 없음) 기준으로 상위 N개만 남기고 나머지 제거
    # 2026-06-30: 30→50으로 확대 — KOSDAQ 2페이지 추가로 후보 증가, idle_in_transaction 타임아웃 제거로 여유 생김
    _MAX_PRICE_FETCH_CANDIDATES = 50
    if len(merged) > _MAX_PRICE_FETCH_CANDIDATES:
        _original_count = len(merged)
        def _pre_score(c: SurgeCandidate) -> float:
            # 앙상블 가중치 기준으로 모든 탐지기 반영 (SPEC-AI-065: volume_breakout/momentum_continuation 추가)
            return (
                c.theme_cluster_score * 0.19
                + c.combo_score * 0.25
                + c.pattern_score * 0.14
                + c.news_delayed_score * 0.11
                + c.volume_breakout_score * 0.11
                + c.momentum_continuation_score * 0.12
                + c.immediate_disclosure_score * 0.08
            )
        _sorted_codes = sorted(merged.keys(), key=lambda code: _pre_score(merged[code]), reverse=True)
        merged = {code: merged[code] for code in _sorted_codes[:_MAX_PRICE_FETCH_CANDIDATES]}
        logger.info(
            "[급등탐지] price_5d_trend 조회 전 상위 %d개로 사전 필터 (성능 패치, 원본=%d개)",
            _MAX_PRICE_FETCH_CANDIDATES,
            _original_count,
        )

    # SPEC-AI-018 REQ-005 fix: price_5d_trend를 candidate에 직접 채움
    # legacy_candidates=[]인 run_surge_signal_generation 경로에서도 페널티가 작동하도록
    from app.services.naver_finance import fetch_stock_price_history_sync as _fetch_ph
    for code, candidate in merged.items():
        if code in legacy_lookup:
            candidate.price_5d_trend = legacy_lookup[code].get("price_5d_trend")
        else:
            try:
                _hist = _fetch_ph(code, pages=1)
                if len(_hist) >= 5 and _hist[4].close_price > 0:
                    candidate.price_5d_trend = round(
                        (_hist[0].close_price - _hist[4].close_price)
                        / _hist[4].close_price * 100,
                        2,
                    )
            except Exception:
                pass

    # SPEC-AI-030 Gate 4 (REQ-AI030-004): combo 단독 신호 buy-pool 미포함
    # @MX:NOTE: [AUTO] SPEC-AI-030 — combo_score > 0이고 다른 탐지기 점수가 모두 0이면 buy-pool 제외
    # @MX:SPEC: SPEC-AI-030 REQ-AI030-004
    _guard = config.combo_chase_guard
    if _guard.enabled and _guard.require_companion_detector:
        _combo_only_codes: list[str] = []
        for _code, _cand in merged.items():
            if (
                _cand.combo_score > 0
                and _cand.theme_cluster_score == 0.0
                and _cand.immediate_disclosure_score == 0.0
                and _cand.pattern_score == 0.0
            ):
                _combo_only_codes.append(_code)
                logger.info("[앙상블] %s combo단독 제외", _code)
        for _code in _combo_only_codes:
            del merged[_code]

    # 앙상블 점수 계산 및 임계값 필터링
    qualified: list[SurgeCandidate] = []
    qualified_codes: set[str] = set()

    # SPEC-AI-017 REQ-001: 레짐별 임계값 적용 (없으면 min_score_for_signal 사용)
    effective_threshold = config.ensemble.regime_thresholds.get(
        market_regime, config.ensemble.min_score_for_signal
    )
    logger.info(
        "[앙상블] 레짐=%s 유효임계=%.2f (기본=%.2f)",
        market_regime, effective_threshold, config.ensemble.min_score_for_signal,
    )

    for candidate in merged.values():
        score = compute_ensemble_score(candidate, config)
        # SPEC-AI-018 REQ-005: 최근 급등 페널티 적용 (앙상블 경로)
        score = _recent_surge_penalty(score, candidate.price_5d_trend)
        if score >= effective_threshold:
            qualified.append(candidate)
            qualified_codes.add(candidate.stock_code)

    # P3: 즉각 공시 이벤트 강도 >= config 임계값이면 앙상블 임계값 우회 포함
    # SPEC-AI-018 REQ-001: 하드코딩(0.70) → config.ensemble.immediate_disclosure_bypass_threshold (0.85)
    # 자사주 소각(0.90), 수주(0.82), 합병(0.82) 등은 다른 탐지기 없이도 즉각 시그널
    _immediate_bypass_threshold = config.ensemble.immediate_disclosure_bypass_threshold
    for candidate in merged.values():
        if (candidate.stock_code not in qualified_codes
                and candidate.immediate_disclosure_score >= _immediate_bypass_threshold):
            # SPEC-AI-018 REQ-005: 즉각 공시 우회 경로에도 급등 페널티 적용
            _bypass_score = candidate.immediate_disclosure_score
            _bypass_score = _recent_surge_penalty(_bypass_score, candidate.price_5d_trend)
            if _bypass_score <= 0:
                continue
            qualified.append(candidate)
            qualified_codes.add(candidate.stock_code)
            logger.info(
                "[즉각공시] 앙상블 임계 우회: %s (immediate_score=%.3f, 페널티후=%.3f)",
                candidate.stock_code,
                candidate.immediate_disclosure_score,
                _bypass_score,
            )

    # SPEC-AI-017 REQ-003: 강한 단일 신호 우회 (theme/combo >= bypass 임계값)
    # 즉각 공시 bypass(0.85)와 대칭 — 강한 테마/거래량 신호 구제
    # @MX:NOTE: [AUTO] theme_cluster 단독 bypass는 SPEC-AI-030 combo 단독 차단과 동일한 원칙으로
    # companion detector(combo/disclosure/volume_breakout > 0.1) 없으면 우회 불허.
    # 이유: theme 단독 0.9+는 대형주 섹터 테마에서 자주 발생하나 10%+ 급등 예측력 없음.
    # combo/volume_breakout과 동반 시에만 유효한 신호.
    _bypass = config.ensemble.strong_single_bypass_threshold
    _companion_threshold = 0.1
    for candidate in merged.values():
        _has_companion = (
            candidate.combo_score > _companion_threshold
            or candidate.immediate_disclosure_score > _companion_threshold
            or candidate.volume_breakout_score > _companion_threshold
        )
        if candidate.stock_code not in qualified_codes and (
            (candidate.theme_cluster_score >= _bypass and _has_companion)
            or candidate.combo_score >= _bypass
        ):
            # SPEC-AI-018 REQ-005: 강한 단일 신호 우회 경로에도 급등 페널티 적용
            _single_score = max(candidate.theme_cluster_score, candidate.combo_score)
            _single_score = _recent_surge_penalty(_single_score, candidate.price_5d_trend)
            if _single_score < _bypass:
                logger.info(
                    "[강한단일신호] 급등 페널티로 우회 차단: %s (페널티후=%.3f < %.3f)",
                    candidate.stock_code, _single_score, _bypass,
                )
                continue
            qualified.append(candidate)
            qualified_codes.add(candidate.stock_code)
            logger.info(
                "[강한단일신호] 앙상블 임계 우회: %s (theme=%.3f, combo=%.3f)",
                candidate.stock_code,
                candidate.theme_cluster_score,
                candidate.combo_score,
            )

    # SPEC-AI-063 REQ-063-001: 거래량 폭발 단독 bypass 경로 (Bypass Path 3)
    # volume_breakout_score >= threshold이면 앙상블 임계값 우회 → 소형주 standalone 시그널 허용
    # REQ-063-004: qualified_codes 가드로 중복 추가 방지 (앙상블 통과 / 다른 bypass 경로 이미 포함 종목 제외)
    # @MX:NOTE: [AUTO] SPEC-AI-063 — 거래량 폭발 단독 bypass. volume_breakout.volume_breakout_bypass_threshold로 제어
    # @MX:SPEC: SPEC-AI-063 REQ-063-001 REQ-063-004
    _vb_bypass_threshold = config.volume_breakout.volume_breakout_bypass_threshold
    for candidate in merged.values():
        if candidate.stock_code not in qualified_codes:
            if candidate.volume_breakout_score >= _vb_bypass_threshold:
                # REQ-063-003: composite_score는 앙상블 점수(~0.06)가 아닌 volume_breakout_score로 주입
                # @MX:WARN: [AUTO] SPEC-AI-063 — volume_breakout_score 직접 주입. max_score=0.50으로 스케일 상이
                # @MX:REASON: 앙상블 점수 사용 시 최대 0.06으로 min_score_for_signal(0.45) 미달 → composite_score 왜곡
                # @MX:SPEC: SPEC-AI-063 REQ-063-003
                candidate.bypass_composite_score = candidate.volume_breakout_score
                qualified.append(candidate)
                qualified_codes.add(candidate.stock_code)
                logger.info(
                    "[거래량폭발] 앙상블 임계 우회: %s (vb_score=%.3f >= threshold=%.3f)",
                    candidate.stock_code,
                    candidate.volume_breakout_score,
                    _vb_bypass_threshold,
                )

    # 앙상블 점수 내림차순 정렬
    qualified.sort(key=lambda c: compute_ensemble_score(c, config), reverse=True)

    if not qualified:
        logger.warning(
            "[앙상블] 최종 급등 후보 0개 (레짐=%s, 유효임계=%.2f, 전체탐지=%d개)",
            market_regime, effective_threshold, len(merged),
        )
    else:
        logger.info(
            "[앙상블] 최종 급등 후보 %d개 (레짐=%s, 유효임계=%.2f)",
            len(qualified), market_regime, effective_threshold,
        )

    # SPEC-AI-061 REQ-AI061-D01: sector_contagion 예방 게이트
    # 전날 섹터 하락 비율 초과 후보 제거
    _sector_decline_threshold: float = (
        getattr(config, "sector_contagion_decline_ratio", None) or 0.60
    )
    _sector_min_stocks: int = int(getattr(config, "sector_min_stocks", None) or 5)
    # 전날 영업일 계산 — 간단히 역일 기준 -1일 사용 (주말/공휴일 처리는 fail-open으로 커버)
    _prev_date: date = datetime.now(timezone.utc).date() - timedelta(days=1)

    if qualified:
        # 성능 최적화: 종목코드 → sector_id 일괄 조회 (N+1 쿼리 방지)
        _stock_sector_map: dict[str, int | None] = {
            row.stock_code: row.sector_id
            for row in db.query(Stock.stock_code, Stock.sector_id)
            .filter(Stock.stock_code.in_([c.stock_code for c in qualified]))
            .all()
        }

        _sector_filtered: list[SurgeCandidate] = []
        for _cand in qualified:
            _sid = _stock_sector_map.get(_cand.stock_code)
            if _sid is None:
                # 섹터 정보 없음 — fail-open (통과)
                _sector_filtered.append(_cand)
                continue
            _ratio = _compute_sector_decline_ratio(db, _sid, _prev_date, _sector_min_stocks)
            if _ratio is None:
                # 데이터 부족 또는 오류 — fail-open (통과)
                _sector_filtered.append(_cand)
                continue
            if _ratio > _sector_decline_threshold:
                # 섹터 하락 비율 초과 — 억제
                logger.info(
                    "sector_contagion 게이트: %s 제거 (섹터 하락비율=%.2f)",
                    _cand.stock_code,
                    _ratio,
                )
            else:
                _sector_filtered.append(_cand)

        if len(_sector_filtered) < len(qualified):
            logger.info(
                "[sector_contagion] 게이트 적용: %d개 → %d개 (임계=%.2f)",
                len(qualified),
                len(_sector_filtered),
                _sector_decline_threshold,
            )
        qualified = _sector_filtered

    return qualified


def surge_candidate_to_signal_metadata(
    candidate: SurgeCandidate,
    config: SurgeDetectionConfig,
) -> dict:
    """SurgeCandidate를 FundSignal.surge_metadata JSON으로 변환한다."""
    ensemble_score = compute_ensemble_score(candidate, config)
    return {
        "surge_probability_score": round(ensemble_score, 4),
        "surge_basis": candidate.active_detectors,
        "theme_cluster_score": round(candidate.theme_cluster_score, 4),
        "combo_score": round(candidate.combo_score, 4),
        "pattern_score": round(candidate.pattern_score, 4),
        "immediate_disclosure_score": round(candidate.immediate_disclosure_score, 4),
        "legacy_score": round(candidate.legacy_score, 4),
        "disclosure_sentiment": candidate.disclosure_sentiment,  # SPEC-AI-028 REQ-002
    }


# ---------------------------------------------------------------------------
# SPEC-AI-022: 테마 전파 시그널
# ---------------------------------------------------------------------------

def _get_peer_price_5d_trend(db: Session, stock_code: str) -> float | None:
    """피어 종목의 최근 5일 수익률을 조회한다.

    Naver Finance 히스토리에서 최신 2개 가격으로 5일 수익률 근사값 계산.
    조회 실패 시 None 반환 (호출부에서 안전하게 처리).
    """
    try:
        from app.services.naver_finance import fetch_stock_price_history_sync
        records = fetch_stock_price_history_sync(stock_code, pages=1)
        if records and len(records) >= 2:
            # Naver 데이터는 최신순 정렬: index 0=최신, index -1=가장 오래된
            latest = records[0].close
            oldest = records[-1].close
            if oldest > 0:
                return round((latest - oldest) / oldest * 100, 2)
    except Exception as e:
        logger.debug("[테마전파] %s 5일 수익률 조회 실패: %s", stock_code, e)
    return None


# @MX:ANCHOR: [AUTO] propagate_theme_group_signals — 테마 전파 시그널 생성 진입점
# @MX:REASON: fund_manager._gather_surge_candidates 완료 후 호출. 테마 그룹 관계 쿼리 + FundSignal 생성 복합 로직
# @MX:SPEC: SPEC-AI-022 REQ-001
def propagate_theme_group_signals(
    db: Session,
    qualified_candidates: list[SurgeCandidate],
    config: "ThemePropagationConfig",  # noqa: F821
) -> int:
    """SPEC-AI-022 REQ-001: 앵커 종목의 테마 클러스터 점수를 그룹 내 피어 종목으로 전파.

    - 앵커 theme_cluster_score >= config.anchor_score_threshold 조건 충족 시 전파
    - 피어 중 오늘 이미 시그널 있거나 price_5d_trend >= threshold 이면 스킵
    - 동일 피어에 복수 앵커가 전파 시 최고 점수 앵커의 시그널만 생성

    Args:
        db: SQLAlchemy 세션
        qualified_candidates: surge_candidate 자격 후보 목록
        config: ThemePropagationConfig

    Returns:
        생성된 theme_propagation 시그널 수
    """
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.models.theme_group import ThemeGroup, StockThemeGroup

    # 앵커 후보 필터링: theme_cluster_score >= 임계값
    anchors = [
        c for c in qualified_candidates
        if c.theme_cluster_score >= config.anchor_score_threshold
    ]
    if not anchors:
        return 0

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 오늘 이미 시그널이 있는 stock_id 집합 사전 수집 (쿼리 최소화)
    today_signal_stock_ids: set[int] = set()
    today_signals = (
        db.query(FundSignal.stock_id)
        .filter(FundSignal.created_at >= today_start)
        .distinct()
        .all()
    )
    for row in today_signals:
        today_signal_stock_ids.add(row[0])

    # 피어별 최고 앵커 점수 집계: {peer_stock_id: (max_score, anchor_stock_code)}
    peer_best: dict[int, tuple[float, str]] = {}

    for anchor in anchors:
        anchor_stock = db.query(Stock).filter(Stock.stock_code == anchor.stock_code).first()
        if not anchor_stock:
            continue

        # 앵커가 속한 테마 그룹 조회
        groups = (
            db.query(ThemeGroup)
            .join(StockThemeGroup, StockThemeGroup.theme_group_id == ThemeGroup.id)
            .filter(StockThemeGroup.stock_id == anchor_stock.id)
            .all()
        )

        for group in groups:
            # 그룹 내 피어 종목 조회 (앵커 자신 제외)
            peers = (
                db.query(Stock)
                .join(StockThemeGroup, StockThemeGroup.stock_id == Stock.id)
                .filter(
                    StockThemeGroup.theme_group_id == group.id,
                    Stock.id != anchor_stock.id,
                )
                .all()
            )

            for peer in peers:
                # 오늘 이미 시그널 있으면 스킵
                if peer.id in today_signal_stock_ids:
                    continue

                # 피어 5일 수익률 확인
                trend = _get_peer_price_5d_trend(db, peer.stock_code)
                if trend is not None and trend >= config.peer_price_trend_threshold:
                    logger.debug(
                        "[테마전파] %s 5일 수익률 %.1f%% (임계값 %.1f%%) 초과, 스킵",
                        peer.stock_code, trend, config.peer_price_trend_threshold,
                    )
                    continue

                # 복수 앵커 전파 시 최고 점수 보존
                current_best = peer_best.get(peer.id)
                if current_best is None or anchor.theme_cluster_score > current_best[0]:
                    peer_best[peer.id] = (anchor.theme_cluster_score, anchor.stock_code)

    # 피어별 theme_propagation 시그널 생성
    created_count = 0
    for peer_stock_id, (best_score, source_code) in peer_best.items():
        try:
            signal = FundSignal(
                stock_id=peer_stock_id,
                signal="buy",
                confidence=config.propagation_confidence,
                reasoning=(
                    f"[SPEC-AI-022 테마전파] 앵커 {source_code} "
                    f"theme_cluster_score={best_score:.3f} 전파"
                ),
                signal_type="theme_propagation",
                paper_executed=False,
                surge_metadata=None,
            )
            db.add(signal)
            db.flush()
            created_count += 1
            logger.info(
                "[테마전파] %d → theme_propagation 시그널 생성 (앵커=%s, score=%.3f)",
                peer_stock_id, source_code, best_score,
            )
        except Exception as e:
            db.rollback()
            logger.warning("[테마전파] %d 시그널 저장 실패: %s", peer_stock_id, e)

    return created_count


# ---------------------------------------------------------------------------
# SPEC-AI-022: 비활성 종목 거래량 이상 탐지
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] detect_volume_anomaly_dormant_stocks — 비활성 종목 거래량 이상 탐지 진입점
# @MX:REASON: fund_manager에서 surge_candidate 저장 완료 후 호출. 전체 stocks 테이블 스캔 + Naver API 호출 포함
# @MX:SPEC: SPEC-AI-022 REQ-002
def detect_volume_anomaly_dormant_stocks(
    db: Session,
    config: "VolumeAnomalyConfig",  # noqa: F821
) -> int:
    """SPEC-AI-022 REQ-002: 비활성 종목의 거래량 이상(spike)을 탐지하여 volume_anomaly 시그널 생성.

    비활성 기준: 최근 90일 내 surge_candidate 시그널 < 3개.
    거래량 비율: 오늘 거래량 / 최근 60일 평균 거래량 >= 5.0 이면 시그널 생성.
    전체 함수가 try/except로 감싸여 있어 내부 예외가 surge_candidate 결과에 영향을 주지 않음.

    Args:
        db: SQLAlchemy 세션
        config: VolumeAnomalyConfig

    Returns:
        생성된 volume_anomaly 시그널 수
    """
    try:
        return _detect_volume_anomaly_internal(db, config)
    except Exception as e:
        logger.error("[거래량이상] detect_volume_anomaly_dormant_stocks 전체 예외: %s", e)
        return 0


def _detect_volume_anomaly_internal(
    db: Session,
    config: "VolumeAnomalyConfig",  # noqa: F821
) -> int:
    """거래량 이상 탐지 내부 구현."""
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.services.naver_finance import fetch_stock_price_history_sync

    lookback_start = datetime.now(timezone.utc) - timedelta(days=config.dormant_lookback_days)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 최소 시가총액 이상인 전체 종목 조회
    all_stocks = (
        db.query(Stock)
        .filter(Stock.market_cap >= config.min_market_cap)
        .all()
    )

    # 오늘 surge_candidate 이미 있는 stock_id 집합
    today_surge_ids: set[int] = set()
    today_surges = (
        db.query(FundSignal.stock_id)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.created_at >= today_start,
        )
        .distinct()
        .all()
    )
    for row in today_surges:
        today_surge_ids.add(row[0])

    # 비활성 종목별 surge_candidate 시그널 수 집계
    from sqlalchemy import func as sqlfunc
    signal_counts: dict[int, int] = {}
    rows = (
        db.query(FundSignal.stock_id, sqlfunc.count(FundSignal.id))
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.created_at >= lookback_start,
        )
        .group_by(FundSignal.stock_id)
        .all()
    )
    for stock_id, cnt in rows:
        signal_counts[stock_id] = cnt

    created_count = 0

    for stock in all_stocks:
        # 비활성 조건: 90일 내 surge_candidate 시그널 수 < threshold
        if signal_counts.get(stock.id, 0) >= config.dormant_signal_count_threshold:
            continue

        # 오늘 이미 surge_candidate 있으면 스킵 (중복 방지)
        if stock.id in today_surge_ids:
            continue

        # 가격 히스토리 조회 (약 60 거래일)
        try:
            records = fetch_stock_price_history_sync(stock.stock_code, pages=config.history_pages)
        except Exception as e:
            logger.debug("[거래량이상] %s 히스토리 조회 실패: %s", stock.stock_code, e)
            continue

        if not records or len(records) < config.min_history_days:
            logger.debug(
                "[거래량이상] %s 히스토리 부족 (%d일 < %d일 최소)",
                stock.stock_code, len(records) if records else 0, config.min_history_days,
            )
            continue

        # Naver 데이터: 최신순 정렬 (records[0] = 오늘/최신)
        today_volume = records[0].volume
        history_volumes = [r.volume for r in records[1:]]  # 오늘 제외한 과거 데이터

        if not history_volumes:
            continue

        avg_volume = statistics.mean(history_volumes)
        if avg_volume <= 0:
            continue

        volume_ratio = today_volume / avg_volume

        if volume_ratio < config.volume_ratio_threshold:
            continue

        # confidence = min(ratio / denominator, max_confidence)
        confidence = min(volume_ratio / config.confidence_denominator, config.max_confidence)

        try:
            signal = FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=confidence,
                reasoning=(
                    f"[SPEC-AI-022 거래량이상] 비활성 종목 거래량 급증 "
                    f"volume_ratio={volume_ratio:.2f}x (avg={avg_volume:.0f}→today={today_volume})"
                ),
                signal_type="volume_anomaly",
                paper_executed=False,
                surge_metadata=None,
            )
            db.add(signal)
            db.flush()
            created_count += 1
            logger.info(
                "[거래량이상] %s volume_anomaly 시그널 생성 (ratio=%.2f, confidence=%.3f)",
                stock.stock_code, volume_ratio, confidence,
            )
        except Exception as e:
            db.rollback()
            logger.warning("[거래량이상] %s 시그널 저장 실패: %s", stock.stock_code, e)

    return created_count


# ---------------------------------------------------------------------------
# 탐지기 5: 상한가 근접 종목 익일 carry-forward (SPEC-AI-023)
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] detect_near_limit_up_carries — 상한가 근접 carry-forward 진입점
# @MX:REASON: fund_manager._run_coverage_expansion에서 호출. 전체 stocks 시총 상위 스캔 + 가격 API 호출 포함
# @MX:SPEC: SPEC-AI-023
def detect_near_limit_up_carries(
    db: Session,
    config: "NearLimitUpConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-023: 어제 상한가 근접 종목에 익일 surge_candidate 시그널 발행.

    전일 near_limit_up_min_pct 이상 near_limit_up_max_pct 이하 등락률 종목 탐지.
    paper_executed=True 로 생성하여 익일 매수 큐에 자동 포함.
    내부 예외는 suppress하여 상위 파이프라인에 영향을 주지 않는다.

    Args:
        db: SQLAlchemy 세션
        config: NearLimitUpConfig

    Returns:
        생성된 FundSignal 목록
    """
    import json as _json
    from zoneinfo import ZoneInfo

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []

    try:
        today_kst_start = datetime.now(KST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # SQLite에서도 동작하도록 UTC 변환
        today_utc_start = today_kst_start.astimezone(timezone.utc)

        # 오늘 이미 시그널 있는 stock_id 집합 (signal_type 불문)
        existing_ids: set[int] = set(
            row[0]
            for row in (
                db.query(FundSignal.stock_id)
                .filter(FundSignal.created_at >= today_utc_start)
                .distinct()
                .all()
            )
        )

        # 시총 상위 N 종목 — market_cap NULL 종목(전체의 60%+)도 후보 풀에 포함.
        # 이전에는 NULL 제외로 남광토건 등 실제 상한가 근접 종목이 통째로 누락됐음.
        # NULL은 nullslast()로 순위 뒤로 밀려 배치되며, max_stocks_to_check 확대로 도달 가능.
        candidates = (
            db.query(Stock)
            .order_by(nullslast(Stock.market_cap.desc()))
            .limit(config.max_stocks_to_check)
            .all()
        )

        for stock in candidates:
            if (
                config.max_signals_per_day is not None
                and len(signals) >= config.max_signals_per_day
            ):
                break

            if stock.id in existing_ids:
                continue

            price_data = _fetch_price_change_sync(stock.stock_code)
            if price_data is None:
                continue

            change_rate: float = price_data.get("change_rate", 0.0)

            if not (
                config.near_limit_up_min_pct
                <= change_rate
                <= config.near_limit_up_max_pct
            ):
                continue

            confidence = round(change_rate / 30.0 * 0.5, 4)
            reasoning = (
                f"상한가 근접 종목 — 전일 {change_rate:.2f}% 상승, 미체결 모멘텀 이월"
            )
            metadata = {
                "surge_basis": ["near_limit_up_carry"],
                "yesterday_change_pct": round(change_rate, 2),
                "surge_probability_score": confidence,
            }

            signal = FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=confidence,
                reasoning=reasoning,
                surge_metadata=_json.dumps(metadata, ensure_ascii=False),
                paper_executed=True,
                price_at_signal=price_data.get("current_price"),
            )
            db.add(signal)
            signals.append(signal)

        if signals:
            db.commit()
            logger.info(
                "[near_limit_up] 상한가 근접 carry-forward 시그널 %d건 생성",
                len(signals),
            )

    except Exception as e:
        logger.error("[near_limit_up] 예외 발생: %s", e, exc_info=True)
        return []

    return signals


# ---------------------------------------------------------------------------
# SPEC-AI-024: 임원 자사주 직접 매수 공시 강화 탐지기
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] detect_insider_purchase_signals — fund_manager._run_coverage_expansion()에서 호출
# @MX:REASON: 커버리지 확장 파이프라인(fan_in >= 3)에 추가된 공시 기반 탐지기. 예외 격리 필수.
def detect_insider_purchase_signals(
    db: Session,
    config: "InsiderPurchaseConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-024: 임원 자사주 매수 공시 종목에 surge_candidate 시그널 발행.

    rcept_dt >= 오늘-lookback_days 인 공시 중 임원 취득 관련 공시를 탐지하여
    아직 오늘 시그널이 없는 종목에 surge_candidate 시그널을 생성한다.
    처분/매도/양도 키워드가 포함된 공시는 제외한다.

    Args:
        db: SQLAlchemy 세션
        config: InsiderPurchaseConfig

    Returns:
        생성된 FundSignal 목록
    """
    import json as _json
    from zoneinfo import ZoneInfo

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []

    try:
        today_kst_start = datetime.now(KST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_utc_start = today_kst_start.astimezone(timezone.utc)
        cutoff_dt = datetime.now(KST) - timedelta(days=config.lookback_days)
        cutoff_str = cutoff_dt.strftime("%Y%m%d")

        # 오늘 이미 시그널 있는 stock_id 집합
        existing_ids: set[int] = set(
            row[0]
            for row in (
                db.query(FundSignal.stock_id)
                .filter(FundSignal.created_at >= today_utc_start)
                .distinct()
                .all()
            )
        )

        # 음성 키워드 (매도 계열)
        _NEGATIVE_KEYWORDS = ["처분", "매도", "양도"]
        # 양성 키워드 (취득 계열): OR 조건
        _POSITIVE_KEYWORDS = ["%임원%취득%", "%임원%매수%"]

        from sqlalchemy import or_
        candidates = (
            db.query(Disclosure)
            .filter(
                Disclosure.rcept_dt >= cutoff_str,
                Disclosure.stock_id.isnot(None),
                or_(
                    *[Disclosure.report_name.ilike(kw) for kw in _POSITIVE_KEYWORDS]
                ),
            )
            .all()
        )

        emitted: set[int] = set()
        for disc in candidates:
            if disc.stock_id is None:
                continue
            if disc.stock_id in existing_ids:
                continue
            if disc.stock_id in emitted:
                continue

            # 음성 키워드 차단
            rname = disc.report_name or ""
            if any(neg in rname for neg in _NEGATIVE_KEYWORDS):
                continue

            metadata = {
                "surge_basis": ["insider_purchase"],
                "report_name": rname,
                "surge_probability_score": config.base_confidence,
            }
            signal = FundSignal(
                stock_id=disc.stock_id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=config.base_confidence,
                reasoning=f"임원 자사주 매수 공시 — {rname}",
                surge_metadata=_json.dumps(metadata, ensure_ascii=False),
                paper_executed=True,
            )
            db.add(signal)
            signals.append(signal)
            emitted.add(disc.stock_id)

        if signals:
            db.commit()
            logger.info("[insider_purchase] 시그널 %d건 생성", len(signals))

    except Exception as e:
        logger.error("[insider_purchase] 예외 발생: %s", e, exc_info=True)
        return []

    return signals


# ---------------------------------------------------------------------------
# SPEC-AI-025: 테마 그룹 강세 carry-forward
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] detect_theme_group_carry_forward — fund_manager._run_coverage_expansion()에서 호출
# @MX:REASON: 커버리지 확장 파이프라인(fan_in >= 3)에 추가된 테마 그룹 강세 탐지기. 예외 격리 필수.
def detect_theme_group_carry_forward(
    db: Session,
    config: "ThemeGroupCarryConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-025: 앵커 종목 강세 시 테마 그룹 멤버에 surge_candidate 시그널 발행.

    ThemeGroup별 anchor_stock의 오늘 등락률이 anchor_surge_min_pct 이상이면
    그룹 내 미시그널 종목에 confidence = round(change_rate / 30.0 * 0.4, 4) 시그널을 생성한다.
    그룹당 최대 max_signals_per_group 건, 크로스 그룹 중복 제거.

    Args:
        db: SQLAlchemy 세션
        config: ThemeGroupCarryConfig

    Returns:
        생성된 FundSignal 목록
    """
    import json as _json
    from zoneinfo import ZoneInfo

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []

    try:
        from app.models.theme_group import ThemeGroup, StockThemeGroup

        today_kst_start = datetime.now(KST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_utc_start = today_kst_start.astimezone(timezone.utc)

        # 오늘 이미 시그널 있는 stock_id 집합
        existing_ids: set[int] = set(
            row[0]
            for row in (
                db.query(FundSignal.stock_id)
                .filter(FundSignal.created_at >= today_utc_start)
                .distinct()
                .all()
            )
        )

        # anchor_stock_id가 있는 그룹만 조회
        groups = (
            db.query(ThemeGroup)
            .filter(ThemeGroup.anchor_stock_id.isnot(None))
            .all()
        )

        emitted_codes: set[int] = set()

        for group in groups:
            if group.anchor_stock_id is None:
                continue

            # 앵커 종목 등락률 조회
            anchor_stock = db.query(Stock).filter(Stock.id == group.anchor_stock_id).first()
            if anchor_stock is None:
                continue

            price_data = _fetch_price_change_sync(anchor_stock.stock_code)
            if price_data is None:
                continue

            change_rate: float = price_data.get("change_rate", 0.0)
            if change_rate < config.anchor_surge_min_pct:
                continue

            # 그룹 멤버 조회
            member_rows = (
                db.query(StockThemeGroup)
                .filter(StockThemeGroup.theme_group_id == group.id)
                .all()
            )

            group_count = 0
            for stg in member_rows:
                if group_count >= config.max_signals_per_group:
                    break

                sid = stg.stock_id
                if sid == group.anchor_stock_id:
                    continue
                if sid in existing_ids:
                    continue
                if sid in emitted_codes:
                    continue

                confidence = round(change_rate / 30.0 * 0.4, 4)
                metadata = {
                    "surge_basis": ["theme_group_carry"],
                    "anchor_stock_id": group.anchor_stock_id,
                    "anchor_change_rate": round(change_rate, 2),
                    "theme_group": group.name,
                    "surge_probability_score": confidence,
                }
                signal = FundSignal(
                    stock_id=sid,
                    signal="buy",
                    signal_type="surge_candidate",
                    confidence=confidence,
                    reasoning=(
                        f"테마 그룹 강세 carry-forward — {group.name} 앵커 {change_rate:.2f}% 상승"
                    ),
                    surge_metadata=_json.dumps(metadata, ensure_ascii=False),
                    paper_executed=True,
                )
                db.add(signal)
                signals.append(signal)
                emitted_codes.add(sid)
                group_count += 1

        if signals:
            db.commit()
            logger.info("[theme_group_carry] 시그널 %d건 생성", len(signals))

    except Exception as e:
        logger.error("[theme_group_carry] 예외 발생: %s", e, exc_info=True)
        return []

    return signals


# ---------------------------------------------------------------------------
# SPEC-AI-026: 포럼 언급 급증 탐지기
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] detect_forum_mention_surge — fund_manager._run_coverage_expansion()에서 호출
# @MX:REASON: 커버리지 확장 파이프라인(fan_in >= 3)에 추가된 포럼 언급 급증 탐지기. 예외 격리 필수.
def detect_forum_mention_surge(
    db: Session,
    config: "ForumMentionConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-026: 종목토론방 언급 급증 종목에 surge_candidate 시그널 발행.

    최근 mention_window_hours 내 게시글 수(recent_count)가
    baseline_days 기간 일평균의 mention_multiplier배 이상이고
    min_absolute_mentions 이상인 종목을 탐지한다.
    baseline=0인 신규 종목은 스킵한다.

    Args:
        db: SQLAlchemy 세션
        config: ForumMentionConfig

    Returns:
        생성된 FundSignal 목록
    """
    import json as _json
    from sqlalchemy import func as sqlfunc
    from zoneinfo import ZoneInfo

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []

    try:
        from app.models.stock_forum import StockForumPost
        from app.services.naver_finance import fetch_current_price_with_change_sync

        now = datetime.now(timezone.utc)
        today_kst_start = datetime.now(KST).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)

        # 오늘 이미 시그널 있는 stock_id 집합
        existing_ids: set[int] = set(
            row[0]
            for row in (
                db.query(FundSignal.stock_id)
                .filter(FundSignal.created_at >= today_kst_start)
                .distinct()
                .all()
            )
        )

        recent_cutoff = now - timedelta(hours=config.mention_window_hours)
        baseline_end = now - timedelta(days=1)
        baseline_start = now - timedelta(days=1 + config.baseline_days)

        # 최근 window 내 종목별 게시글 수 (SQL 집계)
        recent_rows = (
            db.query(
                StockForumPost.stock_id,
                StockForumPost.stock_code,
                sqlfunc.count(StockForumPost.id).label("recent_count"),
            )
            .filter(
                StockForumPost.stock_id.isnot(None),
                StockForumPost.post_date >= recent_cutoff,
            )
            .group_by(StockForumPost.stock_id, StockForumPost.stock_code)
            .all()
        )

        # baseline 기간 종목별 총 게시글 수 (SQL 집계)
        baseline_rows = (
            db.query(
                StockForumPost.stock_id,
                sqlfunc.count(StockForumPost.id).label("baseline_total"),
            )
            .filter(
                StockForumPost.stock_id.isnot(None),
                StockForumPost.post_date >= baseline_start,
                StockForumPost.post_date < baseline_end,
            )
            .group_by(StockForumPost.stock_id)
            .all()
        )

        # stock_id → baseline_avg 매핑
        baseline_map: dict[int, float] = {
            row.stock_id: row.baseline_total / config.baseline_days
            for row in baseline_rows
        }

        for row in recent_rows:
            stock_id = row.stock_id
            recent_count = row.recent_count

            if stock_id is None:
                continue
            if stock_id in existing_ids:
                continue
            if recent_count < config.min_absolute_mentions:
                continue

            baseline_avg = baseline_map.get(stock_id, 0.0)
            if baseline_avg == 0.0:
                # 신규 종목 — 기준선 없음, 스킵
                continue
            if recent_count < baseline_avg * config.mention_multiplier:
                continue

            confidence = round(
                min(recent_count / baseline_avg / 20.0, config.max_confidence), 4
            )
            metadata = {
                "surge_basis": ["forum_mention_surge"],
                "recent_count": recent_count,
                "baseline_avg": round(baseline_avg, 2),
                "ratio": round(recent_count / baseline_avg, 2),
                "surge_probability_score": confidence,
            }
            signal = FundSignal(
                stock_id=stock_id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=confidence,
                reasoning=(
                    f"포럼 언급 급증 — 최근 {recent_count}건 (기준선 {baseline_avg:.1f}건/일의 "
                    f"{recent_count / baseline_avg:.1f}배)"
                ),
                surge_metadata=_json.dumps(metadata, ensure_ascii=False),
                paper_executed=True,
            )
            try:
                price_data = fetch_current_price_with_change_sync(row.stock_code)
                if price_data and price_data.get("current_price"):
                    signal.price_at_signal = price_data["current_price"]
            except Exception:
                pass
            db.add(signal)
            signals.append(signal)

        if signals:
            db.commit()
            logger.info("[forum_mention_surge] 시그널 %d건 생성", len(signals))

    except Exception as e:
        logger.error("[forum_mention_surge] 예외 발생: %s", e, exc_info=True)
        return []

    return signals


# ---------------------------------------------------------------------------
# SPEC-AI-027: 대기업 그룹 계열사 테마캐리 탐지기
# ---------------------------------------------------------------------------

def _fetch_intraday_change_for_cascade(stock_code: str) -> float:
    """대장주의 당일 intraday 등락률(%)을 조회한다.

    네이버 모바일 API를 통해 현재가/기준가를 조회하여 등락률을 계산한다.
    조회 실패 시 0.0을 반환한다.

    Args:
        stock_code: 종목코드

    Returns:
        등락률 (%) — 실패 시 0.0
    """
    try:
        import requests
        url = (
            f"https://m.stock.naver.com/api/stock/{stock_code}/basic"
        )
        resp = requests.get(url, timeout=3)
        if resp.status_code != 200:
            return 0.0
        data = resp.json()
        # Naver 모바일 API는 "fluctuationsRatio" 필드를 사용 (changeRate 아님)
        change_rate = data.get("fluctuationsRatio", data.get("changeRate", "0"))
        return float(str(change_rate).replace("%", "").replace(",", ""))
    except Exception:
        return 0.0


# @MX:ANCHOR: [AUTO] 그룹 계열사 cascade 탐지 진입점 — fund_manager._run_coverage_expansion 7번째 탐지기로 참조됨
# @MX:REASON: [AUTO] _run_coverage_expansion()에서 호출, 향후 테스트/스케줄러에서도 직접 호출 가능 (fan_in >= 2)
# @MX:SPEC: SPEC-AI-027 REQ-001
def detect_group_cascade_signals(
    db: Session,
    surge_results: list[dict],
    config: "GroupCascadeConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-027: 대장주 급등 시 동일 그룹 계열사에 surge_candidate 시그널 발행.

    종목명 접두사 매칭으로 그룹 계열사를 식별하고, 대장주가 급등 조건을 만족하면
    계열사에 cascade 시그널을 생성한다.

    Args:
        db: SQLAlchemy 세션
        surge_results: _gather_surge_candidates 반환값 (surge_candidate dict 목록)
        config: GroupCascadeConfig

    Returns:
        생성된 FundSignal 목록
    """
    import json as _json
    from zoneinfo import ZoneInfo

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []

    # 오늘 KST 시작 시각 (UTC)
    today_kst_start = datetime.now(KST).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    # 오늘 이미 시그널 있는 stock_id → signal_type 집합
    existing_today: dict[int, set[str]] = {}
    today_rows = (
        db.query(FundSignal.stock_id, FundSignal.signal_type)
        .filter(FundSignal.created_at >= today_kst_start)
        .all()
    )
    for row in today_rows:
        if row.stock_id not in existing_today:
            existing_today[row.stock_id] = set()
        if row.signal_type:
            existing_today[row.stock_id].add(row.signal_type)

    # cascade 후보 stock_id → 최고 flagship confidence 추적 (AC-008 dedup)
    # key: cascade_stock_id, value: (flagship_code, flagship_prob, confidence)
    best_cascade: dict[int, tuple[str, float, float]] = {}

    num_flagships = 0
    num_candidates_evaluated = 0

    for result in surge_results:
        stock_code = result.get("stock_code", "")
        stock_name = result.get("name", "")
        surge_score = result.get("surge_score", 0.0)

        if not stock_code or not stock_name:
            continue

        # 대장주 Stock 레코드 조회
        flagship_stock = (
            db.query(Stock)
            .filter(Stock.stock_code == stock_code)
            .first()
        )
        if flagship_stock is None:
            continue

        # market_cap NULL → flagship 제외 (AC-003)
        if flagship_stock.market_cap is None:
            continue

        # flagship 조건 판정
        is_flagship = False
        flagship_prob = surge_score

        # 조건 (a): surge_score >= flagship_prob_threshold
        if surge_score >= config.flagship_prob_threshold:
            # flagship_min_market_cap 검사
            if flagship_stock.market_cap >= config.flagship_min_market_cap:
                is_flagship = True

        # 조건 (b): intraday 등락률 >= flagship_change_pct AND 시총 >= flagship_min_market_cap
        if not is_flagship and flagship_stock.market_cap >= config.flagship_min_market_cap:
            intraday_change = _fetch_intraday_change_for_cascade(stock_code)
            if intraday_change >= config.flagship_change_pct:
                is_flagship = True

        if not is_flagship:
            continue

        num_flagships += 1

        # 접두사 추출
        prefix = stock_name[: config.min_prefix_len]
        if len(prefix) < config.min_prefix_len:
            continue

        # @MX:WARN: [AUTO] stocks 테이블 name LIKE 접두사 매칭 — 인덱스 미활용 시 풀스캔 발생 가능
        # @MX:REASON: [AUTO] stocks.name은 인덱스 없음; 데이터 건수 적어 현재는 허용, 증가 시 인덱스 추가 필요
        affiliate_candidates = (
            db.query(Stock)
            .filter(
                Stock.name.like(f"{prefix}%"),
                Stock.stock_code != stock_code,
                Stock.market_cap >= config.cascade_min_market_cap,
            )
            .order_by(Stock.market_cap.desc())
            .limit(config.max_cascade_per_flagship)
            .all()
        )

        for affiliate in affiliate_candidates:
            num_candidates_evaluated += 1

            # dedup guard: 오늘 이미 시그널 있는 종목 스킵 (AC-006, AC-007)
            existing_types = existing_today.get(affiliate.id, set())
            if existing_types:
                continue

            confidence = round(flagship_prob * config.decay_factor, 4)

            # AC-008: 같은 cascade 종목에 대해 더 높은 flagship 우선
            if affiliate.id in best_cascade:
                _, prev_prob, _ = best_cascade[affiliate.id]
                if flagship_prob <= prev_prob:
                    continue

            best_cascade[affiliate.id] = (stock_code, flagship_prob, confidence)

    # SPEC-AI-050 REQ-4: companion guard 차단 카운터
    companion_blocked = 0

    # best_cascade 기준으로 FundSignal 생성
    for cascade_stock_id, (flagship_code, flagship_prob, confidence) in best_cascade.items():
        # SPEC-AI-050 REQ-4: companion guard — 저확률 cascade 단독 시그널 차단
        if config.require_companion_detector and confidence < config.companion_required_below_prob:
            existing_types = existing_today.get(cascade_stock_id, set())
            # group_cascade 시그널만 있거나 시그널이 없으면 차단
            non_cascade_types = existing_types - {"surge_candidate"}
            has_companion = bool(non_cascade_types) or any(
                st != "surge_candidate" for st in existing_types
            )
            # 오늘 이미 다른 탐지기(group_cascade 제외)에서 surge_candidate 시그널이 있는지 확인
            # existing_today는 이미 오늘 전체 시그널을 포함하므로,
            # 다른 탐지기 기여 여부는 surge_metadata에서 판단하기 어려움
            # 따라서 단순히 오늘 어떤 시그널이라도 있으면 companion이 있다고 봄
            has_companion = bool(existing_types)
            if not has_companion:
                companion_blocked += 1
                logger.debug(
                    "[group_cascade] companion 가드 차단: stock_id=%d confidence=%.3f",
                    cascade_stock_id,
                    confidence,
                )
                continue

        # flagship 이름 조회
        flagship_row = next(
            (r for r in surge_results if r.get("stock_code") == flagship_code), {}
        )
        flagship_name = flagship_row.get("name", flagship_code)

        prefix = flagship_name[: config.min_prefix_len] if flagship_name else ""

        metadata = {
            "surge_basis": ["group_cascade"],
            "flagship_stock_code": flagship_code,
            "flagship_prob": round(flagship_prob, 4),
            "group_prefix": prefix,
            "surge_probability_score": confidence,
        }

        # price_at_signal 조회 (cascade 종목 현재가)
        _cascade_price: int | None = None
        _cascade_stock = db.query(Stock).filter(Stock.id == cascade_stock_id).first()
        if _cascade_stock:
            try:
                _cascade_price_data = _fetch_price_change_sync(_cascade_stock.stock_code)
                if _cascade_price_data:
                    _cascade_price = _cascade_price_data.get("current_price")
            except Exception as _ce:
                logger.warning(
                    "[group_cascade] %s 현재가 조회 실패 (price_at_signal=None): %s",
                    _cascade_stock.stock_code,
                    _ce,
                )

        signal = FundSignal(
            stock_id=cascade_stock_id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=confidence,
            reasoning=(
                f"[SPEC-AI-027 그룹캐스케이드] 대장주 {flagship_name}({flagship_code}) "
                f"{flagship_prob:.2f} 급등 → 계열사 동반 상승 기대"
            ),
            surge_metadata=_json.dumps(metadata, ensure_ascii=False),
            paper_executed=True,
            price_at_signal=_cascade_price,
        )
        db.add(signal)
        signals.append(signal)

    if signals:
        db.commit()

    logger.info(
        "[group_cascade] flagship=%d cascade_eval=%d 생성=%d companion_blocked=%d",
        num_flagships,
        num_candidates_evaluated,
        len(signals),
        companion_blocked,
    )

    return signals


# ---------------------------------------------------------------------------
# SPEC-AI-050 REQ-5: 주말 갭업 탐지기
# ---------------------------------------------------------------------------

def detect_weekend_gap_up_signals(
    db: Session,
    config: SurgeDetectionConfig,
    run_dt: datetime | None = None,
) -> list[dict]:
    """주말/연휴 갭업 후보 탐지 — 최근 10거래일 급등 이력 + 활성 테마 섹터 매칭.

    # @MX:NOTE: [AUTO] SPEC-AI-050 REQ-5 — _is_weekend_gap_up_day() False이면 즉시 []
    # @MX:SPEC: SPEC-AI-050 REQ-5

    월요일(또는 연휴 직후)에만 활성화되며, 최근 10거래일(영업일) 내 급등(was_surge=True)
    종목 중 활성 뉴스 테마 섹터와 일치하는 종목을 후보로 반환한다.

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig
        run_dt: 실행 시각 (None이면 현재 KST 시각 사용)

    Returns:
        surge_candidate dict 목록 (surge_basis=["weekend_gap_up"])
    """
    from zoneinfo import ZoneInfo as _ZI

    _KST = _ZI("Asia/Seoul")

    if run_dt is None:
        run_dt = datetime.now(_KST)

    if not _is_weekend_gap_up_day(run_dt):
        logger.debug("[weekend_gap_up] 주말/연휴 직후 아님 — 스킵")
        return []

    from app.models.surge_actual_outcome import SurgeActualOutcome

    # 최근 10거래일(역일 기준 약 15일) 급등 이력 조회
    cutoff_date = run_dt.date() - timedelta(days=15)

    try:
        surged_rows = (
            db.query(
                SurgeActualOutcome.stock_code,
                SurgeActualOutcome.trading_date,
            )
            .filter(
                SurgeActualOutcome.was_surge.is_(True),
                SurgeActualOutcome.trading_date >= cutoff_date,
            )
            .all()
        )
    except Exception as e:
        logger.warning("[weekend_gap_up] 급등 이력 조회 실패 (스킵): %s", e)
        return []

    if not surged_rows:
        logger.debug("[weekend_gap_up] 최근 10거래일 급등 종목 없음")
        return []

    surged_codes: set[str] = {row.stock_code for row in surged_rows}

    # 테마 클러스터 설정에서 활성 섹터 목록 추출
    sector_theme_map = config.theme_cluster.sector_theme_map
    # 값(섹터 목록)을 평탄화하여 활성 섹터 집합 생성
    active_sectors: set[str] = set()
    for sectors_list in sector_theme_map.values():
        active_sectors.update(sectors_list)

    results: list[dict] = []

    for stock_code in surged_codes:
        # 종목 정보 조회
        stock = (
            db.query(Stock)
            .filter(Stock.stock_code == stock_code)
            .first()
        )
        if stock is None:
            continue

        # 섹터 매칭 (Stock → Sector)
        sector_match = False
        if stock.sector_id is not None:
            sector_obj = (
                db.query(Sector)
                .filter(Sector.id == stock.sector_id)
                .first()
            )
            if sector_obj and sector_obj.name in active_sectors:
                sector_match = True

        if not sector_match:
            continue

        results.append({
            "stock_code": stock_code,
            "stock_id": stock.id,
            "name": stock.name,
            "surge_basis": ["weekend_gap_up"],
            "surge_probability_score": 0.5,
            "weekend_gap_up_score": 0.5,
        })

    logger.info(
        "[weekend_gap_up] 후보 %d개 탐지 (surged_codes=%d, active_sectors=%d)",
        len(results),
        len(surged_codes),
        len(active_sectors),
    )
    return results


# ---------------------------------------------------------------------------
# SPEC-AI-051 REQ-AI051-001~003: 볼린저 밴드 스퀴즈 탐지기
# ---------------------------------------------------------------------------

def detect_bollinger_squeeze_signals(
    db: Session,
    config: "BollingerSqueezeConfig",  # noqa: F821
) -> list[SurgeCandidate]:
    """SPEC-AI-051: 볼린저 밴드 스퀴즈 탐지 — 시총 상위 종목 일봉 분석.

    # @MX:NOTE: [AUTO] SPEC-AI-051 REQ-AI051-003 — 15:10 스케줄러 잡에서 호출
    # @MX:SPEC: SPEC-AI-051 REQ-AI051-001~003

    시총 상위 config.max_stocks_to_check 종목의 일봉을 조회하여
    볼린저 밴드 폭(BW)이 60일 최솟값에 해당하는(스퀴즈) 종목을 SurgeCandidate로 반환한다.
    FundSignal은 생성하지 않으며 15:20 파이프라인에 통합된다.

    Args:
        db: SQLAlchemy 세션
        config: BollingerSqueezeConfig

    Returns:
        squeeze_score >= config.min_squeeze_score 인 SurgeCandidate 목록
    """
    if not config.enabled:
        return []

    from app.services.naver_finance import fetch_stock_price_history_sync
    from app.services.technical_indicators import calculate_bollinger_bandwidth_squeeze

    logger.info("[bollinger_squeeze] 스퀴즈 탐지 시작 (대상: 시총 상위 %d종목)", config.max_stocks_to_check)

    # 시총 상위 N 종목 (market_cap None 제외)
    top_stocks = (
        db.query(Stock)
        .filter(Stock.market_cap.isnot(None))
        .order_by(Stock.market_cap.desc())
        .limit(config.max_stocks_to_check)
        .all()
    )

    results: list[SurgeCandidate] = []

    for stock in top_stocks:
        try:
            price_records = fetch_stock_price_history_sync(stock.stock_code, pages=config.price_pages)
            if not price_records:
                continue

            # 종가 추출 (최신순 내림차순 — fetch_stock_price_history_sync 반환 순서)
            close_prices = [r.close for r in price_records]

            result = calculate_bollinger_bandwidth_squeeze(close_prices, lookback=config.lookback_days)
            if result is None:
                continue

            if not result["squeeze"]:
                continue

            squeeze_score = result["squeeze_score"]
            if squeeze_score < config.min_squeeze_score:
                continue

            candidate = SurgeCandidate(
                stock_code=stock.stock_code,
                stock_name=stock.name,
                squeeze_score=squeeze_score,
                active_detectors=["bollinger_squeeze"],
            )
            results.append(candidate)

        except Exception as e:
            logger.debug("[bollinger_squeeze] %s 처리 오류 (스킵): %s", stock.stock_code, e)
            continue

    logger.info("[bollinger_squeeze] 스퀴즈 탐지 완료: %d건", len(results))
    return results


# ---------------------------------------------------------------------------
# SPEC-AI-051 REQ-AI051-007~009: 14:30 갭상승 런너 파이프라인
# ---------------------------------------------------------------------------

def detect_gap_up_runners(
    db: Session,
    config: "GapUpRunnersConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-051: 당일 급등 리더 종목의 섹터 2/3등 종목을 익일 갭상승 후보로 등록.

    # @MX:WARN: [AUTO] 섹터별 중복 리더 처리 + 오픈 포지션 조회 포함 — 분기 수 높음
    # @MX:REASON: leader_signals 순회 중 sector_id 중복 체크, open_position 조회, price_data 조회가
    #             중첩되어 복잡도가 높다. 대량 리더 시그널 입력 시 성능 주의.
    # @MX:SPEC: SPEC-AI-051 REQ-AI051-007~009

    REQ-AI051-007: 당일 confidence >= min_leader_confidence 인 리더 시그널 조회
    REQ-AI051-008: 동일 섹터 시총 2/3위 피어 선정 (open position 보유 종목 제외)
    REQ-AI051-009: confidence = leader.confidence * confidence_decay 로 감쇠

    Args:
        db: SQLAlchemy 세션
        config: GapUpRunnersConfig

    Returns:
        생성된 FundSignal 목록 (signal_type="gap_up_runners")
    """
    import json as _json
    from zoneinfo import ZoneInfo

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []

    try:
        # 당일 KST 00:00 기준 UTC 변환
        today_kst_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
        today_utc_start = today_kst_start.astimezone(timezone.utc)

        # 당일 고신뢰 리더 시그널 조회 (REQ-AI051-007)
        leader_signals = (
            db.query(FundSignal, Stock)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(
                FundSignal.signal_type.in_(["surge_candidate", "immediate_disclosure"]),
                FundSignal.confidence >= config.min_leader_confidence,
                FundSignal.created_at >= today_utc_start,
            )
            .all()
        )

        if not leader_signals:
            logger.info("[gap_up_runners] 리더 시그널 없음")
            return []

        # 리더별 섹터 런너 선정
        processed_sector_ids: set[int] = set()
        registered_runner_ids: set[int] = set()  # 중복 런너 방지

        for leader_signal, leader_stock in leader_signals:
            if leader_stock.sector_id in processed_sector_ids:
                continue  # 동일 섹터 중복 처리 방지
            processed_sector_ids.add(leader_stock.sector_id)

            # 동일 섹터 종목 market_cap 내림차순 (None 제외, 리더 제외)
            sector_peers = (
                db.query(Stock)
                .filter(
                    Stock.sector_id == leader_stock.sector_id,
                    Stock.market_cap.isnot(None),
                    Stock.id != leader_stock.id,
                )
                .order_by(Stock.market_cap.desc())
                .limit(5)  # 상위 5개에서 2/3등 추출
                .all()
            )

            # 2등, 3등 피어 (인덱스 0, 1)
            runners = sector_peers[:2]

            for runner in runners:
                if runner.id in registered_runner_ids:
                    continue

                # 이미 오픈된 SurgeTrade 있는 종목 제외 (REQ-AI051-008)
                from app.services.surge_trading_service import get_open_position
                if get_open_position(db, runner.stock_code):
                    continue

                # 현재가 조회 (REQ-AI051-008)
                price_data = _fetch_price_change_sync(runner.stock_code)
                current_price = price_data.get("current_price") if price_data else None

                confidence = round(leader_signal.confidence * config.confidence_decay, 4)
                reasoning = (
                    f"오늘 {leader_stock.name} +{leader_signal.confidence * 100:.0f}% 급등 "
                    f"테마 2/3등 종목, 익일 갭상승 저격"
                )
                metadata = {
                    "surge_basis": ["gap_up_runners"],
                    "leader_stock_code": leader_stock.stock_code,
                    "leader_signal_type": leader_signal.signal_type,
                    "leader_confidence": leader_signal.confidence,
                }

                signal = FundSignal(
                    stock_id=runner.id,
                    signal="buy",
                    signal_type="gap_up_runners",
                    confidence=confidence,
                    reasoning=reasoning,
                    surge_metadata=_json.dumps(metadata, ensure_ascii=False),
                    price_at_signal=current_price,
                )
                db.add(signal)
                signals.append(signal)
                registered_runner_ids.add(runner.id)

        if signals:
            db.commit()
            logger.info("[gap_up_runners] %d건 등록", len(signals))

    except Exception as e:
        logger.error("[gap_up_runners] 예외 발생: %s", e, exc_info=True)
        return []

    return signals


# SPEC-AI-066 REQ-005: 종목별 상대 임계 z-score 컷오프 (자체 롤링 대비 이상치 판정)
_VB_RELATIVE_Z_THRESHOLD = 2.0


def _build_volume_baseline_stats(baseline_vols: list[float]):
    """거래량 히스토리로부터 SPEC-AI-065 BaselineStats를 인라인 구성한다 (순수 파이썬).

    surge_baseline_service.compute_zscore를 재사용하기 위한 어댑터. 지속 baseline 테이블은
    탐지기 점수(0~1)를 저장하므로 거래량 규모에는 부적합 → 종목 자체 히스토리로 구성한다.
    """
    from app.services.surge_baseline_service import BaselineStats

    n = len(baseline_vols)
    if n < 2:
        return BaselineStats(rolling_mean=(baseline_vols[0] if baseline_vols else 0.0), rolling_m2=0.0, sample_count=n)
    mean_v = statistics.mean(baseline_vols)
    var = statistics.variance(baseline_vols)  # 표본 분산 (n-1)
    return BaselineStats(rolling_mean=mean_v, rolling_m2=var * (n - 1), sample_count=n)


def _baseline_compute_zscore(raw: float, stats, min_samples: int) -> float | None:
    """surge_baseline_service.compute_zscore 재사용 래퍼 (SPEC-AI-065)."""
    from app.services.surge_baseline_service import compute_zscore

    return compute_zscore(raw, stats, min_samples=min_samples)


def _fetch_volume_breakout_catalyst_universe(
    db: Session,
    config: SurgeDetectionConfig,
    exclude: set[str],
) -> list[str]:
    """SPEC-AI-066 REQ-005: 당일/밤새 촉매(공시 또는 뉴스 커버리지) 보유 종목 코드를 수집한다.

    거래량 순위 상위 50 밖의 촉매 중대형주를 volume_breakout 유니버스에 합류시키기 위함.
    """
    codes: list[str] = []
    _seen: set[str] = set(exclude)

    # 당일/최근 공시 종목
    try:
        _cutoff = (datetime.now(timezone.utc) - timedelta(hours=config.disclosure_pattern.disclosure_window_hours)).strftime("%Y%m%d")
        _disc_rows = (
            db.query(Stock.stock_code)
            .join(Disclosure, Disclosure.stock_id == Stock.id)
            .filter(Disclosure.rcept_dt >= _cutoff)
            .all()
        )
        for r in _disc_rows:
            if r.stock_code and r.stock_code not in _seen:
                _seen.add(r.stock_code)
                codes.append(r.stock_code)
    except Exception as e:
        logger.debug("[거래량폭발] 공시 촉매 조회 실패 (무시): %s", e)

    # 최근 뉴스 커버리지 종목
    try:
        from app.models.news_relation import NewsStockRelation
        _news_cutoff = (datetime.now(timezone.utc) - timedelta(hours=config.volume_news_combo.news_window_hours)).replace(tzinfo=None)
        _news_rows = (
            db.query(Stock.stock_code)
            .join(NewsStockRelation, NewsStockRelation.stock_id == Stock.id)
            .join(NewsArticle, NewsArticle.id == NewsStockRelation.news_id)
            .filter(NewsArticle.collected_at >= _news_cutoff)
            .distinct()
            .all()
        )
        for r in _news_rows:
            if r.stock_code and r.stock_code not in _seen:
                _seen.add(r.stock_code)
                codes.append(r.stock_code)
    except Exception as e:
        logger.debug("[거래량폭발] 뉴스 촉매 조회 실패 (무시): %s", e)

    return codes


def detect_volume_breakout(
    db: Session,
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """뉴스/공시 없이 거래량 폭발만으로 소형주 급등 후보를 탐지한다.

    Naver 거래량 순위 상위 종목에서 최근 20일 평균 대비 volume_ratio_threshold 배 이상
    거래량이 폭발한 종목을 SurgeCandidate로 반환한다. 시총/뉴스 필터 없음.

    SPEC-AI-066 REQ-005: relative_threshold_enabled일 때 촉매 종목 유니버스 확장 +
    종목별 상대(z-score) 임계를 추가한다. AI-062 가중치/AI-063 bypass 임계는 불변.
    """
    cfg = config.volume_breakout
    if not cfg.enabled:
        return []

    from app.models.stock import Stock
    from app.services.naver_finance import fetch_volume_leaders_sync, fetch_stock_price_history_sync

    try:
        leader_codes = fetch_volume_leaders_sync(limit=cfg.max_candidates // 2)
    except Exception as e:
        logger.warning("[거래량폭발] 순위 조회 실패: %s", e)
        return []

    # SPEC-AI-066 REQ-005: relative_threshold_enabled일 때만 촉매 종목으로 유니버스를 확장한다.
    # 비활성 시 기존 상위 거래량 리더 유니버스만 사용 (레거시 동작 보존, staged rollout).
    universe: list[str] = list(dict.fromkeys(leader_codes))
    if cfg.relative_threshold_enabled:
        try:
            _catalyst_codes = _fetch_volume_breakout_catalyst_universe(db, config, set(universe))
            if _catalyst_codes:
                universe = list(dict.fromkeys(universe + _catalyst_codes))[: cfg.max_candidates]
                logger.info("[거래량폭발] 촉매 종목 %d개 유니버스 합류", len(_catalyst_codes))
        except Exception as _ue:
            logger.debug("[거래량폭발] 촉매 유니버스 확장 실패 (무시): %s", _ue)

    candidates: list[SurgeCandidate] = []
    for code in universe:
        try:
            stock = db.query(Stock).filter(Stock.stock_code == code).first()
            if not stock:
                continue

            history = fetch_stock_price_history_sync(code, pages=3)
            if len(history) < cfg.min_history_days + 1:
                continue

            # SPEC-AI-067 REQ-003: 당일(history[0]) 거래량만 장중 실시간 값으로 교정.
            # AI-062 가중치/AI-063 bypass/AI-066 상대임계·유니버스 경로는 입력값만 신선화될 뿐 불변.
            today_vol = _resolve_today_volume(code, history[0].volume, config)
            if today_vol <= 0:
                continue

            # SPEC-AI-067 REQ-006 가정: 이전 거래일(history[1:]) 데이터는 완결된 것으로 가정 —
            # 오늘 실측한 것은 당일(today) 행의 지연이며, 과거 행의 정확성은 별도로 검증되지 않았다.
            # baseline은 모바일 교체 대상이 아니며 계속 sise_day에서 온다(모바일은 과거일 미제공).
            baseline_vols = [r.volume for r in history[1:cfg.baseline_days + 1] if r.volume > 0]
            if len(baseline_vols) < 10:
                continue

            mean_vol = statistics.mean(baseline_vols)
            if mean_vol <= 0:
                continue

            ratio = today_vol / mean_vol

            # SPEC-AI-066 REQ-005: 고정 배율 + (선택적) 종목별 상대(z-score) 임계.
            # relative 경로는 relative_threshold_enabled일 때만 활성. cold-start(표본 부족)이면
            # compute_zscore가 None → 고정 3.0x 배율로 폴백 (회귀 없음).
            qualifies_flat = ratio >= cfg.volume_ratio_threshold
            qualifies_relative = False
            if cfg.relative_threshold_enabled and not qualifies_flat:
                _stats = _build_volume_baseline_stats(baseline_vols)
                _z = _baseline_compute_zscore(
                    float(today_vol), _stats, min_samples=config.zscore_min_baseline_samples
                )
                if _z is not None and _z >= _VB_RELATIVE_Z_THRESHOLD:
                    qualifies_relative = True

            if not (qualifies_flat or qualifies_relative):
                continue

            breakout_score = min(ratio / cfg.confidence_denominator, cfg.max_score)
            candidates.append(
                SurgeCandidate(
                    stock_code=code,
                    stock_name=stock.name,
                    volume_breakout_score=breakout_score,
                    active_detectors=["volume_breakout"],
                )
            )
            logger.debug(
                "[거래량폭발] %s %s ratio=%.1f score=%.3f rel=%s",
                code,
                stock.name,
                ratio,
                breakout_score,
                qualifies_relative,
            )
        except Exception as e:
            logger.debug("[거래량폭발] %s 처리 중 오류: %s", code, e)
            continue

    logger.info("[거래량폭발] %d개 후보 탐지", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기
# ---------------------------------------------------------------------------

def detect_momentum_continuation(
    db: "Session",
    config: "SurgeDetectionConfig",
    market_regime: str = "NEUTRAL",
) -> list[SurgeCandidate]:
    """전일 등락률 5~15% 종목의 익일 모멘텀 연속 패턴을 탐지한다.

    SPEC-AI-065 REQ-3:
    - 전일 change_rate in [5%, 15%] 범위인 종목 탐지
    - 15% 초과는 추격매수 방지(REQ-3.4)로 제외
    - BEAR 레짐에서는 bear_dampening 비율로 점수 감쇠
    - volume_breakout(당일 거래량 이상)과 구별: 이 탐지기는 전일 등락률 기반

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정
        market_regime: 시장 레짐 (BEAR/SIDEWAYS/BULL/NEUTRAL)

    Returns:
        momentum_continuation_score가 채워진 SurgeCandidate 목록
    """
    cfg = config.momentum_continuation
    if not cfg.enabled:
        return []

    from app.models.surge_actual_outcome import SurgeActualOutcome

    try:

        # 15:20 KST scan: SurgeActualOutcome not yet populated (collect_outcomes 16:10 KST)
        # Use most recent available trading day data (SPEC-AI-065 timing bug fix)
        _latest_outcome = (
            db.query(SurgeActualOutcome.trading_date)
            .filter(SurgeActualOutcome.change_rate.isnot(None))
            .order_by(SurgeActualOutcome.trading_date.desc())
            .first()
        )
        if _latest_outcome is None:
            logger.debug("[momentum_cont] SurgeActualOutcome no data -- skip")
            return []
        reference_date = _latest_outcome.trading_date

        rows = (
            db.query(
                SurgeActualOutcome.stock_code,
                SurgeActualOutcome.change_rate,
            )
            .filter(
                SurgeActualOutcome.trading_date == reference_date,
                SurgeActualOutcome.change_rate.isnot(None),
                SurgeActualOutcome.change_rate >= cfg.min_change_rate,
                SurgeActualOutcome.change_rate < cfg.max_change_rate,
            )
            .all()
        )

        if not rows:
            logger.debug("[momentum_cont] %s no candidates (range=%s~%s%%)",
                         reference_date, cfg.min_change_rate, cfg.max_change_rate)
            return []

        candidates: list[SurgeCandidate] = []
        for row in rows:
            try:
                stock_code = row.stock_code
                change_rate = float(row.change_rate)

                # 점수 계산: 등락률 비례 선형 스케일
                # change_rate=5% → base_score, change_rate=15% → max_score
                range_pct = cfg.max_change_rate - cfg.min_change_rate
                rate_ratio = (change_rate - cfg.min_change_rate) / range_pct
                score = cfg.base_score + (cfg.max_score - cfg.base_score) * rate_ratio
                score = max(cfg.base_score, min(cfg.max_score, score))

                # BEAR 레짐 감쇠
                if market_regime == "BEAR":
                    score *= cfg.bear_dampening

                # stock_name 조회
                stock = db.query(Stock).filter(Stock.stock_code == stock_code).first()
                if stock is None:
                    continue

                candidates.append(
                    SurgeCandidate(
                        stock_code=stock_code,
                        stock_name=stock.name,
                        momentum_continuation_score=round(score, 4),
                        active_detectors=["momentum_continuation"],
                        entry_pool="pool_c",  # Pool C와 동일 소스
                    )
                )
                logger.debug(
                    "[모멘텀연속] %s %s change_rate=%.2f%% score=%.4f",
                    stock_code,
                    stock.name,
                    change_rate,
                    score,
                )
            except Exception as e:
                logger.debug("[모멘텀연속] %s 처리 중 오류: %s", row.stock_code, e)
                continue

        logger.info("[모멘텀연속] %d개 후보 탐지 (레짐=%s)", len(candidates), market_regime)
        return candidates

    except Exception as e:
        logger.warning("[모멘텀연속] 탐지 실패 (fail-open): %s", e)
        return []


# ---------------------------------------------------------------------------
# SPEC-AI-065 REQ-2: 스캔 유니버스 확장 — Pool A/B/C 빌드
# ---------------------------------------------------------------------------

def build_scan_universe(
    db: "Session",
    config: "SurgeDetectionConfig",
    existing_codes: set[str] | None = None,
) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """Pool A/B/C를 조합하여 스캔 유니버스를 구성한다.

    SPEC-AI-065 REQ-2:
    - Pool A: 오늘 DART 공시 종목 (rcept_dt == today YYYYMMDD)
    - Pool B: 거래량 200%+ 당일 종목 (PriceRecord 히스토리 기반)
    - Pool C: 오늘 change_rate 5% 이상 종목 (SurgeActualOutcome)
    - 최대 max_scan_universe 종목, 우선순위: A > B > C > existing

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정
        existing_codes: 기존 탐지기 결과 종목 코드 집합

    Returns:
        (universe_codes, entry_pool_map, pool_counts)
        - universe_codes: 최종 스캔 유니버스 코드 목록
        - entry_pool_map: {stock_code: entry_pool} 딕셔너리
        - pool_counts: {"pool_a": N, "pool_b": N, "pool_c": N} 집계
    """
    from datetime import date as _date

    existing_codes = existing_codes or set()
    today = _date.today()
    today_str = today.strftime("%Y%m%d")
    max_universe = config.max_scan_universe

    entry_pool_map: dict[str, str] = {}
    pool_a_codes: list[str] = []
    pool_b_codes: list[str] = []
    pool_c_codes: list[str] = []

    # Pool A: 오늘 DART 공시 종목
    try:
        disclosure_rows = (
            db.query(Disclosure.stock_code)
            .filter(
                Disclosure.rcept_dt == today_str,
                Disclosure.stock_code.isnot(None),
            )
            .distinct()
            .all()
        )
        pool_a_raw = [r.stock_code for r in disclosure_rows if r.stock_code]
        # DB에 등록된 종목만 포함
        for code in pool_a_raw:
            if code not in entry_pool_map:
                pool_a_codes.append(code)
                entry_pool_map[code] = "pool_a"
        logger.info("[스캔유니버스] Pool A(DART공시): %d개 (날짜=%s)", len(pool_a_codes), today_str)
    except Exception as e:
        logger.warning("[스캔유니버스] Pool A 조회 실패: %s", e)
        try:
            db.rollback()
        except Exception:
            pass

    # Pool B: 거래량 200%+ 당일 종목
    # SurgeActualOutcome에서 오늘 데이터를 활용하거나 naver_finance에서 직접 조회
    try:
        from app.services.naver_finance import fetch_volume_leaders_sync, fetch_stock_price_history_sync

        volume_leader_codes = fetch_volume_leaders_sync(limit=100)
        _baseline_days = 20
        _min_ratio = 2.0  # 200% = 2배

        for code in volume_leader_codes:
            if code in entry_pool_map:
                continue
            try:
                history = fetch_stock_price_history_sync(code, pages=3)
                if len(history) < _baseline_days + 1:
                    continue
                # SPEC-AI-067 REQ-004: 당일(history[0]) 거래량만 장중 실시간 값으로 교정.
                # Pool A/B/C 우선순위·max_scan_universe·_min_ratio=2.0은 불변(SPEC-AI-065 소유).
                today_vol = _resolve_today_volume(code, history[0].volume, config)
                if today_vol <= 0:
                    continue
                # SPEC-AI-067 REQ-006 가정: 이전 거래일(history[1:]) 데이터는 완결된 것으로 가정 —
                # baseline은 모바일 교체 대상이 아니며 계속 sise_day에서 온다(과거 행 정확성 미검증).
                baseline_vols = [r.volume for r in history[1:_baseline_days + 1] if r.volume > 0]
                if len(baseline_vols) < 5:
                    continue
                mean_vol = sum(baseline_vols) / len(baseline_vols)
                if mean_vol <= 0:
                    continue
                ratio = today_vol / mean_vol
                if ratio >= _min_ratio:
                    pool_b_codes.append(code)
                    entry_pool_map[code] = "pool_b"
            except Exception:
                continue

        logger.info("[스캔유니버스] Pool B(거래량200%%+): %d개", len(pool_b_codes))
    except Exception as e:
        logger.warning("[스캔유니버스] Pool B 조회 실패: %s", e)

    # Pool C: 오늘 change_rate 5% 이상 종목
    # SPEC-AI-065 REQ-2 버그픽스: 상한(15%) 제거 — 상한이 있으면 이미 15%+ 급등한
    # 종목(예: 금호건설/002990, 위메이드/112040처럼 반복 상한가 종목)이 재진입을 통해
    # 스캔 유니버스에 다시 포함될 기회를 구조적으로 차단하여 recall 손실을 유발했다.
    try:
        from app.models.surge_actual_outcome import SurgeActualOutcome

        _latest_pool_c = (
            db.query(SurgeActualOutcome.trading_date)
            .filter(SurgeActualOutcome.change_rate.isnot(None))
            .order_by(SurgeActualOutcome.trading_date.desc())
            .first()
        )
        _pool_c_date = _latest_pool_c.trading_date if _latest_pool_c else today
        pool_c_raw = (
            db.query(SurgeActualOutcome.stock_code)
            .filter(
                SurgeActualOutcome.trading_date == _pool_c_date,
                SurgeActualOutcome.change_rate.isnot(None),
                SurgeActualOutcome.change_rate >= 5.0,
            )
            .all()
        )
        for r in pool_c_raw:
            code = r.stock_code
            if code and code not in entry_pool_map:
                pool_c_codes.append(code)
                entry_pool_map[code] = "pool_c"

        logger.info("[스캔유니버스] Pool C(등락률5%%+): %d개", len(pool_c_codes))
    except Exception as e:
        logger.warning("[스캔유니버스] Pool C 조회 실패: %s", e)
        try:
            db.rollback()
        except Exception:
            pass

    # 기존 탐지기 결과 추가 (우선순위 최하)
    for code in existing_codes:
        if code not in entry_pool_map:
            entry_pool_map[code] = "existing"

    pool_counts = {
        "pool_a": len(pool_a_codes),
        "pool_b": len(pool_b_codes),
        "pool_c": len(pool_c_codes),
    }

    # 우선순위: A > B > C > existing — max_universe 초과 시 잘라냄
    universe_ordered = (
        pool_a_codes
        + pool_b_codes
        + pool_c_codes
        + [c for c in existing_codes if c not in entry_pool_map]
    )
    # 중복 제거 (순서 유지)
    seen: set[str] = set()
    universe_dedup: list[str] = []
    for code in universe_ordered:
        if code not in seen:
            seen.add(code)
            universe_dedup.append(code)

    final_universe = universe_dedup[:max_universe]
    logger.info(
        "[스캔유니버스] 최종 유니버스: %d개 (상한=%d, A=%d B=%d C=%d existing=%d)",
        len(final_universe),
        max_universe,
        pool_counts["pool_a"],
        pool_counts["pool_b"],
        pool_counts["pool_c"],
        len(existing_codes),
    )

    return final_universe, entry_pool_map, pool_counts
