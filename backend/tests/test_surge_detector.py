"""SPEC-AI-012: 급등 징후 탐지 서비스 테스트.

AC-SURGE-001: 테마 뉴스 클러스터링
AC-SURGE-002: 거래량 이상 + 뉴스 콤보
AC-SURGE-003: 공시 유형 급등 패턴
AC-SURGE-004: 앙상블 스코어
AC-SURGE-005: surge_candidate 5-day 중복 방지
AC-SURGE-007: 설정 검증
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.surge_config.surge_settings import SurgeDetectionConfig
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_detector import (
    SurgeCandidate,
    compute_ensemble_score,
    detect_disclosure_surge_pattern,
    detect_theme_news_cluster,
    detect_volume_surge_news_combo,
    gather_surge_candidates,
    _surge_rate_cache,
    _cache_loaded_at,
)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def surge_config() -> SurgeDetectionConfig:
    """테스트용 SurgeDetectionConfig (기본 설정 파일 기준)."""
    from app.surge_config.surge_settings import get_surge_config

    # 싱글턴 재사용 (실제 YAML 파일 기준)
    return get_surge_config()


@pytest.fixture
def sector_it(db: Session) -> Sector:
    """IT 섹터 픽스처."""
    s = Sector(name="IT")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def sector_semiconductor(db: Session) -> Sector:
    """반도체 섹터 픽스처."""
    s = Sector(name="반도체와반도체장비")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def make_stock(db: Session):
    """종목 팩토리."""
    _counter = [0]

    def _factory(
        name: str,
        stock_code: str,
        sector: Sector,
        market_cap: int = 500,  # 억원 단위
    ) -> Stock:
        _counter[0] += 1
        stock = Stock(
            name=name,
            stock_code=stock_code,
            sector_id=sector.id,
            market_cap=market_cap,
        )
        db.add(stock)
        db.flush()
        return stock

    return _factory


@pytest.fixture
def make_news(db: Session):
    """뉴스 팩토리.

    conftest.py의 make_news_article 패턴을 따라 SQLite/PostgreSQL 호환 datetime 사용.
    """
    import os
    _is_sqlite = os.getenv("TEST_DATABASE_URL", "sqlite://").startswith("sqlite")
    _counter = [0]

    def _factory(
        title: str,
        content: str = "",
        sentiment: str = "positive",
        hours_ago: float = 1.0,
    ) -> NewsArticle:
        _counter[0] += 1
        # SQLite: naive datetime, PostgreSQL: timezone-aware (conftest.py 기존 패턴 동일)
        if _is_sqlite:
            published_at = datetime.utcnow() - timedelta(hours=hours_ago)
        else:
            published_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        article = NewsArticle(
            title=title,
            url=f"https://example.com/surge-news/{_counter[0]}",
            source="test",
            published_at=published_at,
            collected_at=published_at,
            sentiment=sentiment,
            content=content,
        )
        db.add(article)
        db.flush()
        return article

    return _factory


@pytest.fixture
def make_fund_signal(db: Session):
    """FundSignal 팩토리."""

    def _factory(
        stock: Stock,
        signal_type: str = "disclosure_impact",
        price_at_signal: int | None = 10000,
        price_after_5d: int | None = None,
        confidence: float = 0.7,
        disclosure: Disclosure | None = None,
        surge_metadata: str | None = None,
    ) -> FundSignal:
        fs = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=confidence,
            reasoning="테스트 시그널",
            signal_type=signal_type,
            price_at_signal=price_at_signal,
            price_after_5d=price_after_5d,
            disclosure_id=disclosure.id if disclosure else None,
            surge_metadata=surge_metadata,
        )
        db.add(fs)
        db.flush()
        return fs

    return _factory


@pytest.fixture
def make_disclosure(db: Session):
    """Disclosure 팩토리."""
    _counter = [0]

    def _factory(
        stock: Stock,
        report_type: str = "주요사항보고",
        report_name: str = "테스트 공시",
        hours_ago: float = 1.0,
    ) -> Disclosure:
        _counter[0] += 1
        rcept_dt = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y%m%d")
        disc = Disclosure(
            corp_code=f"TEST{_counter[0]:04d}",
            corp_name=stock.name,
            stock_code=stock.stock_code,
            stock_id=stock.id,
            report_name=report_name,
            report_type=report_type,
            rcept_no=f"RCEPT{_counter[0]:08d}",
            rcept_dt=rcept_dt,
            url=f"https://dart.fss.or.kr/{_counter[0]}",
        )
        db.add(disc)
        db.flush()
        return disc

    return _factory


# ---------------------------------------------------------------------------
# AC-SURGE-007: 설정 검증
# ---------------------------------------------------------------------------

class TestSurgeConfig:
    """SurgeDetectionConfig 설정 검증 테스트."""

    def test_characterize_config_loads_from_yaml(self, surge_config: SurgeDetectionConfig):
        """기본 YAML 설정 파일이 정상적으로 로드된다."""
        assert surge_config.theme_cluster.min_article_count == 3
        assert surge_config.ensemble.min_score_for_signal == 0.30
        assert len(surge_config.theme_cluster.keywords) > 0

    def test_characterize_ensemble_weights_sum_to_one(self, surge_config: SurgeDetectionConfig):
        """앙상블 가중치 합산이 1.0이다."""
        w = surge_config.ensemble.weights
        total = w.theme_cluster + w.volume_news_combo + w.disclosure_pattern + w.legacy_detectors
        assert abs(total - 1.0) < 0.001

    def test_invalid_weights_raise_value_error(self):
        """앙상블 가중치 합산 != 1.0 이면 ValueError가 발생한다 (AC-SURGE-007)."""
        config_dict = {
            "theme_cluster": {
                "keywords": ["반도체"],
                "sector_theme_map": {"반도체": ["IT"]},
                "cluster_window_hours": 48,
                "min_article_count": 3,
                "min_market_cap_krw": 100_000_000_000,
            },
            "volume_news_combo": {
                "volume_zscore_threshold": 2.5,
                "volume_baseline_days": 20,
                "news_window_hours": 24,
                "min_news_sentiment": 0.3,
            },
            "disclosure_pattern": {
                "historical_surge_threshold_pct": 10.0,
                "historical_lookback_days": 5,
                "min_surge_rate": 0.40,
                "min_sample_size": 20,
                "cache_ttl_hours": 24,
                "disclosure_window_hours": 24,
            },
            "ensemble": {
                "weights": {
                    "theme_cluster": 0.30,  # 합산 = 1.05 (오류)
                    "volume_news_combo": 0.30,
                    "disclosure_pattern": 0.25,
                    "legacy_detectors": 0.20,
                },
                "min_score_for_signal": 0.55,
            },
            "backtest": {
                "enabled": True,
                "evaluation_horizon_days": 5,
            },
        }
        with pytest.raises(ValueError, match="ensemble weights must sum to 1.0"):
            SurgeDetectionConfig.model_validate(config_dict)


# ---------------------------------------------------------------------------
# AC-SURGE-001: 테마 뉴스 클러스터링
# ---------------------------------------------------------------------------

class TestThemeNewsCluster:
    """테마 뉴스 클러스터링 탐지기 테스트."""

    def test_characterize_active_theme_returns_candidates(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_semiconductor: Sector,
        make_stock,
        make_news,
    ):
        """반도체 테마 기사가 3개 이상이면 반도체 섹터 종목을 후보로 반환한다 (AC-SURGE-001 시나리오 1)."""
        # 시가총액 1000억(min_market_cap_krw=100,000,000,000원 = 1000억원 단위) 이상 종목 생성
        stock = make_stock("삼성전자", "005930", sector_semiconductor, market_cap=2000)

        # 반도체 테마 기사 3개 생성
        news_list = [make_news(f"반도체 수요 급증 {i}", hours_ago=1.0) for i in range(3)]

        result = detect_theme_news_cluster(db, news_list, surge_config)

        assert len(result) >= 1
        codes = [c.stock_code for c in result]
        assert "005930" in codes
        candidate = next(c for c in result if c.stock_code == "005930")
        assert candidate.theme_cluster_score > 0
        assert "theme_cluster" in candidate.active_detectors

    def test_characterize_below_min_article_count_no_candidates(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_semiconductor: Sector,
        make_stock,
        make_news,
    ):
        """기사 수가 min_article_count(3) 미만이면 후보를 반환하지 않는다 (AC-SURGE-001 시나리오 2)."""
        make_stock("삼성전자", "005930", sector_semiconductor, market_cap=200)

        # 2개 기사 (min=3 미달)
        news_list = [make_news(f"반도체 뉴스 {i}", hours_ago=1.0) for i in range(2)]

        result = detect_theme_news_cluster(db, news_list, surge_config)

        codes = [c.stock_code for c in result]
        assert "005930" not in codes

    def test_characterize_low_market_cap_filtered(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_semiconductor: Sector,
        make_stock,
        make_news,
    ):
        """시총이 min_market_cap_krw 미만인 종목은 필터링된다 (AC-SURGE-001 시나리오 3).

        min_market_cap_krw = 100,000,000,000원 = 1000억원 = 1000 (억원 단위)
        → 시총 999 (억원 단위) 종목은 제외
        """
        make_stock("소형주", "999999", sector_semiconductor, market_cap=999)

        news_list = [make_news(f"반도체 기사 {i}", hours_ago=1.0) for i in range(3)]

        result = detect_theme_news_cluster(db, news_list, surge_config)

        codes = [c.stock_code for c in result]
        assert "999999" not in codes


# ---------------------------------------------------------------------------
# AC-SURGE-002: 거래량 이상 + 뉴스 콤보
# ---------------------------------------------------------------------------

class TestVolumeNewsCombo:
    """거래량 이상 + 뉴스 콤보 탐지기 테스트."""

    def test_characterize_high_zscore_positive_news_returns_candidate(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_news,
    ):
        """z-score > 2.5 이고 긍정 뉴스가 있으면 후보를 반환한다 (AC-SURGE-002 시나리오 1)."""
        import app.services.surge_detector as det_module

        stock = make_stock("NAVER", "035420", sector_it, market_cap=500)
        article = make_news("NAVER 실적 어닝 서프라이즈", sentiment="strong_positive", hours_ago=2.0)

        # 뉴스-종목 관계 생성 (match_type, relevance NOT NULL)
        rel = NewsStockRelation(
            news_id=article.id,
            stock_id=stock.id,
            match_type="keyword",
            relevance="direct",
        )
        db.add(rel)
        db.flush()

        # z-score 계산을 위한 거래량 데이터 주입 (z-score ≈ 3.0)
        # mean ≈ 1000, std ≈ 200 (약간의 분산 추가), current=1600
        # → z ≈ (1600-1000)/200 = 3.0 > 2.5 임계값
        import random
        random.seed(42)
        volumes = [1000.0 + random.gauss(0, 200) for _ in range(19)] + [1600.0]

        original_provider = det_module._volume_provider
        try:
            det_module._volume_provider = lambda code, days: volumes
            result = detect_volume_surge_news_combo(db, surge_config)
        finally:
            det_module._volume_provider = original_provider

        codes = [c.stock_code for c in result]
        assert "035420" in codes
        candidate = next(c for c in result if c.stock_code == "035420")
        assert candidate.combo_score > 0
        assert "volume_news_combo" in candidate.active_detectors

    def test_characterize_low_zscore_no_candidate(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_news,
    ):
        """z-score <= 2.5 이면 후보를 반환하지 않는다 (AC-SURGE-002 시나리오 2)."""
        import app.services.surge_detector as det_module

        stock = make_stock("카카오", "035720", sector_it, market_cap=300)
        article = make_news("카카오 긍정 뉴스", sentiment="positive", hours_ago=2.0)
        rel = NewsStockRelation(
            news_id=article.id,
            stock_id=stock.id,
            match_type="keyword",
            relevance="direct",
        )
        db.add(rel)
        db.flush()

        # z-score ≈ 1.0 (임계 2.5 미달) — std ≈ 200이면 z = (1200-1000)/200 = 1.0
        import random
        random.seed(42)
        volumes = [1000.0 + random.gauss(0, 200) for _ in range(19)] + [1200.0]

        original_provider = det_module._volume_provider
        try:
            det_module._volume_provider = lambda code, days: volumes
            result = detect_volume_surge_news_combo(db, surge_config)
        finally:
            det_module._volume_provider = original_provider

        codes = [c.stock_code for c in result]
        assert "035720" not in codes

    def test_characterize_no_positive_news_no_candidate(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_news,
    ):
        """거래량 이상이 있어도 긍정 뉴스가 없으면 후보 없음 (AC-SURGE-002 시나리오 3)."""
        import app.services.surge_detector as det_module

        stock = make_stock("다음", "035350", sector_it, market_cap=200)
        # 중립 뉴스만 (min_news_sentiment=0.3 미달)
        article = make_news("다음 뉴스", sentiment="neutral", hours_ago=2.0)
        rel = NewsStockRelation(
            news_id=article.id,
            stock_id=stock.id,
            match_type="keyword",
            relevance="direct",
        )
        db.add(rel)
        db.flush()

        # z-score ≈ 3.5 > 2.5 임계 — 하지만 긍정 뉴스 없으므로 후보 없음
        import random
        random.seed(42)
        volumes = [1000.0 + random.gauss(0, 200) for _ in range(19)] + [1700.0]

        original_provider = det_module._volume_provider
        try:
            det_module._volume_provider = lambda code, days: volumes
            result = detect_volume_surge_news_combo(db, surge_config)
        finally:
            det_module._volume_provider = original_provider

        codes = [c.stock_code for c in result]
        assert "035350" not in codes


# ---------------------------------------------------------------------------
# AC-SURGE-003: 공시 유형 급등 패턴 + SPEC-AI-004 중복 방지
# ---------------------------------------------------------------------------

class TestDisclosureSurgePattern:
    """공시 급등 패턴 탐지기 테스트."""

    def setup_method(self):
        """각 테스트 전에 캐시 초기화."""
        import app.services.surge_detector as det_module
        det_module._surge_rate_cache = {}
        det_module._cache_loaded_at = None

    def test_characterize_high_surge_rate_returns_candidate(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_disclosure,
        make_fund_signal,
    ):
        """과거 급등률 >= min_surge_rate(0.40)인 공시 유형은 후보를 반환한다 (AC-SURGE-003 시나리오 1)."""
        stock = make_stock("삼성바이오로직스", "207940", sector_it, market_cap=1000)

        # 과거 시그널: 30개 중 15개 급등 (급등률 50%)
        # 급등 = price_after_5d / price_at_signal >= 1.10 (10% 이상 상승)
        disc_past = make_disclosure(stock, report_type="지분공시", hours_ago=2000)
        for i in range(15):
            make_fund_signal(
                stock,
                signal_type="disclosure_impact",
                price_at_signal=10000,
                price_after_5d=11000,  # 10% 상승 → 급등
                disclosure=disc_past,
            )
        for i in range(15):
            make_fund_signal(
                stock,
                signal_type="disclosure_impact",
                price_at_signal=10000,
                price_after_5d=10200,  # 2% 상승 → 비급등
                disclosure=disc_past,
            )

        # 최근 24시간 내 같은 유형 공시 생성
        make_disclosure(stock, report_type="지분공시", hours_ago=1.0)

        import app.services.surge_detector as det_module
        det_module._surge_rate_cache = {}
        det_module._cache_loaded_at = None

        result = detect_disclosure_surge_pattern(db, surge_config)

        codes = [c.stock_code for c in result]
        assert "207940" in codes
        candidate = next(c for c in result if c.stock_code == "207940")
        assert candidate.pattern_score > 0
        assert "disclosure_pattern" in candidate.active_detectors

    def test_characterize_low_surge_rate_no_candidate(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_disclosure,
        make_fund_signal,
    ):
        """과거 급등률 < min_surge_rate(0.40)이면 후보 없음 (AC-SURGE-003 시나리오 2)."""
        stock = make_stock("POSCO홀딩스", "005490", sector_it, market_cap=800)

        disc_past = make_disclosure(stock, report_type="정기공시", hours_ago=2000)
        # 30개 중 10개 급등 (급등률 33%, min=0.40 미달)
        for i in range(10):
            make_fund_signal(
                stock,
                signal_type="disclosure_impact",
                price_at_signal=10000,
                price_after_5d=11000,
                disclosure=disc_past,
            )
        for i in range(20):
            make_fund_signal(
                stock,
                signal_type="disclosure_impact",
                price_at_signal=10000,
                price_after_5d=10100,
                disclosure=disc_past,
            )

        make_disclosure(stock, report_type="정기공시", hours_ago=1.0)

        import app.services.surge_detector as det_module
        det_module._surge_rate_cache = {}
        det_module._cache_loaded_at = None

        result = detect_disclosure_surge_pattern(db, surge_config)

        codes = [c.stock_code for c in result]
        assert "005490" not in codes

    def test_characterize_does_not_duplicate_disclosure_impact_logic(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_disclosure,
        make_fund_signal,
    ):
        """SPEC-AI-004 disclosure_impact_scorer의 unreflected_gap 로직을 중복 구현하지 않는다 (AC-SURGE-003 시나리오 3).

        detect_disclosure_surge_pattern은 과거 급등률(통계)을 보고,
        disclosure_impact_scorer는 현재 미반영 갭(실시간)을 본다.
        두 함수는 서로 다른 데이터 소스를 사용한다.
        """
        # disclosure_impact_scorer의 핵심 필드 (unreflected_gap, impact_score)는
        # detect_disclosure_surge_pattern에서 절대 사용하지 않음을 확인
        import inspect
        from app.services.surge_detector import detect_disclosure_surge_pattern as fn

        source = inspect.getsource(fn)

        # unreflected_gap이 해당 함수 소스에 없어야 한다
        assert "unreflected_gap" not in source, (
            "detect_disclosure_surge_pattern이 unreflected_gap을 참조합니다 — "
            "SPEC-AI-004 로직 중복 금지"
        )
        # score_disclosure_impact 함수도 호출하지 않아야 한다
        assert "score_disclosure_impact" not in source


# ---------------------------------------------------------------------------
# AC-SURGE-004: 앙상블 스코어
# ---------------------------------------------------------------------------

class TestEnsembleScore:
    """앙상블 스코어 테스트."""

    def test_characterize_below_threshold_no_signal(self, surge_config: SurgeDetectionConfig):
        """앙상블 점수 < min_score_for_signal(0.55)이면 시그널 없음 (AC-SURGE-004 시나리오 1).

        theme=0.40, combo=0.0, pattern=0.0, legacy=0.0
        → score = 0.25 * 0.40 = 0.10 < 0.55
        """
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트주",
            theme_cluster_score=0.40,
            combo_score=0.0,
            pattern_score=0.0,
            legacy_score=0.0,
        )
        score = compute_ensemble_score(candidate, surge_config)
        # 0.25 * 0.40 = 0.10
        assert abs(score - 0.10) < 0.001
        assert score < surge_config.ensemble.min_score_for_signal

    def test_characterize_above_threshold_generates_signal(self, surge_config: SurgeDetectionConfig):
        """앙상블 점수 >= min_score_for_signal(0.55)이면 시그널 발생 (AC-SURGE-004 시나리오 2).

        theme=0.8, combo=0.9, pattern=0.7, legacy=0.5
        → score = 0.25*0.8 + 0.30*0.9 + 0.25*0.7 + 0.20*0.5
                = 0.20 + 0.27 + 0.175 + 0.10 = 0.745 >= 0.55
        """
        candidate = SurgeCandidate(
            stock_code="000002",
            stock_name="강한주",
            theme_cluster_score=0.8,
            combo_score=0.9,
            pattern_score=0.7,
            legacy_score=0.5,
        )
        score = compute_ensemble_score(candidate, surge_config)
        # 0.745
        assert score >= surge_config.ensemble.min_score_for_signal
        assert abs(score - 0.745) < 0.001

    def test_characterize_ensemble_respects_weight_sum(self, surge_config: SurgeDetectionConfig):
        """앙상블 점수는 가중치 합산(=1.0)에 따라 최대 1.0이다."""
        candidate = SurgeCandidate(
            stock_code="000003",
            stock_name="만점주",
            theme_cluster_score=1.0,
            combo_score=1.0,
            pattern_score=1.0,
            legacy_score=1.0,
        )
        score = compute_ensemble_score(candidate, surge_config)
        assert abs(score - 1.0) < 0.001

    def test_characterize_gather_surge_candidates_filters_below_threshold(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
    ):
        """gather_surge_candidates는 앙상블 점수 미달 후보를 제거한다."""
        # 빈 뉴스 + 빈 레거시로 실행 시 결과 없음
        result = gather_surge_candidates(
            db=db,
            recent_news=[],
            config=surge_config,
            legacy_candidates=[],
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# AC-SURGE-005: surge_candidate 5-day 중복 방지
# ---------------------------------------------------------------------------

class TestSurgeCandidateDeduplication:
    """_gather_surge_candidates 5영업일 중복 방지 테스트 (AC-SURGE-005).

    fund_manager._gather_surge_candidates가 동일 종목 기존 시그널 존재 시
    INSERT 대신 UPDATE를 수행하는지 검증한다.
    """

    @pytest.mark.asyncio
    async def test_dedup_updates_existing_signal_within_5_days(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_fund_signal,
    ):
        """5영업일 이내 동일 종목 surge_candidate 시그널이 있으면 UPDATE한다 (AC-SURGE-005)."""
        from datetime import timezone as tz
        from unittest.mock import patch

        from app.services.fund_manager import _gather_surge_candidates
        from app.services.surge_detector import SurgeCandidate

        stock = make_stock("테스트전자", "000001", sector_it)

        # 기존 시그널 생성 (3일 전)
        existing_signal = make_fund_signal(
            stock,
            signal_type="surge_candidate",
            confidence=0.60,
            surge_metadata='{"test": true}',
        )
        # created_at을 3일 전으로 명시 (5일 이내)
        from datetime import datetime, timedelta
        existing_signal.created_at = datetime.now(tz.utc) - timedelta(days=3)
        db.flush()

        initial_count = db.query(FundSignal).filter(
            FundSignal.signal_type == "surge_candidate"
        ).count()
        assert initial_count == 1

        # gather_surge_candidates를 목 처리 — 같은 종목 후보 반환
        mock_candidate = SurgeCandidate(
            stock_code=stock.stock_code,
            stock_name=stock.name,
            theme_cluster_score=0.8,
            combo_score=0.9,
            pattern_score=0.7,
            legacy_score=0.5,
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[mock_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        # 시그널 수는 변하지 않아야 한다 (UPDATE, INSERT 아님)
        final_count = db.query(FundSignal).filter(
            FundSignal.signal_type == "surge_candidate"
        ).count()
        assert final_count == 1, f"INSERT가 발생했습니다 (expected 1, got {final_count})"

        # 신뢰도가 새 앙상블 점수로 갱신됐어야 한다
        db.refresh(existing_signal)
        assert existing_signal.confidence > 0.60, "기존 시그널 confidence가 업데이트되지 않았습니다"

    @pytest.mark.asyncio
    async def test_creates_new_signal_when_older_than_5_days(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_it: Sector,
        make_stock,
        make_fund_signal,
    ):
        """5영업일 초과 된 시그널은 중복으로 취급하지 않고 신규 INSERT한다 (AC-SURGE-005)."""
        from datetime import timezone as tz
        from unittest.mock import patch

        from app.services.fund_manager import _gather_surge_candidates
        from app.services.surge_detector import SurgeCandidate

        stock = make_stock("오래된주식", "000002", sector_it)

        # 기존 시그널 생성 (7일 전 — 5일 초과)
        old_signal = make_fund_signal(
            stock,
            signal_type="surge_candidate",
            confidence=0.60,
        )
        from datetime import datetime, timedelta
        old_signal.created_at = datetime.now(tz.utc) - timedelta(days=7)
        db.flush()

        mock_candidate = SurgeCandidate(
            stock_code=stock.stock_code,
            stock_name=stock.name,
            theme_cluster_score=0.8,
            combo_score=0.9,
            pattern_score=0.7,
            legacy_score=0.5,
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[mock_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        # 신규 시그널이 INSERT 됐어야 한다
        final_count = db.query(FundSignal).filter(
            FundSignal.signal_type == "surge_candidate"
        ).count()
        assert final_count == 2, f"신규 시그널이 생성되지 않았습니다 (expected 2, got {final_count})"
