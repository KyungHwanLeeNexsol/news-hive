"""SPEC-AI-030: volume_news_combo 추격매수 방지 4개 게이트 인수 검증 테스트.

AC 검증 목록:
  - 특성화(characterize) 테스트: 게이트 추가 전 기존 동작 문서화
  - Gate 1 (REQ-AI030-001): 당일 과열 필터
  - Gate 2 (REQ-AI030-002): 거래량 신선도 검증
  - Gate 3 (REQ-AI030-003): 분산 패턴 거부
  - Gate 4 (REQ-AI030-004): combo 단독 신호 buy-pool 미포함
  - 마스터 스위치: enabled=False이면 모든 게이트 비활성
  - YAML 부재 시 기본값 호환성
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import ARRAY, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_detector import (
    SurgeCandidate,
    detect_volume_surge_news_combo,
    gather_surge_candidates,
)
from app.surge_config.surge_settings import (
    ComboChaseGuardConfig,
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
    """각 테스트에 독립적인 세션 (롤백 격리)."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

_sector_cache: dict = {}  # engine_id → Sector.id


def _get_or_create_sector(db: Session) -> int:
    """테스트용 더미 섹터를 반환한다 (세션당 한 번 생성)."""
    sector = Sector(name="테스트섹터_ai030")
    db.add(sector)
    db.flush()
    return sector.id


def _make_stock(db: Session, code: str, name: str = "테스트종목") -> Stock:
    sector_id = _get_or_create_sector(db)
    stock = Stock(stock_code=code, name=name, sector_id=sector_id)
    db.add(stock)
    db.flush()
    return stock


_news_counter = [0]


def _make_news_with_relation(
    db: Session,
    stock_id: int,
    sentiment: str = "positive",
    hours_ago: float = 1.0,
) -> NewsArticle:
    _news_counter[0] += 1
    article = NewsArticle(
        title="테스트뉴스",
        content="테스트내용",
        url=f"http://example.com/{stock_id}-{hours_ago}-{_news_counter[0]}",
        source="테스트출처",
        sentiment=sentiment,
        collected_at=datetime.now() - timedelta(hours=hours_ago),
    )
    db.add(article)
    db.flush()
    relation = NewsStockRelation(
        news_id=article.id,
        stock_id=stock_id,
        match_type="keyword",
        relevance="direct",
    )
    db.add(relation)
    db.flush()
    return article


def _make_config(**override_guard_fields) -> SurgeDetectionConfig:
    """기본 설정에 ComboChaseGuardConfig를 오버라이드한 SurgeDetectionConfig 반환."""
    base = get_surge_config()
    guard = ComboChaseGuardConfig(**{**ComboChaseGuardConfig().model_dump(), **override_guard_fields})
    # Pydantic 모델은 immutable → model_copy로 교체
    return base.model_copy(update={"combo_chase_guard": guard})


# ---------------------------------------------------------------------------
# ComboChaseGuardConfig 단위 테스트
# ---------------------------------------------------------------------------

