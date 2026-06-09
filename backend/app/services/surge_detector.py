"""SPEC-AI-012: 급등 징후 탐지 서비스.

4가지 탐지기(테마 뉴스 클러스터링, 거래량 이상+뉴스 콤보, 공시 급등 패턴,
즉각 공시 이벤트)와 앙상블 스코어링을 제공한다.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import and_, or_
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
        return []

    logger.info("[테마클러스터] 활성 테마 %d개: %s", len(active_themes), list(active_themes.keys()))

    # 4. 활성 테마의 관련 섹터 목록 수집
    theme_to_sectors: dict[str, list[str]] = {}
    for theme, cnt in active_themes.items():
        sectors = cfg.sector_theme_map.get(theme, [])
        if sectors:
            theme_to_sectors[theme] = sectors

    if not theme_to_sectors:
        return []

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
        return []

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
        return []

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

    logger.info("[테마클러스터] 후보 %d개 탐지", len(results))
    return results


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
        # Pydantic 모델이므로 직접 필드 접근 (copy + 오버라이드)
        from app.surge_config.surge_settings import VolumeNewsComboConfig
        cfg = VolumeNewsComboConfig(
            volume_zscore_threshold=regime_params.volume_zscore_threshold,
            volume_baseline_days=cfg.volume_baseline_days,
            news_window_hours=regime_params.news_window_hours,
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
    news_stock_rows = (
        db.query(
            NewsArticle.sentiment,
            Stock.stock_code,
        )
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .join(Stock, Stock.id == NewsStockRelation.stock_id)
        .filter(
            NewsArticle.collected_at >= news_cutoff_naive,
            NewsArticle.sentiment.in_(["positive", "strong_positive", "mixed"]),
        )
        .all()
    )

    for sentiment, stock_code in news_stock_rows:
        score = _positive_sentiment_score(sentiment)
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
        current_vol = volumes[-1]

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
            if change_rate is None and cfg_guard.exclude_on_price_unavailable:
                logger.debug("[거래량콤보] %s 가격 조회 실패 — 제외", stock_code)
                continue
            if change_rate is not None and change_rate >= cfg_guard.overheat_change_pct:
                logger.debug(
                    "[거래량콤보] %s 과열 제외 change_rate=%.2f%%",
                    stock_code, change_rate,
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
            # Naver sise_day는 최신순(newest-first) → 역순으로 변환 후 최근 N일 슬라이스
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
            best_score = round(best_score * disc_filter.penalty_factor, 4)
            logger.debug("[즉각공시] %s 페널티 적용 (%.3f)", disc.stock_id, best_score)
            if disc.stock_id is not None:
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
        # SPEC-AI-039 REQ-039-002: 뉴스 지연 반응 점수 추가 (가중치 0.15)
        + w.news_delayed * candidate.news_delayed_score
    )

    # SPEC-AI-018 REQ-009: 탐지기 그룹 단위 컨센서스 배율 (동일 이벤트 중복 보상 방지)
    # news 그룹(theme+combo)은 모두 뉴스 이벤트에 반응 → 동일 그룹으로 묶음
    # disclosure 그룹: best_disclosure_score (공시 이벤트)
    # technical 그룹: legacy_score (선행 기술적 신호)
    detector_groups = {
        "news": [candidate.theme_cluster_score, candidate.combo_score],
        "disclosure": [best_disclosure_score],
        "technical": [candidate.legacy_score],
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

    # SPEC-AI-038 성능 패치 3단계: price_5d_trend 조회(HTTP) 전 상위 N개로 사전 필터
    # 이유: 테마클러스터가 수백 개 후보 반환 시 모든 종목 HTTP 호출 → 300s 타임아웃 초과
    # 수정: 기존 점수(HTTP 없음) 기준으로 상위 30개만 남기고 나머지 제거
    _MAX_PRICE_FETCH_CANDIDATES = 30
    if len(merged) > _MAX_PRICE_FETCH_CANDIDATES:
        _original_count = len(merged)
        def _pre_score(c: SurgeCandidate) -> float:
            return (
                c.theme_cluster_score * 0.45
                + c.combo_score * 0.30
                + c.pattern_score * 0.15
                + c.immediate_disclosure_score * 0.05
                + c.news_delayed_score * 0.05
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
    _bypass = config.ensemble.strong_single_bypass_threshold
    for candidate in merged.values():
        if candidate.stock_code not in qualified_codes and (
            candidate.theme_cluster_score >= _bypass
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

    # 앙상블 점수 내림차순 정렬
    qualified.sort(key=lambda c: compute_ensemble_score(c, config), reverse=True)

    logger.info(
        "[앙상블] 최종 급등 후보 %d개 (레짐=%s, 유효임계=%.2f)",
        len(qualified), market_regime, effective_threshold,
    )
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

        # 시총 상위 N 종목 (None 제외)
        candidates = (
            db.query(Stock)
            .filter(Stock.market_cap.isnot(None))
            .order_by(Stock.market_cap.desc())
            .limit(config.max_stocks_to_check)
            .all()
        )

        for stock in candidates:
            if len(signals) >= config.max_signals_per_day:
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
                sqlfunc.count(StockForumPost.id).label("recent_count"),
            )
            .filter(
                StockForumPost.stock_id.isnot(None),
                StockForumPost.post_date >= recent_cutoff,
            )
            .group_by(StockForumPost.stock_id)
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

    # best_cascade 기준으로 FundSignal 생성
    for cascade_stock_id, (flagship_code, flagship_prob, confidence) in best_cascade.items():
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
        )
        db.add(signal)
        signals.append(signal)

    if signals:
        db.commit()

    logger.info(
        "[group_cascade] flagship=%d cascade_eval=%d 생성=%d",
        num_flagships,
        num_candidates_evaluated,
        len(signals),
    )

    return signals
