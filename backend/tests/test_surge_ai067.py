"""SPEC-AI-067: 장중 당일 거래량 실시간성 개선 인수 검증 테스트.

AC 검증 목록:
  - AC-1 (REQ-001): 실시간 당일 거래량 소스 (공유 메커니즘) — 장중 취득/장외 미호출/당일 원소만 교체
  - AC-2 (REQ-002): combo 탐지기 z-score 부호 교정 (위메이드형 stale 64,418 → 실시간 258,945)
  - AC-3/4 (REQ-003/004): breakout/Pool B today_vol 교정 (헬퍼 재사용으로 공통 검증)
  - AC-5 (REQ-005): fail-open 폴백 · 예산 상한 · 단조 비감소(max) 채택
  - AC-6 (REQ-006): 과거 베이스라인 무결성 (모바일 교체 대상 아님)
  - AC-7 (REQ-007): 설정 기본값 · enabled=false 레거시 동등
  - AC-8 (REQ-008): _PriceHistoryCache 장중 인지형 TTL

모바일 API는 전부 mock/주입 (실네트워크 금지). 결정 로직만 검증한다.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import ARRAY, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.services.surge_detector as sd
from app.database import Base
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_detector import (
    _reset_live_volume_budget,
    _resolve_today_volume,
    detect_volume_surge_news_combo,
)
from app.surge_config.surge_settings import (
    ComboChaseGuardConfig,
    IntradayLiveVolumeConfig,
    SurgeDetectionConfig,
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


@pytest.fixture(autouse=True)
def _reset_live_volume_state():
    """각 테스트 전후로 SPEC-AI-067 모듈 전역 상태를 초기화한다."""
    _reset_live_volume_budget()
    sd._live_volume_provider = None
    yield
    _reset_live_volume_budget()
    sd._live_volume_provider = None


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_stock(db: Session, code: str, name: str = "테스트종목") -> Stock:
    sector = Sector(name=f"섹터_{code}")
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=name, sector_id=sector.id)
    db.add(stock)
    db.flush()
    return stock


_news_counter = [0]


def _make_news_with_relation(db: Session, stock_id: int, hours_ago: float = 1.0) -> None:
    _news_counter[0] += 1
    article = NewsArticle(
        title="인수 합병 호재",
        content="테스트내용",
        url=f"http://example.com/{stock_id}-{_news_counter[0]}",
        source="테스트출처",
        sentiment="positive",
        collected_at=datetime.now() - timedelta(hours=hours_ago),
    )
    db.add(article)
    db.flush()
    db.add(NewsStockRelation(
        news_id=article.id,
        stock_id=stock_id,
        match_type="keyword",
        relevance="direct",
    ))
    db.flush()


def _ilv_config(
    enabled: bool = True,
    market_hours_only: bool = True,
    max_live_fetches_per_scan: int = 80,
) -> SurgeDetectionConfig:
    """intraday_live_volume 섹션만 오버라이드한 SurgeDetectionConfig."""
    base = get_surge_config()
    ilv = IntradayLiveVolumeConfig(
        enabled=enabled,
        market_hours_only=market_hours_only,
        max_live_fetches_per_scan=max_live_fetches_per_scan,
    )
    return base.model_copy(update={"intraday_live_volume": ilv})


def _combo_config(intraday_enabled: bool = True) -> SurgeDetectionConfig:
    """combo 부호 교정 테스트용: 게이트 비활성(z-score 격리) + combo 탐지기 활성 + intraday 설정."""
    base = get_surge_config()
    guard = ComboChaseGuardConfig(
        **{**ComboChaseGuardConfig().model_dump(), "enabled": False}
    )
    vnc = base.volume_news_combo.model_copy(update={"enabled": True})
    ilv = IntradayLiveVolumeConfig(
        enabled=intraday_enabled, market_hours_only=True, max_live_fetches_per_scan=80
    )
    return base.model_copy(update={
        "combo_chase_guard": guard,
        "volume_news_combo": vnc,
        "intraday_live_volume": ilv,
    })


# ---------------------------------------------------------------------------
# AC-7: 설정 및 하위 호환
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    """AC-7.1: 설정 부재 시 문서화된 기본값."""

    def test_default_enabled_true(self):
        cfg = IntradayLiveVolumeConfig()
        assert cfg.enabled is True

    def test_default_market_hours_only_true(self):
        assert IntradayLiveVolumeConfig().market_hours_only is True

    def test_default_max_live_fetches_80(self):
        assert IntradayLiveVolumeConfig().max_live_fetches_per_scan == 80

    def test_surge_config_has_section(self):
        """get_surge_config()에 intraday_live_volume 섹션이 존재하고 기본값 로드."""
        cfg = get_surge_config()
        assert cfg.intraday_live_volume.enabled is True
        assert cfg.intraday_live_volume.max_live_fetches_per_scan == 80


# ---------------------------------------------------------------------------
# AC-1 / AC-5: 공유 헬퍼 _resolve_today_volume 결정 로직
# ---------------------------------------------------------------------------

class TestResolveTodayVolume:
    """공유 메커니즘 결정 로직 (장중/장외/fail-open/예산/단조)."""

    def test_market_open_uses_live(self):
        """AC-1.1: 장중 + 실시간 값 정상 → 실시간 값 채택 (sise_day 미사용)."""
        sd._live_volume_provider = lambda code: 258945
        config = _ilv_config()
        with patch("app.services.naver_finance._is_market_open", return_value=True):
            result = _resolve_today_volume("112040", 64418.0, config)
        assert result == 258945.0

    def test_market_closed_no_live_fetch(self):
        """AC-1.2: 장외 → 모바일 미호출, sise_day 값 반환."""
        calls = []
        sd._live_volume_provider = lambda code: calls.append(code) or 258945
        config = _ilv_config(market_hours_only=True)
        with patch("app.services.naver_finance._is_market_open", return_value=False):
            result = _resolve_today_volume("112040", 64418.0, config)
        assert result == 64418.0
        assert calls == [], "장외에는 provider가 호출되지 않아야 한다"

    def test_enabled_false_legacy(self):
        """AC-7.2: enabled=false → 항상 sise_day 값 (모바일 미호출)."""
        calls = []
        sd._live_volume_provider = lambda code: calls.append(code) or 999999
        config = _ilv_config(enabled=False)
        with patch("app.services.naver_finance._is_market_open", return_value=True):
            result = _resolve_today_volume("112040", 64418.0, config)
        assert result == 64418.0
        assert calls == []

    def test_fail_open_on_exception(self):
        """AC-5.1: 모바일 예외 → sise_day 폴백 (무예외)."""
        def _raise(code):
            raise RuntimeError("rate limit")

        sd._live_volume_provider = _raise
        config = _ilv_config(market_hours_only=False)
        result = _resolve_today_volume("112040", 64418.0, config)
        assert result == 64418.0

    def test_fail_open_on_none(self):
        """AC-5.1: 실시간 None → sise_day 폴백."""
        sd._live_volume_provider = lambda code: None
        config = _ilv_config(market_hours_only=False)
        assert _resolve_today_volume("112040", 64418.0, config) == 64418.0

    def test_fail_open_on_zero(self):
        """Edge: 실시간 0 → 무효 → sise_day 폴백."""
        sd._live_volume_provider = lambda code: 0
        config = _ilv_config(market_hours_only=False)
        assert _resolve_today_volume("112040", 64418.0, config) == 64418.0

    def test_monotonic_max_when_live_smaller(self):
        """AC-5.4: 실시간 값이 sise_day보다 작으면 큰 값(sise_day) 채택 (단조 비감소)."""
        sd._live_volume_provider = lambda code: 50000
        config = _ilv_config(market_hours_only=False)
        assert _resolve_today_volume("112040", 64418.0, config) == 64418.0

    def test_budget_exceeded_fallback(self):
        """AC-5.3: 스캔당 상한 초과 → 이후 후보는 sise_day 폴백 (provider 미호출)."""
        calls = []
        sd._live_volume_provider = lambda code: calls.append(code) or 999999
        config = _ilv_config(market_hours_only=False, max_live_fetches_per_scan=2)

        r1 = _resolve_today_volume("A", 100.0, config)
        r2 = _resolve_today_volume("B", 100.0, config)
        r3 = _resolve_today_volume("C", 100.0, config)
        r4 = _resolve_today_volume("D", 100.0, config)

        assert r1 == 999999.0 and r2 == 999999.0
        assert r3 == 100.0 and r4 == 100.0, "상한 초과 후 sise_day 폴백"
        assert calls == ["A", "B"], "상한 내 2회만 provider 호출"

    def test_budget_reset(self):
        """예산 카운터가 스캔 경계에서 리셋됨."""
        sd._live_volume_provider = lambda code: 999999
        config = _ilv_config(market_hours_only=False, max_live_fetches_per_scan=1)

        assert _resolve_today_volume("A", 100.0, config) == 999999.0
        assert _resolve_today_volume("B", 100.0, config) == 100.0  # 상한 도달
        _reset_live_volume_budget()
        assert _resolve_today_volume("C", 100.0, config) == 999999.0  # 리셋 후 재취득


# ---------------------------------------------------------------------------
# AC-2 / AC-6: combo 탐지기 z-score 부호 교정 + 베이스라인 무결성
# ---------------------------------------------------------------------------

class TestComboZScoreSignFlip:
    """위메이드형 stale 당일 거래량이 z-score 부호를 뒤집는 버그의 교정 검증."""

    # baseline 19개: 평균 ≈182,368, std>0 (위메이드 20일 평균 182,449 근사)
    _BASELINE = [180000.0, 185000.0] * 9 + [180000.0]  # 19개
    _STALE_TODAY = 64418.0     # sise_day 지연 값 (음의 z-score 유발)
    _LIVE_TODAY = 258945.0     # 모바일 실시간 값 (양의 z-score)

    def test_live_value_produces_candidate(self, db):
        """AC-2.1: 장중 실시간 값(258,945) 사용 → 양의 z-score → combo candidate 생성."""
        stock = _make_stock(db, "112040", "위메이드")
        _make_news_with_relation(db, stock.id)
        sd._live_volume_provider = lambda code: int(self._LIVE_TODAY)
        volumes = list(self._BASELINE) + [self._STALE_TODAY]
        config = _combo_config(intraday_enabled=True)

        with patch(
            "app.services.surge_detector._get_volume_history", return_value=volumes
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 3.0},
        ), patch("app.services.naver_finance._is_market_open", return_value=True):
            results = detect_volume_surge_news_combo(db, config)

        assert "112040" in [r.stock_code for r in results], (
            "실시간 값으로 z-score가 양(+)이 되어 combo candidate가 생성되어야 함"
        )

    def test_stale_value_excludes_candidate(self, db):
        """대조: intraday off(레거시)이면 stale 64,418로 음의 z-score → 미탐지."""
        stock = _make_stock(db, "112041", "위메이드레거시")
        _make_news_with_relation(db, stock.id)
        sd._live_volume_provider = lambda code: int(self._LIVE_TODAY)
        volumes = list(self._BASELINE) + [self._STALE_TODAY]
        config = _combo_config(intraday_enabled=False)  # 레거시: sise_day stale 사용

        with patch(
            "app.services.surge_detector._get_volume_history", return_value=volumes
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 3.0},
        ), patch("app.services.naver_finance._is_market_open", return_value=True):
            results = detect_volume_surge_news_combo(db, config)

        assert "112041" not in [r.stock_code for r in results], (
            "레거시(stale) 경로는 음의 z-score로 미탐지되어야 함 (부호 오류 재현)"
        )

    def test_baseline_not_contaminated_by_live(self, db):
        """AC-6.1/AC-2.3: 베이스라인은 sise_day 그대로 — 실시간 값이 baseline을 오염시키지 않는다.

        baseline 전부 동일값(std=0)이면 combo가 스킵한다. 만약 실시간 값이 baseline에
        주입되면 std>0이 되어 스킵되지 않을 것이다. 스킵됨(=미탐지)을 확인해 무결성 증명.
        """
        stock = _make_stock(db, "112042", "베이스라인검증")
        _make_news_with_relation(db, stock.id)
        sd._live_volume_provider = lambda code: 999999  # baseline에 섞이면 std>0
        volumes = [1000.0] * 19 + [500.0]  # baseline 전부 1000 → std=0
        config = _combo_config(intraday_enabled=True)

        with patch(
            "app.services.surge_detector._get_volume_history", return_value=volumes
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 3.0},
        ), patch("app.services.naver_finance._is_market_open", return_value=True):
            results = detect_volume_surge_news_combo(db, config)

        assert "112042" not in [r.stock_code for r in results], (
            "baseline std=0으로 스킵되어야 함 — 실시간 값이 baseline을 오염시키지 않음을 증명"
        )


# ---------------------------------------------------------------------------
# naver_finance 공유 파싱 / 동기 헬퍼
# ---------------------------------------------------------------------------

class TestNaverHelpers:
    """_extract_accumulated_volume 순수 파싱 + fetch_live_today_volume_sync fail-open."""

    def test_extract_valid(self):
        from app.services.naver_finance import _extract_accumulated_volume
        assert _extract_accumulated_volume([{"accumulatedTradingVolume": "258,945"}]) == 258945

    def test_extract_int(self):
        from app.services.naver_finance import _extract_accumulated_volume
        assert _extract_accumulated_volume([{"accumulatedTradingVolume": 258945}]) == 258945

    def test_extract_empty_list(self):
        from app.services.naver_finance import _extract_accumulated_volume
        assert _extract_accumulated_volume([]) is None

    def test_extract_non_list(self):
        from app.services.naver_finance import _extract_accumulated_volume
        assert _extract_accumulated_volume({"x": 1}) is None

    def test_extract_missing_field(self):
        from app.services.naver_finance import _extract_accumulated_volume
        assert _extract_accumulated_volume([{"closePrice": "10000"}]) is None

    def test_sync_helper_returns_volume(self):
        """fetch_live_today_volume_sync가 모바일 응답에서 거래량을 추출한다 (httpx mock)."""
        import app.services.naver_finance as nf

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"accumulatedTradingVolume": "258945"}]

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, *a, **k):
                return _Resp()

        with patch.object(nf.httpx, "Client", lambda *a, **k: _Client()):
            assert nf.fetch_live_today_volume_sync("112040") == 258945

    def test_sync_helper_fail_open(self):
        """네트워크 예외 → None (호출부 fail-open)."""
        import app.services.naver_finance as nf

        def _raise(*a, **k):
            raise RuntimeError("network")

        with patch.object(nf.httpx, "Client", _raise):
            assert nf.fetch_live_today_volume_sync("112040") is None


# ---------------------------------------------------------------------------
# AC-8: _PriceHistoryCache 장중 인지형 TTL (REQ-008)
# ---------------------------------------------------------------------------

class TestPriceHistoryCacheTTL:
    """평면 3600 → _cache_ttl() 전환 검증 (장중 짧은 TTL / 장외 긴 TTL)."""

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        import app.services.naver_finance as nf
        nf._price_cache.data.pop("TTLTEST", None)
        nf._price_cache.last_updated.pop("TTLTEST", None)
        nf._price_cache.pages_fetched.pop("TTLTEST", None)
        yield
        nf._price_cache.data.pop("TTLTEST", None)
        nf._price_cache.last_updated.pop("TTLTEST", None)
        nf._price_cache.pages_fetched.pop("TTLTEST", None)

    def test_market_closed_uses_long_ttl(self):
        """AC-8.2: 장외 TTL(300초) — 30초 전 캐시는 fresh → 캐시 반환."""
        import app.services.naver_finance as nf

        rec = nf.PriceRecord(date="2026.07.01", close=1000, volume=5000)
        nf._price_cache.data["TTLTEST"] = [rec]
        nf._price_cache.last_updated["TTLTEST"] = time.time() - 30
        # SPEC-AI-097 REQ-003: pages 인지형 히트 판정 — 요청 pages(1) 이상으로 채워진
        # 상태여야 TTL 판정(AC-8.2 검증 대상)만으로 히트가 결정된다.
        nf._price_cache.pages_fetched["TTLTEST"] = 1

        with patch("app.services.naver_finance._is_market_open", return_value=False):
            result = nf.fetch_stock_price_history_sync("TTLTEST", pages=1)
        assert result == [rec], "장외(TTL=300)에서 30초 전 캐시는 fresh"

    def test_market_open_uses_short_ttl(self):
        """AC-8.1: 장중 TTL(10초) — 30초 전 캐시는 stale → 재fetch 시도(mock 실패로 빈 결과).

        평면 3600이었다면 두 경우 모두 캐시를 반환했을 것이므로, 이 대조가 전환을 증명한다.
        """
        import app.services.naver_finance as nf

        rec = nf.PriceRecord(date="2026.07.01", close=1000, volume=5000)
        nf._price_cache.data["TTLTEST"] = [rec]
        nf._price_cache.last_updated["TTLTEST"] = time.time() - 30

        def _raise(*a, **k):
            raise RuntimeError("no network in test")

        with patch("app.services.naver_finance._is_market_open", return_value=True), \
                patch.object(nf.httpx, "Client", _raise):
            result = nf.fetch_stock_price_history_sync("TTLTEST", pages=1)
        assert result == [], "장중(TTL=10)에서 30초 전 캐시는 stale → 재fetch (mock 실패로 빈 결과)"