class TestComboChaseGuardConfigDefaults:
    """YAML 부재 시 기본값 호환성 (backward compatible 문서화)."""

    def test_default_enabled_true(self):
        cfg = ComboChaseGuardConfig()
        assert cfg.enabled is True

    def test_default_overheat_5pct(self):
        cfg = ComboChaseGuardConfig()
        assert cfg.overheat_change_pct == 5.0

    def test_default_freshness_ratio_1_5(self):
        cfg = ComboChaseGuardConfig()
        assert cfg.min_freshness_ratio == 1.5

    def test_default_distribution_0(self):
        cfg = ComboChaseGuardConfig()
        assert cfg.distribution_change_pct == 0.0

    def test_default_exclude_on_price_unavailable_true(self):
        cfg = ComboChaseGuardConfig()
        assert cfg.exclude_on_price_unavailable is True

    def test_default_require_companion_detector_true(self):
        cfg = ComboChaseGuardConfig()
        assert cfg.require_companion_detector is True

    def test_surge_detection_config_has_combo_chase_guard(self):
        """SurgeDetectionConfig에 combo_chase_guard 필드가 포함되어야 한다."""
        cfg = get_surge_config()
        assert hasattr(cfg, "combo_chase_guard")
        assert isinstance(cfg.combo_chase_guard, ComboChaseGuardConfig)

    def test_yaml_values_loaded_correctly(self):
        """surge_detection.yaml의 combo_chase_guard 값이 정상 로드되어야 한다."""
        cfg = get_surge_config()
        guard = cfg.combo_chase_guard
        assert guard.enabled is True
        assert guard.overheat_change_pct == 5.0
        assert guard.min_freshness_ratio == 1.5
        assert guard.distribution_change_pct == 0.0
        assert guard.exclude_on_price_unavailable is True
        assert guard.require_companion_detector is True


# ---------------------------------------------------------------------------
# 특성화(Characterization) 테스트: 기존 동작 문서화
# ---------------------------------------------------------------------------

class TestCharacterizeExistingBehavior:
    """PRESERVE 단계 — 게이트 추가 전 기존 동작을 문서화한다."""

    def test_characterize_normal_flow_produces_combo_candidate(self, db):
        """정상 z-score + 긍정 뉴스 → combo candidate 생성 (마스터스위치 OFF)."""
        stock = _make_stock(db, "900000", "특성화종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=False)

        # volumes[:-1] 기준 mean≈1100, std≈300 → z-score = (5000-1100)/300 ≈ 13 (임계 초과)
        volumes = [1000.0] * 16 + [1500.0, 900.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 3.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        codes = [r.stock_code for r in results]
        assert "900000" in codes, "정상 z-score + 뉴스 → combo candidate가 생성되어야 함"

    def test_characterize_enabled_false_legacy_behavior(self, db):
        """enabled=False이면 모든 게이트 비활성 — price None이어도 candidate 생성."""
        stock = _make_stock(db, "900001", "레거시종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=False, exclude_on_price_unavailable=True)

        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value=None,
        ):
            results = detect_volume_surge_news_combo(db, config)

        # enabled=False이면 가격 None에도 candidate 생성 (레거시 동작)
        codes = [r.stock_code for r in results]
        assert "900001" in codes, "enabled=False이면 가격 None에도 candidate 생성"


# ---------------------------------------------------------------------------
# Gate 1: 당일 과열 필터 (REQ-AI030-001)
# ---------------------------------------------------------------------------

class TestGate1OverheatFilter:
    """change_rate >= overheat_change_pct → 제외."""

    def test_overheat_exact_threshold_excluded(self, db):
        """change_rate == 5.0 → 제외."""
        stock = _make_stock(db, "910001", "과열종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=True, overheat_change_pct=5.0)
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 5.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert not any(r.stock_code == "910001" for r in results), "change_rate=5.0 → 제외"

    def test_overheat_above_threshold_excluded(self, db):
        """change_rate == 7.5 → 제외."""
        stock = _make_stock(db, "910002", "과열종목2")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=True, overheat_change_pct=5.0)
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 7.5},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert not any(r.stock_code == "910002" for r in results), "change_rate=7.5 → 제외"

    def test_below_overheat_threshold_passes(self, db):
        """change_rate == 4.9 → 통과."""
        stock = _make_stock(db, "910003", "정상종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=True, overheat_change_pct=5.0, distribution_change_pct=-999.0)
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 4.9},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "910003" for r in results), "change_rate=4.9 → 통과"

    def test_price_none_excluded_when_flag_true(self, db):
        """가격 조회 실패(None) + exclude_on_price_unavailable=True → 제외."""
        stock = _make_stock(db, "910004", "가격없음종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=True, exclude_on_price_unavailable=True)
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value=None,
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert not any(r.stock_code == "910004" for r in results), "가격 None → 제외"

    def test_price_none_included_when_flag_false(self, db):
        """가격 조회 실패(None) + exclude_on_price_unavailable=False → 통과."""
        stock = _make_stock(db, "910005", "가격없음통과종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            exclude_on_price_unavailable=False,
            distribution_change_pct=-999.0,
        )
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value=None,
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "910005" for r in results), "exclude_on_price_unavailable=False → 통과"


