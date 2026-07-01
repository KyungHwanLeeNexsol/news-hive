"""SPEC-AI-066: 확신도 기반 선행 급등 신호 정밀화 — 인수 검증 테스트.

AC 검증 목록:
  - AC-1 (REQ-001): 촉매 확신도 tier 산출 (HIGH/LOW/NONE)
  - AC-2 (REQ-002): combo 과열 게이트 확신도 차등 완화 (HIGH 통과, 분산/stale 여전 차단)
  - AC-3 (REQ-003): 전략적 인수 공시 페널티 부분완화 (0.7 vs 0.3)
  - AC-4 (REQ-004): co-mention 테마 자동 확장 (기능 활성 시)
  - AC-5 (REQ-005): volume_breakout 유니버스 확장 + 상대 임계 (기능 활성 시)
  - AC-7 (REQ-007): 이벤트 구동 재스캔 (쿨다운/일일상한/정기스캔 불변)
  - AC-6 (REQ-006): 설정 부재 기본값 + enabled=false 레거시 동등
  - Edge Cases + 위메이드형 통합 회귀
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import ARRAY, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.surge_config.surge_settings as _settings_module
from app.database import Base
from app.models.disclosure import Disclosure
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_detector import (
    CONVICTION_HIGH,
    CONVICTION_LOW,
    CONVICTION_NONE,
    ConvictionEvidence,
    compute_catalyst_conviction,
    detect_immediate_disclosure_signal,
    detect_theme_news_cluster,
    detect_volume_breakout,
    detect_volume_surge_news_combo,
)
from app.surge_config.surge_settings import (
    CatalystConvictionConfig,
    ComboChaseGuardConfig,
    DisclosureTypeFilterConfig,
    VolumeBreakoutConfig,
    get_surge_config,
)


# ---------------------------------------------------------------------------
# 인메모리 SQLite DB 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    @compiles(ARRAY, "sqlite")
    def _array_sqlite(type_, compiler, **kw):
        return "TEXT"

    _engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture()
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def reset_config_singleton():
    _settings_module._config_singleton = None
    yield
    _settings_module._config_singleton = None


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _sector(db: Session) -> int:
    s = db.query(Sector).filter(Sector.name == "테스트섹터_ai066").first()
    if not s:
        s = Sector(name="테스트섹터_ai066")
        db.add(s)
        db.flush()
    return s.id


def _make_stock(db: Session, code: str, name: str = "테스트종목", market_cap=None) -> Stock:
    stock = Stock(stock_code=code, name=name, sector_id=_sector(db), market_cap=market_cap)
    db.add(stock)
    db.flush()
    return stock


_counter = [0]


def _make_news(
    db: Session,
    stock_id: int,
    *,
    title: str = "테스트뉴스",
    sentiment: str = "positive",
    hours_ago: float = 1.0,
    ai_summary: str | None = None,
) -> NewsArticle:
    _counter[0] += 1
    ts = datetime.now() - timedelta(hours=hours_ago)
    article = NewsArticle(
        title=title,
        content="테스트내용",
        summary="",
        url=f"http://ex.com/{stock_id}-{_counter[0]}",
        source="테스트",
        sentiment=sentiment,
        ai_summary=ai_summary,
        collected_at=ts,
        published_at=ts,
    )
    db.add(article)
    db.flush()
    db.add(
        NewsStockRelation(
            news_id=article.id, stock_id=stock_id, match_type="keyword", relevance="direct"
        )
    )
    db.flush()
    return article


def _make_disclosure(db: Session, stock_id: int, report_name: str, ai_summary: str = "") -> Disclosure:
    _counter[0] += 1
    disc = Disclosure(
        stock_id=stock_id,
        corp_code="00000000",
        corp_name="테스트법인",
        report_name=report_name,
        ai_summary=ai_summary,
        rcept_dt=datetime.now().strftime("%Y%m%d"),
        rcept_no=f"R{_counter[0]}{stock_id}",
        url=f"http://dart.example.com/{_counter[0]}",
    )
    db.add(disc)
    db.flush()
    return disc


def _cfg(
    *,
    catalyst_overrides: dict | None = None,
    guard_overrides: dict | None = None,
    disc_overrides: dict | None = None,
    vb_overrides: dict | None = None,
):
    """기본 설정에 SPEC-AI-066 관련 섹션들을 오버라이드한 SurgeDetectionConfig 반환."""
    base = get_surge_config()
    updates: dict = {}

    catalyst = CatalystConvictionConfig(
        **{**CatalystConvictionConfig().model_dump(), **(catalyst_overrides or {})}
    )
    updates["catalyst_conviction"] = catalyst

    if guard_overrides is not None:
        updates["combo_chase_guard"] = ComboChaseGuardConfig(
            **{**ComboChaseGuardConfig().model_dump(), **guard_overrides}
        )
    if disc_overrides is not None:
        updates["disclosure_type_filter"] = DisclosureTypeFilterConfig(
            **{**DisclosureTypeFilterConfig().model_dump(), **disc_overrides}
        )
    if vb_overrides is not None:
        updates["volume_breakout"] = VolumeBreakoutConfig(
            **{**VolumeBreakoutConfig().model_dump(), **vb_overrides}
        )
    # combo 탐지기 강제 활성 (단위테스트)
    updates["volume_news_combo"] = base.volume_news_combo.model_copy(update={"enabled": True})
    return base.model_copy(update=updates)


# 강한 z-score를 만드는 volume 히스토리 (fresh)
_VOL_FRESH = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]
# stale (freshness=1.0)
_VOL_STALE = [1000.0] * 16 + [1200.0, 800.0] + [5000.0, 5000.0]


# ===========================================================================
# AC-6 / REQ-006: 설정 및 하위 호환
# ===========================================================================

class TestConfigDefaults:
    def test_catalyst_defaults(self):
        c = CatalystConvictionConfig()
        assert c.enabled is True
        assert c.min_article_count_high == 5
        assert c.min_coverage_hours_high == 6.0
        assert c.min_sentiment_high == 0.5
        assert c.comention_theme_enabled is False
        assert c.event_rescan_enabled is False
        assert c.event_rescan_cooldown_minutes == 30
        assert c.max_daily_event_triggers == 20
        assert any("인수" in kw or kw == "인수" for kw in c.acquisition_keywords)

    def test_new_fields_on_existing_configs(self):
        assert ComboChaseGuardConfig().overheat_change_pct_high_conviction == 15.0
        assert DisclosureTypeFilterConfig().acquisition_exemption_enabled is True
        assert DisclosureTypeFilterConfig().acquisition_penalty_factor == 0.7
        assert VolumeBreakoutConfig().relative_threshold_enabled is False

    def test_yaml_loads_catalyst_section(self):
        cfg = get_surge_config()
        assert cfg.catalyst_conviction.enabled is True
        assert cfg.combo_chase_guard.overheat_change_pct_high_conviction == 15.0
        assert cfg.disclosure_type_filter.acquisition_penalty_factor == 0.7
        # 소유 경계 불변: AI-062 가중치 / AI-063 bypass 임계
        assert cfg.volume_breakout.volume_breakout_bypass_threshold == 0.30
        assert cfg.ensemble.weights.volume_breakout == 0.11

    def test_absent_section_uses_defaults(self):
        """catalyst_conviction 섹션 없이도 로드 에러 없이 기본값 동작 (AC-6.1)."""
        # 부분 dict로 모델 검증 시 default_factory가 채워지는지 확인
        from app.surge_config.surge_settings import SurgeDetectionConfig
        full = get_surge_config().model_dump()
        full.pop("catalyst_conviction", None)
        cfg = SurgeDetectionConfig.model_validate(full)
        assert isinstance(cfg.catalyst_conviction, CatalystConvictionConfig)
        assert cfg.catalyst_conviction.enabled is True


# ===========================================================================
# AC-1 / REQ-001: 확신도 tier 산출
# ===========================================================================

class TestConvictionTier:
    def test_strong_catalyst_high(self):
        """15건 다출처 + 16h span + 감성 + 인수 키워드 → HIGH (AC-1.1)."""
        ev = ConvictionEvidence(
            article_count=15,
            coverage_hours=16.0,
            sentiment_score=0.7,
            has_high_impact_keyword=True,
            has_backing_disclosure=True,
        )
        assert compute_catalyst_conviction(ev, get_surge_config()) == CONVICTION_HIGH

    def test_thin_single_news_non_high(self):
        """1건 단발 + 공시 없음 → non-HIGH (AC-1.2)."""
        ev = ConvictionEvidence(article_count=1, coverage_hours=0.0, sentiment_score=0.7)
        assert compute_catalyst_conviction(ev, get_surge_config()) == CONVICTION_LOW

    def test_no_evidence_lowest(self):
        """뉴스 없음 + 공시 없음 → 최저 tier (결코 HIGH 아님) (AC-1.3)."""
        ev = ConvictionEvidence()
        assert compute_catalyst_conviction(ev, get_surge_config()) == CONVICTION_NONE

    def test_span_zero_cannot_be_high(self):
        """단발 기사(span=0) → 지속시간 미충족 → HIGH 불가 (Edge)."""
        ev = ConvictionEvidence(
            article_count=20, coverage_hours=0.0, sentiment_score=1.0, has_high_impact_keyword=True
        )
        assert compute_catalyst_conviction(ev, get_surge_config()) != CONVICTION_HIGH

    def test_news_only_high_without_disclosure(self):
        """공시 없이 뉴스만으로 HIGH 승격 가능 (위메이드형 핵심, Edge)."""
        ev = ConvictionEvidence(
            article_count=15,
            coverage_hours=16.0,
            sentiment_score=0.7,
            has_high_impact_keyword=True,
            has_backing_disclosure=False,
        )
        assert compute_catalyst_conviction(ev, get_surge_config()) == CONVICTION_HIGH

    def test_enabled_false_disables_relaxation_paths_but_tier_still_computes(self):
        """enabled=false여도 tier 산출 자체는 순수함수라 동작 (완화 적용은 호출부에서 차단)."""
        cfg = _cfg(catalyst_overrides={"enabled": False})
        ev = ConvictionEvidence(
            article_count=15, coverage_hours=16.0, sentiment_score=0.7, has_high_impact_keyword=True
        )
        assert compute_catalyst_conviction(ev, cfg) == CONVICTION_HIGH


# ===========================================================================
# AC-2 / REQ-002: combo 과열 게이트 확신도 차등 완화
# ===========================================================================

def _make_high_conviction_news(db, stock_id, n=15, keyword="인수"):
    """HIGH 확신도 조건을 만족하는 다출처 지속 뉴스 생성."""
    for i in range(n):
        _make_news(
            db,
            stock_id,
            title=f"{keyword} 관련 대형 호재 보도 {i}",
            sentiment="positive",
            hours_ago=1.0 + i * (16.0 / n),  # 첫~마지막 span ≈ 16h
        )


class TestComboOverheatConviction:
    def test_high_conviction_passes_overheat(self, db):
        """HIGH 확신도 +12% → 상향 상한(15%)으로 통과 (AC-2.1)."""
        stock = _make_stock(db, "112040", "위메이드")
        _make_high_conviction_news(db, stock.id)
        cfg = _cfg(
            catalyst_overrides={"enabled": True},
            guard_overrides={"enabled": True, "overheat_change_pct": 5.0,
                             "overheat_change_pct_high_conviction": 15.0,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_FRESH), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_volume_surge_news_combo(db, cfg)
        assert any(r.stock_code == "112040" for r in results), "HIGH 확신도 12% → 통과"

    def test_non_high_overheat_excluded(self, db):
        """non-HIGH +7% → 기존 5% 상한으로 제외 (AC-2.2)."""
        stock = _make_stock(db, "222222", "얇은뉴스종목")
        _make_news(db, stock.id, title="단발 뉴스", sentiment="positive", hours_ago=1.0)
        cfg = _cfg(
            catalyst_overrides={"enabled": True},
            guard_overrides={"enabled": True, "overheat_change_pct": 5.0,
                             "overheat_change_pct_high_conviction": 15.0,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_FRESH), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 7.0}):
            results = detect_volume_surge_news_combo(db, cfg)
        assert not any(r.stock_code == "222222" for r in results), "non-HIGH 7% → 제외"

    def test_high_conviction_but_distribution_still_excluded(self, db):
        """HIGH 확신도지만 change_rate<0(분산) → Gate3로 여전히 제외 (AC-2.3, 안전 불변식)."""
        stock = _make_stock(db, "333333", "분산종목")
        _make_high_conviction_news(db, stock.id)
        cfg = _cfg(
            catalyst_overrides={"enabled": True},
            guard_overrides={"enabled": True, "distribution_change_pct": 0.0,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_FRESH), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": -2.0}):
            results = detect_volume_surge_news_combo(db, cfg)
        assert not any(r.stock_code == "333333" for r in results), "HIGH여도 분산 → 제외"

    def test_high_conviction_but_stale_still_excluded(self, db):
        """HIGH 확신도지만 freshness<1.5(stale) → Gate2로 여전히 제외 (AC-2.4, 안전 불변식)."""
        stock = _make_stock(db, "444444", "stale종목")
        _make_high_conviction_news(db, stock.id)
        cfg = _cfg(
            catalyst_overrides={"enabled": True},
            guard_overrides={"enabled": True, "min_freshness_ratio": 1.5,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_STALE), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 2.0}):
            results = detect_volume_surge_news_combo(db, cfg)
        assert not any(r.stock_code == "444444" for r in results), "HIGH여도 stale → 제외"

    def test_switch_off_restores_legacy(self, db):
        """enabled=false → 기본 5% 상한 적용 → HIGH-룩 12%도 제외 (AC-2.5, 레거시)."""
        stock = _make_stock(db, "555555", "스위치오프종목")
        _make_high_conviction_news(db, stock.id)
        cfg = _cfg(
            catalyst_overrides={"enabled": False},
            guard_overrides={"enabled": True, "overheat_change_pct": 5.0,
                             "overheat_change_pct_high_conviction": 15.0,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_FRESH), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_volume_surge_news_combo(db, cfg)
        assert not any(r.stock_code == "555555" for r in results), "enabled=false → 5% 상한 → 제외"


# ===========================================================================
# AC-3 / REQ-003: 전략적 인수 공시 페널티 예외
# ===========================================================================

class TestDisclosurePenaltyExemption:
    def test_acquisition_partial_mitigation(self, db):
        """호재성 인수 최대주주변경 → 페널티 0.7 부분완화 + bullish (AC-3.1)."""
        stock = _make_stock(db, "112040", "위메이드")
        _make_news(db, stock.id, title="위메이드 경영권 인수 호재", sentiment="positive", hours_ago=1.0)
        _make_disclosure(db, stock.id, report_name="최대주주변경 흡수합병결정")
        cfg = _cfg(catalyst_overrides={"enabled": True},
                   disc_overrides={"acquisition_exemption_enabled": True,
                                   "penalty_factor": 0.3, "acquisition_penalty_factor": 0.7})
        with patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_immediate_disclosure_signal(db, cfg)
        cand = next(r for r in results if r.stock_code == "112040")
        # 흡수합병결정 base=0.82, factor=0.7 → 0.574
        assert cand.immediate_disclosure_score == pytest.approx(0.82 * 0.7, abs=1e-3)
        assert cand.disclosure_sentiment == "bullish"

    def test_distress_keeps_full_penalty(self, db):
        """부실 매각형 최대주주변경(인수 키워드 없음) → 페널티 0.3 유지 + bearish (AC-3.2)."""
        stock = _make_stock(db, "666666", "부실종목")
        _make_disclosure(db, stock.id, report_name="최대주주변경 자기주식취득결정")
        cfg = _cfg(catalyst_overrides={"enabled": True},
                   disc_overrides={"acquisition_exemption_enabled": True,
                                   "penalty_factor": 0.3, "acquisition_penalty_factor": 0.7})
        with patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_immediate_disclosure_signal(db, cfg)
        cand = next(r for r in results if r.stock_code == "666666")
        # 자기주식취득결정 base=0.70, factor=0.3 → 0.21
        assert cand.immediate_disclosure_score == pytest.approx(0.70 * 0.3, abs=1e-3)
        assert cand.disclosure_sentiment == "bearish"

    def test_acquisition_keyword_but_negative_price_keeps_penalty(self, db):
        """인수 키워드 있으나 change_rate<0 → 3중 조건 미충족 → 페널티 유지 (Edge)."""
        stock = _make_stock(db, "777777", "인수하락종목")
        _make_news(db, stock.id, title="경영권 인수 보도", sentiment="positive", hours_ago=1.0)
        _make_disclosure(db, stock.id, report_name="최대주주변경 흡수합병결정")
        cfg = _cfg(catalyst_overrides={"enabled": True},
                   disc_overrides={"acquisition_exemption_enabled": True})
        with patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": -1.0}):
            results = detect_immediate_disclosure_signal(db, cfg)
        cand = next(r for r in results if r.stock_code == "777777")
        assert cand.immediate_disclosure_score == pytest.approx(0.82 * 0.3, abs=1e-3)

    def test_switch_off_full_penalty(self, db):
        """acquisition_exemption_enabled=false → 예외 없이 전면 페널티 (AC-3.3)."""
        stock = _make_stock(db, "888888", "스위치오프공시")
        _make_news(db, stock.id, title="경영권 인수 호재", sentiment="positive", hours_ago=1.0)
        _make_disclosure(db, stock.id, report_name="최대주주변경 흡수합병결정")
        cfg = _cfg(catalyst_overrides={"enabled": True},
                   disc_overrides={"acquisition_exemption_enabled": False})
        with patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_immediate_disclosure_signal(db, cfg)
        cand = next(r for r in results if r.stock_code == "888888")
        assert cand.immediate_disclosure_score == pytest.approx(0.82 * 0.3, abs=1e-3)

    def test_catalyst_disabled_full_penalty(self, db):
        """catalyst_conviction.enabled=false → 전면 페널티 (레거시)."""
        stock = _make_stock(db, "889999", "촉매오프공시")
        _make_news(db, stock.id, title="경영권 인수 호재", sentiment="positive", hours_ago=1.0)
        _make_disclosure(db, stock.id, report_name="최대주주변경 흡수합병결정")
        cfg = _cfg(catalyst_overrides={"enabled": False},
                   disc_overrides={"acquisition_exemption_enabled": True})
        with patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_immediate_disclosure_signal(db, cfg)
        cand = next(r for r in results if r.stock_code == "889999")
        assert cand.immediate_disclosure_score == pytest.approx(0.82 * 0.3, abs=1e-3)


# ===========================================================================
# AC-4 / REQ-004: co-mention 테마 자동 확장
# ===========================================================================

class TestComentionTheme:
    def _cluster_news(self, db, stock_ids, n=3):
        """n개 기사가 stock_ids를 동일 기사에서 반복 공동언급."""
        for i in range(n):
            _counter[0] += 1
            ts = datetime.now() - timedelta(hours=1.0)
            art = NewsArticle(
                title=f"공동언급 기사 {i}", content="내용", summary="",
                url=f"http://ex.com/cm-{_counter[0]}", source="테스트",
                sentiment="positive", collected_at=ts, published_at=ts,
            )
            db.add(art)
            db.flush()
            for sid in stock_ids:
                db.add(NewsStockRelation(news_id=art.id, stock_id=sid,
                                         match_type="keyword", relevance="direct"))
            db.flush()

    def test_non_affiliate_cluster_identified(self, db):
        """비계열 종목이 comention_min_pairs 이상 동반 등장 → 클러스터 후보 생성 (AC-4.1)."""
        a = _make_stock(db, "101010", "가나다전자")
        b = _make_stock(db, "202020", "라마바화학")
        self._cluster_news(db, [a.id, b.id], n=3)
        cfg = _cfg(catalyst_overrides={"comention_theme_enabled": True, "comention_min_pairs": 3})
        results = detect_theme_news_cluster(db, [], cfg)
        codes = {r.stock_code for r in results}
        assert "101010" in codes and "202020" in codes, "비계열 co-mention 클러스터 → 후보 생성"

    def test_affiliate_cluster_excluded(self, db):
        """동일 그룹 계열사(접두사 공유) → group_cascade 소관 → 이중 카운트 배제 (AC-4.2)."""
        a = _make_stock(db, "303030", "삼성전자")
        b = _make_stock(db, "404040", "삼성SDI")
        self._cluster_news(db, [a.id, b.id], n=3)
        cfg = _cfg(catalyst_overrides={"comention_theme_enabled": True, "comention_min_pairs": 3})
        results = detect_theme_news_cluster(db, [], cfg)
        codes = {r.stock_code for r in results}
        assert "303030" not in codes and "404040" not in codes, "계열사 클러스터 → 배제"

    def test_disabled_fallback(self, db):
        """comention_theme_enabled=false → co-mention 후보 없음 (AC-4.3, 레거시)."""
        a = _make_stock(db, "505050", "가나다전자")
        b = _make_stock(db, "606060", "라마바화학")
        self._cluster_news(db, [a.id, b.id], n=3)
        cfg = _cfg(catalyst_overrides={"comention_theme_enabled": False})
        results = detect_theme_news_cluster(db, [], cfg)
        codes = {r.stock_code for r in results}
        assert "505050" not in codes and "606060" not in codes, "비활성 → co-mention 후보 없음"

    def test_single_stock_no_cluster(self, db):
        """1종목만 언급 → 쌍 부재 → 클러스터 미형성 (Edge)."""
        a = _make_stock(db, "707070", "단독종목")
        self._cluster_news(db, [a.id], n=3)
        cfg = _cfg(catalyst_overrides={"comention_theme_enabled": True, "comention_min_pairs": 3})
        results = detect_theme_news_cluster(db, [], cfg)
        assert not any(r.stock_code == "707070" for r in results)


# ===========================================================================
# AC-5 / REQ-005: volume_breakout 유니버스 확장 + 상대 임계
# ===========================================================================

class _Bar:
    def __init__(self, volume):
        self.volume = volume
        self.close_price = 10000


def _hist(today_vol, baseline_vol, n_baseline=20, jitter=None):
    """history[0]=today, 이후 baseline. jitter로 표준편차 부여."""
    bars = [_Bar(today_vol)]
    for i in range(n_baseline):
        v = baseline_vol
        if jitter is not None:
            v = baseline_vol + (jitter if i % 2 == 0 else -jitter)
        bars.append(_Bar(v))
    return bars


class TestVolumeBreakoutRelative:
    def test_relative_threshold_catches_midcap(self, db):
        """상대 임계로 절대비율 2.5x(<3.0) 중대형주 포착 (AC-5.2)."""
        _make_stock(db, "111111", "중대형주")
        cfg = _cfg(vb_overrides={"enabled": True, "relative_threshold_enabled": True,
                                 "volume_ratio_threshold": 3.0})
        # ratio 2.5, 낮은 분산 → z-score 매우 높음
        hist = _hist(2500.0, 1000.0, jitter=10.0)
        with patch("app.services.naver_finance.fetch_volume_leaders_sync", return_value=["111111"]), \
             patch("app.services.naver_finance.fetch_stock_price_history_sync", return_value=hist):
            results = detect_volume_breakout(db, cfg)
        assert any(r.stock_code == "111111" for r in results), "상대 임계로 2.5x 중대형주 포착"

    def test_flat_only_excludes_subthreshold(self, db):
        """relative 비활성 → 2.5x는 고정 3.0 미달로 제외 (레거시 회귀)."""
        _make_stock(db, "121212", "중대형주2")
        cfg = _cfg(vb_overrides={"enabled": True, "relative_threshold_enabled": False,
                                 "volume_ratio_threshold": 3.0})
        hist = _hist(2500.0, 1000.0, jitter=10.0)
        with patch("app.services.naver_finance.fetch_volume_leaders_sync", return_value=["121212"]), \
             patch("app.services.naver_finance.fetch_stock_price_history_sync", return_value=hist):
            results = detect_volume_breakout(db, cfg)
        assert not any(r.stock_code == "121212" for r in results), "비활성 → 2.5x 제외"

    def test_cold_start_falls_back_to_flat(self, db):
        """분산 0(cold-start z=None) → 고정 3.0x 폴백. 3.5x는 통과, 2.5x는 제외 (AC-5.3)."""
        _make_stock(db, "131313", "폴백통과")
        _make_stock(db, "141414", "폴백제외")
        cfg = _cfg(vb_overrides={"enabled": True, "relative_threshold_enabled": True,
                                 "volume_ratio_threshold": 3.0})
        hist_pass = _hist(3500.0, 1000.0, jitter=None)   # std=0 → z None, flat 3.5>=3 통과
        hist_fail = _hist(2500.0, 1000.0, jitter=None)   # std=0 → z None, flat 2.5<3 제외

        def _fake_hist(code, pages=3):
            return hist_pass if code == "131313" else hist_fail

        with patch("app.services.naver_finance.fetch_volume_leaders_sync",
                   return_value=["131313", "141414"]), \
             patch("app.services.naver_finance.fetch_stock_price_history_sync", side_effect=_fake_hist):
            results = detect_volume_breakout(db, cfg)
        codes = {r.stock_code for r in results}
        assert "131313" in codes, "cold-start 3.5x → flat 폴백 통과"
        assert "141414" not in codes, "cold-start 2.5x → flat 폴백 제외"

    def test_catalyst_universe_expansion(self, db):
        """거래량 순위 밖 촉매(공시) 종목이 유니버스에 합류 (AC-5.1)."""
        stock = _make_stock(db, "151515", "촉매중대형주")
        _make_disclosure(db, stock.id, report_name="단일판매ㆍ공급계약체결")
        cfg = _cfg(vb_overrides={"enabled": True, "relative_threshold_enabled": True,
                                 "volume_ratio_threshold": 3.0})
        hist = _hist(4000.0, 1000.0, jitter=10.0)  # flat 4x 통과
        with patch("app.services.naver_finance.fetch_volume_leaders_sync", return_value=[]), \
             patch("app.services.naver_finance.fetch_stock_price_history_sync", return_value=hist):
            results = detect_volume_breakout(db, cfg)
        assert any(r.stock_code == "151515" for r in results), "촉매 종목 유니버스 합류 → 평가됨"

    def test_ownership_boundary_unchanged(self):
        """AI-062 가중치 / AI-063 bypass 임계 불변 확인 (AC-5.4)."""
        cfg = get_surge_config()
        assert cfg.volume_breakout.volume_breakout_bypass_threshold == 0.30
        assert cfg.ensemble.weights.volume_breakout == 0.11


# ===========================================================================
# AC-7 / REQ-007: 이벤트 구동 재스캔
# ===========================================================================

@pytest.fixture()
def reset_event_state():
    import app.services.scheduler as sched
    sched._reset_event_rescan_state()
    yield
    sched._reset_event_rescan_state()


class TestEventRescan:
    def test_high_article_triggers(self, db, reset_event_state):
        """HIGH 촉매 기사 저장 → 즉시 트리거 (AC-7.1)."""
        import app.services.scheduler as sched
        stock = _make_stock(db, "112040", "위메이드")
        _make_news(db, stock.id, title="위메이드 경영권 인수 M&A 확정", sentiment="positive", hours_ago=0.5)
        cfg = _cfg(catalyst_overrides={"enabled": True, "event_rescan_enabled": True})
        with patch("app.services.scheduler._run_event_surge_generation", return_value=3) as mock_gen:
            triggered = sched._maybe_trigger_event_rescan(db, cfg)
        assert triggered is True
        mock_gen.assert_called_once()

    def test_cooldown_blocks_retrigger(self, db, reset_event_state):
        """쿨다운 내 재트리거 차단 (AC-7.2)."""
        import app.services.scheduler as sched
        stock = _make_stock(db, "161616", "쿨다운종목")
        _make_news(db, stock.id, title="경영권 인수 확정", sentiment="positive", hours_ago=0.5)
        cfg = _cfg(catalyst_overrides={"enabled": True, "event_rescan_enabled": True,
                                       "event_rescan_cooldown_minutes": 30})
        with patch("app.services.scheduler._run_event_surge_generation", return_value=1) as mock_gen:
            first = sched._maybe_trigger_event_rescan(db, cfg)
            second = sched._maybe_trigger_event_rescan(db, cfg)
        assert first is True
        assert second is False, "쿨다운 내 재트리거 차단"
        assert mock_gen.call_count == 1

    def test_daily_cap_skips(self, db, reset_event_state):
        """일일 상한 초과 시 스킵 (AC-7.3)."""
        import app.services.scheduler as sched
        stock = _make_stock(db, "171717", "상한종목")
        _make_news(db, stock.id, title="합병 인수 확정", sentiment="positive", hours_ago=0.5)
        cfg = _cfg(catalyst_overrides={"enabled": True, "event_rescan_enabled": True,
                                       "max_daily_event_triggers": 20})
        # 당일 카운터를 상한으로 설정
        sched._event_rescan_state["date"] = datetime.now(timezone.utc).date()
        sched._event_rescan_state["count"] = 20
        with patch("app.services.scheduler._run_event_surge_generation", return_value=1) as mock_gen:
            triggered = sched._maybe_trigger_event_rescan(db, cfg)
        assert triggered is False, "일일 상한 도달 → 스킵"
        mock_gen.assert_not_called()

    def test_disabled_no_trigger(self, db, reset_event_state):
        """event_rescan_enabled=false → 트리거 없음 (AC-7.5, 레거시)."""
        import app.services.scheduler as sched
        stock = _make_stock(db, "181818", "비활성종목")
        _make_news(db, stock.id, title="경영권 인수 확정", sentiment="positive", hours_ago=0.5)
        cfg = _cfg(catalyst_overrides={"enabled": True, "event_rescan_enabled": False})
        with patch("app.services.scheduler._run_event_surge_generation", return_value=1) as mock_gen:
            triggered = sched._maybe_trigger_event_rescan(db, cfg)
        assert triggered is False
        mock_gen.assert_not_called()

    def test_no_qualifying_article_no_trigger(self, db, reset_event_state):
        """키워드/감성 미충족 기사 → 트리거 없음."""
        import app.services.scheduler as sched
        stock = _make_stock(db, "191919", "일반뉴스종목")
        _make_news(db, stock.id, title="일반 실적 발표", sentiment="neutral", hours_ago=0.5)
        cfg = _cfg(catalyst_overrides={"enabled": True, "event_rescan_enabled": True})
        with patch("app.services.scheduler._run_event_surge_generation", return_value=1) as mock_gen:
            triggered = sched._maybe_trigger_event_rescan(db, cfg)
        assert triggered is False
        mock_gen.assert_not_called()

    def test_periodic_scan_untouched(self):
        """정기 스캔 잡 래퍼가 그대로 존재 — 제거/대체 없음 (AC-7.4)."""
        import app.services.scheduler as sched
        assert hasattr(sched, "_run_surge_signal_generate")
        assert callable(sched._run_surge_signal_generate)

    def test_no_streaming_infra(self):
        """이벤트 경로는 인메모리 상태만 사용 — 스트리밍 인프라 미도입 (AC-7.6)."""
        import app.services.scheduler as sched
        assert isinstance(sched._event_rescan_state, dict)


# ===========================================================================
# 통합 회귀: 위메이드형 시나리오 (M6)
# ===========================================================================

class TestWemadeRegression:
    """2026-07-01 실제 프로덕션 미스(위메이드 112040)가 고쳐졌음을 증명하는 회귀 테스트."""

    def _setup_wemade(self, db):
        stock = _make_stock(db, "112040", "위메이드")
        # 15+ 다출처 기사, 인수/경영권 키워드, positive 감성, 16h span
        for i in range(15):
            _make_news(
                db, stock.id,
                title=f"위메이드 경영권 매각 인수 M&A 보도 {i}",
                sentiment="positive", hours_ago=1.0 + i,
            )
        # 최대주주변경 + 흡수합병결정 (인수 맥락) 공시
        _make_disclosure(db, stock.id, report_name="최대주주변경 흡수합병결정")
        return stock

    def test_a_conviction_high(self, db):
        """(a) 확신도 tier가 HIGH로 산출된다."""
        ev = ConvictionEvidence(
            article_count=15, coverage_hours=16.0, sentiment_score=0.7,
            has_high_impact_keyword=True, has_backing_disclosure=True,
        )
        assert compute_catalyst_conviction(ev, get_surge_config()) == CONVICTION_HIGH

    def test_b_passes_combo_overheat_gate(self, db):
        """(b) 과거 5% 컷오프에서 제외되던 종목이 이제 combo 과열 게이트를 통과한다."""
        self._setup_wemade(db)
        cfg = _cfg(
            catalyst_overrides={"enabled": True},
            guard_overrides={"enabled": True, "overheat_change_pct": 5.0,
                             "overheat_change_pct_high_conviction": 15.0,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_FRESH), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results_new = detect_volume_surge_news_combo(db, cfg)
        assert any(r.stock_code == "112040" for r in results_new), \
            "HIGH 확신도 → 12%가 과열 게이트 통과 (선행 신호 복구)"

    def test_b_control_old_behavior_excludes(self, db):
        """(b-대조) enabled=false(레거시)에서는 동일 종목이 5% 컷오프로 제외된다."""
        self._setup_wemade(db)
        cfg = _cfg(
            catalyst_overrides={"enabled": False},
            guard_overrides={"enabled": True, "overheat_change_pct": 5.0,
                             "overheat_change_pct_high_conviction": 15.0,
                             "exclude_on_price_unavailable": False},
        )
        with patch("app.services.surge_detector._get_volume_history", return_value=_VOL_FRESH), \
             patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results_old = detect_volume_surge_news_combo(db, cfg)
        assert not any(r.stock_code == "112040" for r in results_old), \
            "레거시(enabled=false) → 5% 컷오프로 제외 (과거 미스 재현)"

    def test_c_disclosure_penalty_mitigated(self, db):
        """(c) 인수 공시 페널티가 0.3이 아니라 0.7로 부분완화된다."""
        self._setup_wemade(db)
        cfg = _cfg(catalyst_overrides={"enabled": True},
                   disc_overrides={"acquisition_exemption_enabled": True,
                                   "penalty_factor": 0.3, "acquisition_penalty_factor": 0.7})
        with patch("app.services.surge_detector._fetch_price_change_sync",
                   return_value={"current_price": 10000, "change_rate": 12.0}):
            results = detect_immediate_disclosure_signal(db, cfg)
        cand = next(r for r in results if r.stock_code == "112040")
        # 흡수합병결정 base=0.82: 완화 후 0.574 (= 0.82×0.7), 페널티 유지 시 0.246 (= 0.82×0.3)
        assert cand.immediate_disclosure_score == pytest.approx(0.82 * 0.7, abs=1e-3), \
            "인수 호재 → 페널티 0.7 부분완화 (0.3 아님)"
        assert cand.immediate_disclosure_score > 0.82 * 0.3, "완화 후 점수가 페널티 유지보다 높음"
        assert cand.disclosure_sentiment == "bullish", "인수 호재 → bearish 아님"
