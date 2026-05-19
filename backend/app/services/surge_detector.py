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

from sqlalchemy.orm import Session

from app.surge_config.surge_settings import SurgeDetectionConfig
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

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


def _sigmoid(x: float) -> float:
    """시그모이드 함수."""
    return 1.0 / (1.0 + math.exp(-x))


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

    stocks = (
        db.query(Stock)
        .filter(
            Stock.sector_id.in_(sector_ids),
            Stock.market_cap >= min_market_cap_eok,
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
        # 종목명 또는 종목코드가 제목/본문에 포함된 기사를 종목 전용 기사로 판별
        stock_articles = [
            a for a in window_news
            if stock.name in (a.title or "") + " " + (a.content or "")
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

        # REQ-AI014-002: 경량 거래량 보너스 (+0.10)
        # 전일 대비 3% 초과 가격 변동 시 보너스 적용
        price_bonus = 0.0
        try:
            price_data = _fetch_price_change_sync(stock.stock_code)
            if price_data is not None:
                change_rate = price_data.get("change_rate", 0.0) or 0.0
                if abs(change_rate) > 3.0:
                    price_bonus = 0.10
        except Exception:
            # 가격 조회 실패 시 보너스 없음, 예외 전파 금지
            price_bonus = 0.0

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

        results.append(
            SurgeCandidate(
                stock_code=stock.stock_code,
                stock_name=stock.name,
                theme_cluster_score=theme_cluster_score,
                active_detectors=["theme_cluster"],
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
) -> list[SurgeCandidate]:
    """거래량 z-score 이상 + 긍정 뉴스 콤보로 급등 후보를 탐지한다 (AC-SURGE-002).

    거래량 z-score > volume_zscore_threshold AND
    최근 news_window_hours 내 긍정 뉴스(sentiment_score >= min_news_sentiment)가 있는 종목.

    거래량 데이터는 FundSignal.price_at_signal 연속 레코드로 대체할 수 없으므로
    naver_finance 히스토리에 의존한다. 데이터 없는 경우 해당 종목 스킵.

    Args:
        db: SQLAlchemy 동기 세션
        config: SurgeDetectionConfig 설정

    Returns:
        SurgeCandidate 목록 (combo_score 채워짐)
    """
    cfg = config.volume_news_combo
    # @MX:NOTE: 운영환경(PostgreSQL)은 timezone-aware, 테스트(SQLite)는 naive — 양쪽 호환
    news_cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.news_window_hours)
    news_cutoff_naive = news_cutoff.replace(tzinfo=None)

    # 최근 뉴스에서 긍정 감성 종목 코드 수집
    positive_news_stocks: dict[str, float] = {}  # stock_code -> max sentiment score

    # news_stock_relations를 통해 뉴스와 연결된 종목 조회
    from app.models.news_relation import NewsStockRelation

    recent_positive_news = (
        db.query(NewsArticle)
        .filter(
            # naive cutoff 사용: SQLite 호환 (PostgreSQL에서도 정상 동작)
            NewsArticle.collected_at >= news_cutoff_naive,
            NewsArticle.sentiment.in_(["positive", "strong_positive", "mixed"]),
        )
        .all()
    )

    for article in recent_positive_news:
        score = _positive_sentiment_score(article.sentiment)
        if score < cfg.min_news_sentiment:
            continue
        # 해당 뉴스와 연결된 종목 조회
        relations = (
            db.query(NewsStockRelation)
            .filter(NewsStockRelation.news_id == article.id)
            .all()
        )
        for rel in relations:
            if rel.stock_id:
                stock = db.query(Stock).filter(Stock.id == rel.stock_id).first()
                if stock:
                    existing = positive_news_stocks.get(stock.stock_code, 0.0)
                    positive_news_stocks[stock.stock_code] = max(existing, score)

    if not positive_news_stocks:
        logger.debug("[거래량콤보] 긍정 뉴스 관련 종목 없음")
        return []

    # 거래량 z-score 계산 — naver_finance 히스토리 사용
    # @MX:NOTE: 동기 컨텍스트에서 비동기 함수 호출 불가 → 캐시된 데이터 또는 스킵
    # 실제 운영 환경에서는 fund_manager의 비동기 컨텍스트에서 호출되므로
    # 여기서는 FundSignal 이력에서 volume 대용 데이터를 사용하거나 종목별 처리 스킵
    # 테스트 환경에서는 _volume_provider 주입으로 대체 가능
    results: list[SurgeCandidate] = []

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

        stock = db.query(Stock).filter(Stock.stock_code == stock_code).first()
        stock_name = stock.name if stock else stock_code

        results.append(
            SurgeCandidate(
                stock_code=stock_code,
                stock_name=stock_name,
                combo_score=combo_score,
                active_detectors=["volume_news_combo"],
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
            # 캐시 미스: 동기 HTTP 요청으로 일봉 히스토리 즉시 조회 (TTL=1h 캐싱)
            cached = fetch_stock_price_history_sync(stock_code, pages=3)
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

    results: list[SurgeCandidate] = []
    for _, info in stock_scores.items():
        results.append(
            SurgeCandidate(
                stock_code=info["stock_code"],
                stock_name=info["stock_name"],
                pattern_score=info["score"],
                active_detectors=["disclosure_pattern"],
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

    for disc in recent_disclosures:
        rname = disc.report_name or ""
        best_score = 0.0
        for keyword, score in _IMMEDIATE_EVENT_PATTERNS:
            if keyword in rname:
                best_score = max(best_score, score)
        if best_score == 0.0:
            continue

        if disc.stock_id not in stock_scores or stock_scores[disc.stock_id]["score"] < best_score:
            stock = db.query(Stock).filter(Stock.id == disc.stock_id).first()
            if stock:
                stock_scores[disc.stock_id] = {
                    "score": best_score,
                    "stock_code": stock.stock_code,
                    "stock_name": stock.name,
                    "report_name": rname,
                }

    results: list[SurgeCandidate] = []
    for _, info in stock_scores.items():
        results.append(
            SurgeCandidate(
                stock_code=info["stock_code"],
                stock_name=info["stock_name"],
                immediate_disclosure_score=info["score"],
                active_detectors=["immediate_disclosure"],
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
    활성 탐지기 수에 따른 컨센서스 배율을 적용한다.

    # @MX:NOTE: [AUTO] 컨센서스 배율: 활성 탐지기 1/2/3+개 → 1.00/1.15/1.30
    # @MX:SPEC: SPEC-AI-014 REQ-004

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
    )

    # REQ-AI014-004: 활성 탐지기 수 기반 컨센서스 배율
    # "활성 탐지기" = 해당 탐지기 점수 > 0 인 것
    active_count = sum([
        1 for score in [
            candidate.theme_cluster_score,
            candidate.combo_score,
            best_disclosure_score,
            candidate.legacy_score,
        ] if score > 0
    ])

    if active_count >= 3:
        multiplier = 1.30
    elif active_count == 2:
        multiplier = 1.15
    else:
        multiplier = 1.00

    final_score = min(1.0, weighted_sum * multiplier)

    logger.debug(
        "[앙상블] code=%s weighted_sum=%.4f consensus=%.2f final=%.4f (active_detectors=%d)",
        candidate.stock_code,
        weighted_sum,
        multiplier,
        final_score,
        active_count,
    )

    return final_score


# @MX:NOTE: [AUTO] SPEC-AI-012 앙상블 파이프라인 진입점 — fund_manager._gather_surge_candidates에서 호출
# @MX:SPEC: SPEC-AI-012
def gather_surge_candidates(
    db: Session,
    recent_news: list,
    config: SurgeDetectionConfig,
    legacy_candidates: list[dict],
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
    combo_results = detect_volume_surge_news_combo(db, config)
    pattern_results = detect_disclosure_surge_pattern(db, config)
    # P3: 즉각 공시 이벤트 탐지기 (자사주 소각, 수주, 합병)
    immediate_results = detect_immediate_disclosure_signal(db, config)

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

    # 레거시 탐지기 점수 계산
    # @MX:NOTE: legacy_score = min(1.0, 레거시 탐지기 발동 수 / 4)
    #           leading_signals 키로 몇 개의 선행 탐지기가 발동했는지 확인
    legacy_score_map: dict[str, float] = {}
    for lc in legacy_candidates:
        code = lc.get("code") or lc.get("stock_code")
        if not code:
            continue
        signals = lc.get("leading_signals", [])
        num_triggered = len(signals) if signals else 1  # 후보로 있으면 최소 1개
        legacy_score_map[code] = min(1.0, num_triggered / 4)

    for code, candidate in merged.items():
        if code in legacy_score_map:
            candidate.legacy_score = legacy_score_map[code]
            if "legacy" not in candidate.active_detectors:
                candidate.active_detectors.append("legacy")

    # 앙상블 점수 계산 및 임계값 필터링
    qualified: list[SurgeCandidate] = []
    qualified_codes: set[str] = set()

    for candidate in merged.values():
        score = compute_ensemble_score(candidate, config)
        if score >= config.ensemble.min_score_for_signal:
            qualified.append(candidate)
            qualified_codes.add(candidate.stock_code)

    # P3: 즉각 공시 이벤트 강도 >= 0.70 이면 앙상블 임계값 우회 포함
    # 자사주 소각(0.90), 수주(0.82), 합병(0.82) 등은 다른 탐지기 없이도 즉각 시그널
    _IMMEDIATE_BYPASS_THRESHOLD = 0.70
    for candidate in merged.values():
        if (candidate.stock_code not in qualified_codes
                and candidate.immediate_disclosure_score >= _IMMEDIATE_BYPASS_THRESHOLD):
            qualified.append(candidate)
            qualified_codes.add(candidate.stock_code)
            logger.info(
                "[즉각공시] 앙상블 임계 우회: %s (immediate_score=%.3f)",
                candidate.stock_code,
                candidate.immediate_disclosure_score,
            )

    # 앙상블 점수 내림차순 정렬
    qualified.sort(key=lambda c: compute_ensemble_score(c, config), reverse=True)

    logger.info("[앙상블] 최종 급등 후보 %d개 (임계=%.2f)", len(qualified), config.ensemble.min_score_for_signal)
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
    }