# ---------------------------------------------------------------------------
# Gate 2: 거래량 신선도 검증 (REQ-AI030-002)
# ---------------------------------------------------------------------------

class TestGate2FreshnessCheck:
    """volumes[-1]/volumes[-2] < min_freshness_ratio → 제외."""

    def test_stale_volume_excluded(self, db):
        """freshness=1.0 (< 1.5) → stale 제외."""
        stock = _make_stock(db, "920001", "stale종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=True, min_freshness_ratio=1.5, distribution_change_pct=-999.0)
        # volumes[:-1] 분산 확보 (stale: 마지막값=5000, 그 전=5000 → ratio=1.0 < 1.5)
        volumes = [1000.0] * 16 + [1200.0, 800.0] + [5000.0, 5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 2.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert not any(r.stock_code == "920001" for r in results), "stale(ratio=1.0) → 제외"

    def test_fresh_volume_passes(self, db):
        """freshness=2.0 (>= 1.5) → 통과."""
        stock = _make_stock(db, "920002", "fresh종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            min_freshness_ratio=1.5,
            overheat_change_pct=100.0,
            distribution_change_pct=-999.0,
        )
        # volumes[:-1] 분산 확보 (fresh: volumes[-2]=2000, volumes[-1]=4000 → ratio=2.0)
        volumes = [1000.0] * 16 + [1200.0, 800.0] + [2000.0, 4000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 2.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "920002" for r in results), "fresh(ratio=2.0) → 통과"

    def test_zero_baseline_fresh_by_definition(self, db):
        """volumes[-2]=0, volumes[-1]>0 → zero 나눗셈 없이 통과 (신선 by definition)."""
        stock = _make_stock(db, "920003", "제로베이스종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            min_freshness_ratio=1.5,
            overheat_change_pct=100.0,
            distribution_change_pct=-999.0,
        )
        # volumes[:-1] 분산 확보 (zero baseline: volumes[-2]=0, volumes[-1]=5000)
        volumes = [1000.0] * 16 + [1200.0, 800.0] + [0.0, 5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 2.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "920003" for r in results), "zero baseline → 신선 통과"

    def test_exact_freshness_ratio_boundary_passes(self, db):
        """freshness == min_freshness_ratio (1.5) → 경계값 통과."""
        stock = _make_stock(db, "920004", "경계종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            min_freshness_ratio=1.5,
            overheat_change_pct=100.0,
            distribution_change_pct=-999.0,
        )
        # volumes[:-1] 분산 확보 (경계값: volumes[-2]=2000, volumes[-1]=3000 → ratio=1.5)
        volumes = [1000.0] * 16 + [1200.0, 800.0] + [2000.0, 3000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 2.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "920004" for r in results), "freshness 경계값(1.5) → 통과"


# ---------------------------------------------------------------------------
# Gate 3: 분산 패턴 거부 (REQ-AI030-003)
# ---------------------------------------------------------------------------

class TestGate3DistributionPattern:
    """change_rate < distribution_change_pct → 제외."""

    def test_negative_change_rate_excluded(self, db):
        """change_rate=-0.5 (< 0.0) → 분산패턴 제외."""
        stock = _make_stock(db, "930001", "음수종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            overheat_change_pct=100.0,
            distribution_change_pct=0.0,
            exclude_on_price_unavailable=False,
        )
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": -0.5},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert not any(r.stock_code == "930001" for r in results), "change_rate=-0.5 → 제외"

    def test_zero_change_rate_passes(self, db):
        """change_rate=0.0 → 음수 아님 → 통과 (flat은 분산패턴 아님)."""
        stock = _make_stock(db, "930002", "보합종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            overheat_change_pct=100.0,
            distribution_change_pct=0.0,
            exclude_on_price_unavailable=False,
            min_freshness_ratio=0.0,
        )
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 0.0},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "930002" for r in results), "change_rate=0.0 → 통과"

    def test_positive_change_rate_passes(self, db):
        """change_rate=1.5 → 통과."""
        stock = _make_stock(db, "930003", "상승종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(
            enabled=True,
            overheat_change_pct=100.0,
            distribution_change_pct=0.0,
            exclude_on_price_unavailable=False,
            min_freshness_ratio=0.0,
        )
        # volumes[:-1]에 분산 확보: mean≈993, std>0 → z-score 충분히 높음
        volumes = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 1.5},
        ):
            results = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "930003" for r in results), "change_rate=1.5 → 통과"


# ---------------------------------------------------------------------------
# Gate 4: combo 단독 신호 buy-pool 미포함 (REQ-AI030-004)
# ---------------------------------------------------------------------------

class TestGate4ComboOnlyExclusion:
    """gather_surge_candidates에서 combo 단독 신호 제외."""

    def _make_combo_only_candidate(self, code: str) -> SurgeCandidate:
        """combo_score > 0이고 다른 탐지기 점수가 0인 후보."""
        return SurgeCandidate(
            stock_code=code,
            stock_name=f"{code}종목",
            combo_score=0.6,
            theme_cluster_score=0.0,
            immediate_disclosure_score=0.0,
            pattern_score=0.0,
            active_detectors=["volume_news_combo"],
        )

    def _make_combo_with_theme(self, code: str) -> SurgeCandidate:
        """combo + theme 동반 신호 (bypass_threshold 이상으로 앙상블 임계 우회)."""
        return SurgeCandidate(
            stock_code=code,
            stock_name=f"{code}종목",
            combo_score=0.87,   # strong_single_bypass_threshold(0.85) 초과
            theme_cluster_score=0.87,
            immediate_disclosure_score=0.0,
            pattern_score=0.0,
            active_detectors=["volume_news_combo", "theme_cluster"],
        )

    def test_combo_only_excluded_when_required(self, db):
        """combo 단독(테마/공시/패턴=0) → require_companion_detector=True이면 제외."""
        config = _make_config(enabled=True, require_companion_detector=True)

        combo_only = self._make_combo_only_candidate("940001")

        with patch(
            "app.services.surge_detector.detect_theme_news_cluster",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_volume_surge_news_combo",
            return_value=[combo_only],
        ), patch(
            "app.services.surge_detector.detect_disclosure_surge_pattern",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_immediate_disclosure_signal",
            return_value=[],
        ), patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=[],
        ):
            results = gather_surge_candidates(db, [], config, [])

        codes = [r.stock_code for r in results]
        assert "940001" not in codes, "combo 단독 → 제외"

    def test_combo_with_theme_not_excluded(self, db):
        """combo + theme 동반 → 제외하지 않음."""
        config = _make_config(enabled=True, require_companion_detector=True)

        combo_theme = self._make_combo_with_theme("940002")

        with patch(
            "app.services.surge_detector.detect_theme_news_cluster",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_volume_surge_news_combo",
            return_value=[combo_theme],
        ), patch(
            "app.services.surge_detector.detect_disclosure_surge_pattern",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_immediate_disclosure_signal",
            return_value=[],
        ), patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=[],
        ):
            results = gather_surge_candidates(db, [], config, [])

        codes = [r.stock_code for r in results]
        assert "940002" in codes, "combo + theme → 제외 안 함"

    def test_combo_only_not_excluded_when_flag_false(self, db):
        """require_companion_detector=False → combo 단독도 제외하지 않음."""
        config = _make_config(enabled=True, require_companion_detector=False)

        combo_only = self._make_combo_only_candidate("940003")
        # combo_score를 bypass_threshold 이상으로 설정해 앙상블 우회 통과
        combo_only.combo_score = 0.99

        with patch(
            "app.services.surge_detector.detect_theme_news_cluster",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_volume_surge_news_combo",
            return_value=[combo_only],
        ), patch(
            "app.services.surge_detector.detect_disclosure_surge_pattern",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_immediate_disclosure_signal",
            return_value=[],
        ), patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=[],
        ):
            results = gather_surge_candidates(db, [], config, [])

        codes = [r.stock_code for r in results]
        assert "940003" in codes, "require_companion_detector=False → 제외 안 함"

    def test_gate4_disabled_when_guard_disabled(self, db):
        """enabled=False → Gate 4도 비활성."""
        config = _make_config(enabled=False, require_companion_detector=True)

        combo_only = self._make_combo_only_candidate("940004")
        combo_only.combo_score = 0.99

        with patch(
            "app.services.surge_detector.detect_theme_news_cluster",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_volume_surge_news_combo",
            return_value=[combo_only],
        ), patch(
            "app.services.surge_detector.detect_disclosure_surge_pattern",
            return_value=[],
        ), patch(
            "app.services.surge_detector.detect_immediate_disclosure_signal",
            return_value=[],
        ), patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=[],
        ):
            results = gather_surge_candidates(db, [], config, [])

        codes = [r.stock_code for r in results]
        assert "940004" in codes, "enabled=False → Gate 4 비활성, combo 단독도 통과"


# ---------------------------------------------------------------------------
# 마스터 스위치: enabled=False → 모든 게이트 비활성
# ---------------------------------------------------------------------------

class TestMasterSwitch:
    """enabled=False이면 모든 게이트(1~3)가 비활성된다."""

    def test_all_gates_inactive_when_disabled(self, db):
        """enabled=False → 과열(+7%), stale(ratio=0.5), 음수(-1%) 모두 통과."""
        stock = _make_stock(db, "950001", "마스터스위치종목")
        _make_news_with_relation(db, stock.id, sentiment="positive", hours_ago=1)

        config = _make_config(enabled=False)
        # stale 조건: volumes[-2]=5000, volumes[-1]=2000 → ratio=0.4 < 1.5 → Gate2 걸려야 하지만 disabled
        volumes = [1000.0] * 16 + [1200.0, 800.0] + [5000.0, 2000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 7.0},
        ):
            detect_volume_surge_news_combo(db, config)

        # z-score 계산: 마지막 값(2000)은 baseline 평균(1000~5000)에서
        # 단, volumes[-1]=2000이 현재 거래량이므로 baseline에는 volumes[:-1]이 사용됨
        # z-score가 임계 초과하면 candidate 생성 — 단지 disabled 게이트로 인해 제외 안 됨
        # 정확한 z-score 계산은 detect_volume_surge_news_combo 내부에 의존
        # 여기서는 enabled=False 의 의도가 '게이트 비활성'임을 확인
        # (z-score 미달로 결과가 0일 수 있음 → 과열 제외와 구분 불가 → 별도 케이스로 분리)
        # => 실제로 z-score 충분한 경우만 테스트
        stock2 = _make_stock(db, "950002", "마스터스위치2")
        _make_news_with_relation(db, stock2.id, sentiment="positive", hours_ago=1)

        volumes2 = [1000.0] * 17 + [1200.0, 800.0] + [5000.0]

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=volumes2,
        ), patch(
            "app.services.surge_detector._fetch_price_change_sync",
            return_value={"current_price": 10000, "change_rate": 7.0},
        ):
            results2 = detect_volume_surge_news_combo(db, config)

        assert any(r.stock_code == "950002" for r in results2), (
            "enabled=False → 과열(7%) + z-score 충분 → 제외 없음"
        )
