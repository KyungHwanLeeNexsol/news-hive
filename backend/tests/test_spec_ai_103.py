"""SPEC-AI-103: 테마 클러스터 뉴스 신선도/중복(dedup) 가드 — 검증 스위트.

구성:
  §M5  TestCharacterizationPreGuard — DDD PRESERVE 특성화 테스트.
       가드 도입 이전 `detect_theme_news_cluster()` 출력을 대표 픽스처로 캡처한다
       (REQ-AI103-006). 전부 기본 설정(가드 비활성)에서 실행되므로, 구현 이후에도
       영구적인 바이트 동등 회귀 스냅샷으로 계속 기능한다.
  §A   AC-AI103-001 ~ AC-AI103-007 검증.
  §B   acceptance.md §B Edge Cases + 하드 캡 성능 경계.

conftest.py 공유 픽스처(db)와 test_spec_ai_098.py의 실제 YAML 기반 surge_config
픽스처 관례를 재사용한다.

주의(테스트 데이터 설계): 기존 관례인 `f"...기사 {i}"` 형태의 연번 제목은 서로
difflib 유사도 0.93으로 **근접 중복 판정 임계(0.85)를 넘긴다**. 따라서 "서로 다른
고유 사건"을 표현해야 하는 픽스처에서는 의미가 다른 제목을 사용한다
(_DISTINCT_TITLES, 최대 쌍대 유사도 0.53).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.news import NewsArticle
from app.models.sector import Sector
from app.models.stock import Stock
from app.services import surge_detector as det_module
from app.services.naver_finance import PriceRecord
from app.surge_config.surge_settings import (
    SurgeDetectionConfig,
    ThemeFreshnessGuardConfig,
    get_surge_config,
)


# ---------------------------------------------------------------------------
# 픽스처 / 헬퍼
# ---------------------------------------------------------------------------

# 서로 명확히 다른 사건을 다루는 제목들 (쌍대 difflib 유사도 최대 0.53 < 임계 0.85).
_DISTINCT_TITLES = [
    "반도체 설비 투자 확대 전망",
    "반도체 수출 물량 감소 우려 확산",
    "반도체 소재 국산화 정책 발표",
    "반도체 인력 채용 규모 역대 최대",
    "반도체 장비 수주 잔고 급증",
    "반도체 공정 미세화 기술 경쟁 심화",
]


@pytest.fixture
def surge_config() -> SurgeDetectionConfig:
    """테스트마다 독립적인 config 사본 (실제 YAML 기준, 싱글턴 오염 방지)."""
    return get_surge_config().model_copy(deep=True)


@pytest.fixture
def sector_semiconductor(db: Session) -> Sector:
    s = Sector(name="반도체와반도체장비")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def make_theme_stock(db: Session, sector_semiconductor: Sector):
    """반도체 섹터 종목 팩토리 (시총 필터 통과, market_cap 단위: 억원)."""

    def _factory(name: str, stock_code: str, market_cap: int = 2000) -> Stock:
        stock = Stock(
            name=name, stock_code=stock_code, sector_id=sector_semiconductor.id,
            market_cap=market_cap,
        )
        db.add(stock)
        db.flush()
        return stock

    return _factory


@pytest.fixture
def make_theme_news(db: Session):
    """반도체 테마 뉴스 팩토리 (cluster_window_hours=48 이내)."""
    import os

    _is_sqlite = os.getenv("TEST_DATABASE_URL", "sqlite://").startswith("sqlite")
    _counter = [0]

    def _factory(title: str, content: str = "", hours_ago: float = 1.0) -> NewsArticle:
        _counter[0] += 1
        now = datetime.utcnow() if _is_sqlite else datetime.now(timezone.utc)
        published_at = now - timedelta(hours=hours_ago)
        article = NewsArticle(
            title=title, content=content,
            url=f"https://example.com/spec-ai-103/{_counter[0]}",
            source=f"매체{_counter[0]}", published_at=published_at,
            collected_at=published_at, sentiment="positive",
        )
        db.add(article)
        db.flush()
        return article

    return _factory


def _enabled_guard(**overrides) -> ThemeFreshnessGuardConfig:
    """가드 활성 설정 생성 헬퍼 (나머지 필드는 스키마 기본값)."""
    return ThemeFreshnessGuardConfig(enabled=True, **overrides)


def _run(db: Session, config: SurgeDetectionConfig):
    return det_module.detect_theme_news_cluster(db, [], config)


def _score_of(results, stock_code: str) -> float | None:
    c = next((r for r in results if r.stock_code == stock_code), None)
    return None if c is None else c.theme_cluster_score


# ===========================================================================
# §M5 — DDD PRESERVE: 가드 도입 이전 동작 특성화 (REQ-AI103-006)
# ===========================================================================


class TestCharacterizationPreGuard:
    """M5: 가드 도입 이전 `detect_theme_news_cluster()` 출력 스냅샷.

    전부 스키마 기본값(enabled=False)으로 실행된다 — 구현 이후에도 값이 변하면
    REQ-AI103-002 바이트 동등 계약 위반이다.
    """

    def test_char_001_guard_defaults_are_fully_inert(self, surge_config: SurgeDetectionConfig):
        """가드 기본값 스냅샷: 마스터 스위치 비활성 + 감쇠 임계 0.0(미발동)."""
        g = surge_config.theme_freshness_guard
        assert g.enabled is False
        assert g.min_theme_freshness_ratio == 0.0
        assert g.price_overheat_enabled is False
        assert g.dedup_max_comparison_batch == 200

    def test_char_002_sector_only_score_formula(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """섹터 전용 후보 점수 = min(1.0, cnt/10) * sector_only_penalty (cnt=raw 기사 수)."""
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t)

        results = _run(db, surge_config)

        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)

    def test_char_003_direct_mention_blend_formula(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """직접 언급 후보 점수 = (theme_base*0.6 + stock_article_score*0.4) * sentiment_factor."""
        make_theme_stock("에스케이하이닉스", "000660")
        for t in _DISTINCT_TITLES[:2]:
            make_theme_news(t)
        make_theme_news("SK하이닉스가 반도체 신규 라인을 증설한다", content="SK하이닉스 증설")

        results = _run(db, surge_config)

        theme_base = min(1.0, 3 / 10)          # 반도체 매칭 기사 3건 (raw)
        stock_article_score = min(1.0, 1 / 5)  # 종목 전용 기사 1건
        sentiment_factor = 0.8 + 0.4 * 0.7     # sentiment="positive" → 0.7
        expected = (theme_base * 0.6 + stock_article_score * 0.4) * sentiment_factor
        assert _score_of(results, "000660") == pytest.approx(expected)

    def test_char_004_near_duplicates_counted_individually(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """가드 이전에는 근접 중복(동일 제목 재보도)이 각각 개별 건으로 집계된다.

        고유 사건은 2건(재보도 1쌍 + 단독 1건)이지만 raw count는 3이다 — 이 값이
        곧 재보도 인플레이션의 스냅샷이다.
        """
        make_theme_stock("삼성전자", "005930")
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)  # 다른 매체 재보도
        make_theme_news(_DISTINCT_TITLES[1], hours_ago=1.5)

        results = _run(db, surge_config)

        # raw cnt=3 기준 점수 (중복 제거 시에는 cnt=2가 되어 0.10이 된다)
        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)

    def test_char_005_min_article_count_gate_uses_raw_count(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """고유 사건이 1건뿐이어도 재보도 2건이면 raw count=2로 테마가 활성화된다."""
        make_theme_stock("삼성전자", "005930")
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)

        results = _run(db, surge_config)

        assert _score_of(results, "005930") is not None

    def test_char_006_stale_articles_score_identically_to_fresh(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """가드 이전에는 기사 발행 시각(신선/진부)이 점수에 전혀 반영되지 않는다."""
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t, hours_ago=40.0)  # 창(48h) 안이지만 초반부

        results = _run(db, surge_config)

        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)

    def test_char_007_empty_news_window_returns_empty(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock,
    ):
        """뉴스 창이 비면 빈 후보 목록을 반환한다."""
        make_theme_stock("삼성전자", "005930")
        assert _run(db, surge_config) == []


# ===========================================================================
# §A — AC-AI103-001: 근접 중복 기사의 단일 집계
# ===========================================================================


class TestDedupNearDuplicateArticles:
    """AC-AI103-001: 근접 중복 기사를 단일 건으로 집계하고 가장 이른 기사를 대표로 쓴다."""

    def test_ac103_001_helper_collapses_duplicates_keeping_earliest(self, make_theme_news):
        """헬퍼 단위: 근접 중복 2건이 1건으로 축약되고 대표는 가장 이른 발행 기사다."""
        early = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=3.0)
        late = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        distinct = make_theme_news(_DISTINCT_TITLES[1], hours_ago=2.0)

        kept = det_module._dedup_near_duplicate_articles(
            [late, distinct, early], _enabled_guard()
        )

        assert len(kept) == 2
        kept_urls = {a.url for a in kept}
        assert early.url in kept_urls and late.url not in kept_urls
        assert distinct.url in kept_urls

    def test_ac103_001_similar_but_not_identical_title_is_deduped(self, make_theme_news):
        """제목이 완전히 같지 않아도 유사도 임계 이상이면 중복으로 판정된다."""
        a = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        b = make_theme_news("[속보] 반도체 업계 신규 투자 발표", hours_ago=1.0)  # 유사도 0.857

        assert len(det_module._dedup_near_duplicate_articles([a, b], _enabled_guard())) == 1

    def test_ac103_001_distinct_titles_are_not_deduped(self, make_theme_news):
        """의미가 다른 제목은 발행 시각이 근접해도 중복이 아니다."""
        arts = [make_theme_news(t, hours_ago=1.0) for t in _DISTINCT_TITLES[:4]]

        assert len(det_module._dedup_near_duplicate_articles(arts, _enabled_guard())) == 4

    def test_ac103_001_far_apart_publish_time_is_not_deduped(self, make_theme_news):
        """제목이 동일해도 발행 시각 차가 dedup 창을 넘으면 중복이 아니다."""
        a = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        b = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=30.0)  # 29h 차 > 6h

        assert len(det_module._dedup_near_duplicate_articles([a, b], _enabled_guard())) == 2

    def test_ac103_001_theme_activation_count_uses_deduped_value(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """통합: 테마 활성 판정 카운트가 raw(3)이 아닌 중복 제거값(2)으로 계산된다."""
        surge_config.theme_freshness_guard = _enabled_guard()
        make_theme_stock("삼성전자", "005930")
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        make_theme_news(_DISTINCT_TITLES[1], hours_ago=1.5)

        results = _run(db, surge_config)

        # 고유 사건 2건 → theme_base = 0.2 (raw 3이었다면 0.15가 나온다)
        assert _score_of(results, "005930") == pytest.approx(min(1.0, 2 / 10) * 0.5)

    def test_ac103_001_boundary_dedup_drops_theme_below_min_article_count(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """경계 사례: raw(2)로는 통과하던 테마가 중복 제거 후 1건이 되어 비활성화된다."""
        surge_config.theme_freshness_guard = _enabled_guard()
        make_theme_stock("삼성전자", "005930")
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)

        assert _run(db, surge_config) == []

    def test_ac103_001_stock_article_attribution_is_deduped(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """종목별 기사 귀속 경로에도 중복 제거가 적용된다 (stock_article_score 감소)."""
        surge_config.theme_freshness_guard = _enabled_guard()
        make_theme_stock("에스케이하이닉스", "000660")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t)
        # 동일 종목 기사의 재보도 2건 — 귀속 카운트는 1이어야 한다
        make_theme_news("SK하이닉스가 반도체 라인을 증설한다", content="증설", hours_ago=2.0)
        make_theme_news("SK하이닉스가 반도체 라인을 증설한다", content="증설", hours_ago=1.0)

        results = _run(db, surge_config)

        # 반도체 키워드 매칭 기사는 5건(고유 3 + SK 재보도 2)이며, 재보도쌍이 1건으로
        # 축약되어 테마 카운트는 4가 된다. 종목 귀속 기사도 2 → 1로 축약된다.
        theme_base = min(1.0, 4 / 10)
        sentiment_factor = 0.8 + 0.4 * 0.7
        expected_deduped = (theme_base * 0.6 + min(1.0, 1 / 5) * 0.4) * sentiment_factor
        assert _score_of(results, "000660") == pytest.approx(expected_deduped)

        # 대조군: 가드 비활성 시에는 재보도가 각각 집계되어 더 높은 점수가 나온다
        surge_config.theme_freshness_guard = ThemeFreshnessGuardConfig()
        raw_expected = (min(1.0, 5 / 10) * 0.6 + min(1.0, 2 / 5) * 0.4) * sentiment_factor
        assert _score_of(_run(db, surge_config), "000660") == pytest.approx(raw_expected)
        assert raw_expected > expected_deduped

    def test_ac103_001_original_records_are_not_mutated(self, db: Session, make_theme_news):
        """중복 제거는 집계 필터일 뿐 — 원본 NewsArticle / DB 상태를 변경하지 않는다."""
        a = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        b = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        before = {(x.url, x.title, x.published_at) for x in (a, b)}

        det_module._dedup_near_duplicate_articles([a, b], _enabled_guard())

        assert {(x.url, x.title, x.published_at) for x in (a, b)} == before
        assert db.query(NewsArticle).count() == 2


# ===========================================================================
# §A — AC-AI103-002: 기본값 바이트 동등
# ===========================================================================


class TestDefaultByteEquivalence:
    """AC-AI103-002: 기본 설정에서는 본 SPEC 적용 이전과 완전히 동일한 결과."""

    def test_ac103_002_duplicate_fixture_matches_characterization_snapshot(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """중복 포함 픽스처에서 기본 설정 결과가 §M5 특성화 스냅샷과 동일하다."""
        make_theme_stock("삼성전자", "005930")
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        make_theme_news(_DISTINCT_TITLES[1], hours_ago=1.5)

        results = _run(db, surge_config)

        assert len(results) == 1
        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)

    def test_ac103_002_enabled_guard_with_default_thresholds_skips_decay(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """2단 스위치: enabled=True로 켜도 min_theme_freshness_ratio=0.0이면 감쇠 미발동."""
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t, hours_ago=40.0)  # 전부 진부 구간

        baseline = _score_of(_run(db, surge_config), "005930")
        surge_config.theme_freshness_guard = _enabled_guard()  # 임계는 기본값 0.0
        assert _score_of(_run(db, surge_config), "005930") == pytest.approx(baseline)


# ===========================================================================
# §A — AC-AI103-003 / AC-AI103-004: 진부화 감쇠 및 신선 테마 무감쇠
# ===========================================================================


class TestFreshnessDecay:
    """AC-AI103-003(진부화 분기) / AC-AI103-004(신선 분기 — 대칭 케이스)."""

    def test_ac103_003_stale_theme_is_discounted_but_not_removed(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """진부화된 테마는 freshness_discount_factor만큼 감쇠되되 후보에서 사라지지 않는다."""
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t, hours_ago=40.0)  # 신선 구간(24h) 밖 → ratio = 0.0

        baseline = _score_of(_run(db, surge_config), "005930")

        surge_config.theme_freshness_guard = _enabled_guard(min_theme_freshness_ratio=0.5)
        results = _run(db, surge_config)

        assert _score_of(results, "005930") == pytest.approx(baseline * 0.5)
        assert _score_of(results, "005930") is not None  # 완전 배제 아님

    def test_ac103_004_fresh_theme_is_not_discounted(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """모든 기사가 신선 구간 이내면 감쇠가 전혀 적용되지 않는다 (대칭 케이스)."""
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t, hours_ago=1.0)  # 신선 구간(24h) 이내 → ratio = 1.0

        baseline = _score_of(_run(db, surge_config), "005930")

        surge_config.theme_freshness_guard = _enabled_guard(min_theme_freshness_ratio=0.5)
        assert _score_of(_run(db, surge_config), "005930") == pytest.approx(baseline)

    def test_ac103_003_freshness_ratio_helper_partial_and_zero_denominator(self, make_theme_news):
        """신선 비율 계산: 부분 신선 값 + 빈 입력 0으로 나누기 방어."""
        cfg = _enabled_guard(fresh_window_hours=24.0)
        arts = [
            make_theme_news(_DISTINCT_TITLES[0], hours_ago=1.0),
            make_theme_news(_DISTINCT_TITLES[1], hours_ago=2.0),
            make_theme_news(_DISTINCT_TITLES[2], hours_ago=40.0),
        ]

        assert det_module._compute_theme_freshness_ratio(arts, cfg, 48) == pytest.approx(2 / 3)
        # 분모 0 방어 — 예외 없이 '완전 신선'(감쇠 미발동)으로 처리
        assert det_module._compute_theme_freshness_ratio([], cfg, 48) == 1.0

    def test_ac103_003_fresh_window_defaults_to_half_cluster_window(self, make_theme_news):
        """fresh_window_hours=None이면 cluster_window_hours/2(=24h)로 파생된다."""
        cfg = _enabled_guard()  # fresh_window_hours 기본 None
        assert cfg.fresh_window_hours is None
        arts = [
            make_theme_news(_DISTINCT_TITLES[0], hours_ago=23.0),  # 24h 이내
            make_theme_news(_DISTINCT_TITLES[1], hours_ago=25.0),  # 24h 밖
        ]

        assert det_module._compute_theme_freshness_ratio(arts, cfg, 48) == pytest.approx(0.5)


# ===========================================================================
# §A — AC-AI103-005: 유계된 가격 과열 방어 (SHOULD-PASS)
# ===========================================================================


def _overheat_history(base_day: datetime, base_close: int, latest_close: int):
    """활동 시작일 종가 → 익일 종가 상승을 나타내는 2행 일봉 이력 (최신순 내림차순)."""
    return [
        PriceRecord(date=(base_day + timedelta(days=1)).strftime("%Y.%m.%d"), close=latest_close),
        PriceRecord(date=base_day.strftime("%Y.%m.%d"), close=base_close),
    ]


class TestPriceOverheatGuard:
    """AC-AI103-005: 절단 이후 유계 후보에만, 단일 배치 호출로 과열 감쇠를 적용한다."""

    def _setup(self, surge_config, make_theme_stock, make_theme_news, *, max_candidates=3):
        surge_config.theme_cluster.sector_only_max_candidates = max_candidates
        surge_config.theme_freshness_guard = _enabled_guard(price_overheat_enabled=True)
        stock = make_theme_stock("삼성전자", "005930")
        arts = [make_theme_news(t, hours_ago=30.0) for t in _DISTINCT_TITLES[:3]]
        return stock, min(a.published_at for a in arts)

    def test_ac103_005_overheated_candidate_is_discounted_with_single_batch_call(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """과열 후보 점수가 감쇠되고, 배치 가격 조회가 정확히 1회만 호출된다."""
        _stock, activity_start = self._setup(surge_config, make_theme_stock, make_theme_news)
        baseline = min(1.0, 3 / 10) * 0.5  # 감쇠 이전 섹터 전용 점수

        batch = MagicMock(
            return_value={"005930": _overheat_history(activity_start, 10000, 12000)}  # +20%
        )
        with patch("app.services.naver_finance.fetch_stock_price_history_batch_sync", batch):
            results = _run(db, surge_config)

        assert batch.call_count == 1
        assert _score_of(results, "005930") == pytest.approx(baseline * 0.5)

    def test_ac103_005_non_overheated_candidate_is_untouched(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """과열 임계 미만 상승은 감쇠되지 않는다."""
        _stock, activity_start = self._setup(surge_config, make_theme_stock, make_theme_news)

        batch = MagicMock(
            return_value={"005930": _overheat_history(activity_start, 10000, 10500)}  # +5%
        )
        with patch("app.services.naver_finance.fetch_stock_price_history_batch_sync", batch):
            results = _run(db, surge_config)

        assert batch.call_count == 1
        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)

    def test_ac103_005_skipped_when_max_candidates_is_none(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """sector_only_max_candidates=None이면 price_overheat_enabled=true여도 배치 호출 0회.

        (acceptance.md §B '가격 과열 서브기능 비활성 시 스킵' 엣지 케이스)
        """
        surge_config.theme_cluster.sector_only_max_candidates = None
        surge_config.theme_freshness_guard = _enabled_guard(price_overheat_enabled=True)
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t, hours_ago=30.0)

        batch = MagicMock(return_value={})
        with patch("app.services.naver_finance.fetch_stock_price_history_batch_sync", batch):
            results = _run(db, surge_config)

        assert batch.call_count == 0
        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)

    def test_ac103_005_defensive_paths_never_discount_or_raise(self, make_theme_news):
        """방어 분기 단위 검증: 이력이 부족하거나 손상돼도 감쇠 없이 안전하게 통과한다."""
        cfg = _enabled_guard(price_overheat_enabled=True)
        base_day = datetime(2026, 8, 1)

        def _candidate(code: str = "005930", score: float = 0.5):
            return det_module.SurgeCandidate(
                stock_code=code, stock_name="테스트", theme_cluster_score=score,
                active_detectors=["theme_cluster"],
            )

        # 대상 집합이 비었거나 활동 시작 시각을 모르면 배치 호출 자체가 없다
        batch = MagicMock(return_value={})
        with patch("app.services.naver_finance.fetch_stock_price_history_batch_sync", batch):
            assert det_module._apply_price_overheat_discount([_candidate()], set(), cfg, base_day) == 0
            assert det_module._apply_price_overheat_discount(
                [_candidate()], {"005930"}, cfg, None
            ) == 0
        assert batch.call_count == 0

        cases = {
            "대상 외 종목": ({"999999": _overheat_history(base_day, 10000, 12000)}, {"999999"}),
            "이력 1행 미만": ({"005930": [PriceRecord(date="2026.08.02", close=12000)]}, {"005930"}),
            "손상된 날짜 문자열": (
                {"005930": [PriceRecord(date="not-a-date", close=12000),
                            PriceRecord(date="also-bad", close=10000)]},
                {"005930"},
            ),
            "기준가 0": (
                {"005930": [PriceRecord(date="2026.08.02", close=12000),
                            PriceRecord(date="2026.08.01", close=0)]},
                {"005930"},
            ),
        }
        for label, (history, targets) in cases.items():
            candidate = _candidate()
            with patch(
                "app.services.naver_finance.fetch_stock_price_history_batch_sync",
                MagicMock(return_value=history),
            ):
                discounted = det_module._apply_price_overheat_discount(
                    [candidate], targets, cfg, base_day
                )
            assert discounted == 0, label
            assert candidate.theme_cluster_score == pytest.approx(0.5), label

    def test_ac103_005_batch_failure_degrades_without_raising(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """배치 조회가 실패해도 예외를 전파하지 않고 감쇠 없이 진행한다."""
        self._setup(surge_config, make_theme_stock, make_theme_news)

        batch = MagicMock(side_effect=RuntimeError("network down"))
        with patch("app.services.naver_finance.fetch_stock_price_history_batch_sync", batch):
            results = _run(db, surge_config)

        assert _score_of(results, "005930") == pytest.approx(min(1.0, 3 / 10) * 0.5)


# ===========================================================================
# §A — AC-AI103-006: 종목 순회 루프 내 동기 가격 호출 금지 (Must-Pass 불변식)
# ===========================================================================


class TestNoPerStockSyncPriceCall:
    """AC-AI103-006: 어떤 가드 조합에서도 종목별 개별 동기 가격 호출이 발생하지 않는다.

    SPEC-AI-038 회귀 방지 불변식(921종목 × 0.6s/call = 550초 timeout).
    """

    @pytest.mark.parametrize(
        "guard_factory, max_candidates",
        [
            (lambda: ThemeFreshnessGuardConfig(), None),                       # 가드 비활성
            (lambda: _enabled_guard(), None),                                  # 가드만 활성
            (lambda: _enabled_guard(price_overheat_enabled=True), 3),          # 과열까지 활성
        ],
        ids=["guard-off", "guard-on", "guard-on+overheat-on"],
    )
    def test_ac103_006_no_per_stock_sync_price_call_in_any_guard_combo(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
        guard_factory, max_candidates,
    ):
        surge_config.theme_freshness_guard = guard_factory()
        surge_config.theme_cluster.sector_only_max_candidates = max_candidates
        for i in range(12):  # 섹터 소속 종목 다수
            make_theme_stock(f"반도체종목{i}", f"1{i:05d}")
        arts = [make_theme_news(t, hours_ago=30.0) for t in _DISTINCT_TITLES[:3]]
        activity_start = min(a.published_at for a in arts)

        per_stock_spy = MagicMock(return_value={"change_rate": 0.0})
        current_price_spy = MagicMock(return_value={"change_rate": 0.0})
        batch = MagicMock(
            return_value={
                f"1{i:05d}": _overheat_history(activity_start, 10000, 12000) for i in range(12)
            }
        )

        with patch.object(det_module, "_fetch_price_change_sync", per_stock_spy), patch(
            "app.services.naver_finance.fetch_current_price_with_change_sync", current_price_spy
        ), patch("app.services.naver_finance.fetch_stock_price_history_batch_sync", batch):
            results = _run(db, surge_config)

        assert results, "픽스처가 후보를 생성하지 못해 불변식 검증이 무의미해짐"
        assert per_stock_spy.call_count == 0
        assert current_price_spy.call_count == 0
        # 과열 서브기능이 켜진 조합에서도 배치 호출은 최대 1회 (AC-AI103-005와 상호 정합)
        assert batch.call_count <= 1


# ===========================================================================
# §A — AC-AI103-007: 관측성 로깅 (Must-Pass)
# ===========================================================================


class TestObservabilityLogging:
    """AC-AI103-007: 활성 테마별 중복 제거 기사 수 + 신선 비율을 DEBUG 로그로 남긴다."""

    def test_ac103_007_debug_log_contains_deduped_count_and_freshness_ratio(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
        caplog,
    ):
        surge_config.theme_freshness_guard = _enabled_guard()
        make_theme_stock("삼성전자", "005930")
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)  # 중복 2건
        make_theme_news(_DISTINCT_TITLES[1], hours_ago=1.5)

        with caplog.at_level(logging.DEBUG, logger=det_module.logger.name):
            _run(db, surge_config)

        records = [
            r.getMessage() for r in caplog.records
            if "신선도가드" in r.getMessage() and r.levelno == logging.DEBUG
        ]
        assert records, "신선도가드 DEBUG 로그 레코드가 존재해야 한다"
        msg = records[0]
        assert "deduped_articles=2" in msg   # raw 3 → 중복 제거 2
        assert "raw_articles=3" in msg
        assert "freshness_ratio=" in msg

    def test_ac103_007_no_guard_log_when_disabled(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
        caplog,
    ):
        """가드 비활성 시에는 관측성 로그 자체가 발생하지 않는다."""
        make_theme_stock("삼성전자", "005930")
        for t in _DISTINCT_TITLES[:3]:
            make_theme_news(t)

        with caplog.at_level(logging.DEBUG, logger=det_module.logger.name):
            _run(db, surge_config)

        assert not [r for r in caplog.records if "신선도가드" in r.getMessage()]


# ===========================================================================
# §B — Edge Cases + 하드 캡 성능 경계
# ===========================================================================


class TestEdgeCases:
    """acceptance.md §B Edge Cases."""

    def test_edge_timezone_aware_published_at_is_normalized(self):
        """tz-aware/naive 혼재(SQLite vs PostgreSQL) 정규화 — 시각 차 연산이 깨지지 않는다."""
        aware = datetime(2026, 8, 5, 3, 0, tzinfo=timezone(timedelta(hours=9)))  # KST 03:00
        naive = det_module._as_naive_utc(aware)

        assert naive == datetime(2026, 8, 4, 18, 0)  # UTC로 환산된 naive 값
        assert naive.tzinfo is None
        assert det_module._as_naive_utc(None) is None
        # 이미 naive면 그대로 통과
        assert det_module._as_naive_utc(datetime(2026, 8, 4, 18, 0)) == datetime(2026, 8, 4, 18, 0)

    def test_edge_empty_window_with_guard_enabled(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock,
    ):
        """빈 뉴스 창: 가드 활성/비활성 무관하게 빈 목록."""
        surge_config.theme_freshness_guard = _enabled_guard()
        make_theme_stock("삼성전자", "005930")
        assert _run(db, surge_config) == []

    def test_edge_all_identical_titles_collapse_to_one_without_zero_division(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_news,
    ):
        """전량 동일 제목: 1건으로 수렴하고 신선 비율이 ZeroDivisionError 없이 계산된다."""
        cfg = _enabled_guard()
        arts = [
            make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0 + i * 0.1)
            for i in range(5)
        ]

        deduped = det_module._dedup_near_duplicate_articles(arts, cfg)

        assert len(deduped) == 1
        assert det_module._compute_theme_freshness_ratio(deduped, cfg, 48) == pytest.approx(1.0)

    def test_edge_publish_time_delta_exactly_at_window_boundary_is_inclusive(
        self, db: Session, make_theme_news,
    ):
        """경계값: 발행 시각 차가 정확히 dedup 창과 같으면 '포함'(중복으로 판정)한다.

        두 팩토리 호출 사이의 마이크로초 드리프트가 경계 판정을 흔들지 않도록
        published_at을 명시적으로 고정한다(시각 의존 flaky 방지).
        """
        cfg = _enabled_guard(duplicate_dedup_window_hours=6.0)
        a = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=7.0)
        b = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        b.published_at = a.published_at + timedelta(hours=6)  # 정확히 6.0h 차로 고정
        db.flush()

        assert abs(b.published_at - a.published_at) == timedelta(hours=6)
        assert len(det_module._dedup_near_duplicate_articles([a, b], cfg)) == 1

        # 경계를 아주 살짝 넘으면 배제된다 (경계 방향이 <= 임을 대칭으로 확인)
        cfg_tight = _enabled_guard(duplicate_dedup_window_hours=5.99)
        assert len(det_module._dedup_near_duplicate_articles([a, b], cfg_tight)) == 2

    def test_edge_multi_theme_dedup_does_not_cross_contaminate(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """한 테마의 중복 제거가 다른 테마의 부분집합 카운트를 오염시키지 않는다."""
        surge_config.theme_freshness_guard = _enabled_guard()
        make_theme_stock("삼성전자", "005930")
        # 반도체 테마: 재보도 2건(→1) + 고유 2건 = 3
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=2.0)
        make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        make_theme_news(_DISTINCT_TITLES[1], hours_ago=1.5)
        make_theme_news(_DISTINCT_TITLES[2], hours_ago=1.5)
        # 두 테마에 동시 매칭되는 기사 (반도체 + 로봇)
        make_theme_news("반도체 공정용 로봇 수요 급증", hours_ago=1.2)

        # 반도체 부분집합: 재보도쌍(1) + 고유2 + 교차1 = 4
        results = _run(db, surge_config)

        assert _score_of(results, "005930") == pytest.approx(min(1.0, 4 / 10) * 0.5)

    def test_edge_articles_without_published_at_are_not_treated_as_duplicates(
        self, db: Session, make_theme_news,
    ):
        """발행 시각이 없으면 근접도를 판정할 수 없으므로 중복으로 보지 않는다."""
        a = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        b = make_theme_news("반도체 업계 신규 투자 발표", hours_ago=1.0)
        b.published_at = None
        db.flush()

        assert len(det_module._dedup_near_duplicate_articles([a, b], _enabled_guard())) == 2


class TestDedupHardCapBoundary:
    """acceptance.md §B 성능 경계: dedup_max_comparison_batch 하드 캡의 구조적 유계성.

    핵심 검증은 "관측상 빠르다"가 아니라 **캡을 초과해도 비교 연산량이 늘지 않는다**는
    코드 강제 상한이다(spec.md §Decisions D4). 실행 시간은 환경 의존적이라 보조 지표로만
    사용하고, 1차 판정은 결정적인 비교 횟수 계측으로 수행한다.
    """

    @staticmethod
    def _count_ratio_calls(articles, cfg) -> tuple[int, list]:
        """dedup 수행 중 실제 SequenceMatcher.ratio() 호출 횟수를 계측한다."""
        calls = [0]
        original = det_module.difflib.SequenceMatcher.ratio

        def counting_ratio(self):
            calls[0] += 1
            return original(self)

        with patch.object(det_module.difflib.SequenceMatcher, "ratio", counting_ratio):
            kept = det_module._dedup_near_duplicate_articles(articles, cfg)
        return calls[0], kept

    def test_comparison_cost_is_structurally_bounded_by_cap(self, make_theme_news):
        """캡 도달(200)과 캡 초과(500)에서 비교 횟수가 동일하게 O(캡²) 이내로 유계된다."""
        cfg = _enabled_guard(dedup_max_comparison_batch=200)
        cap = cfg.dedup_max_comparison_batch

        pool = [
            make_theme_news(f"{_DISTINCT_TITLES[i % 6]} 심층분석 {i}편", hours_ago=1.0)
            for i in range(500)
        ]

        at_cap_calls, _ = self._count_ratio_calls(pool[:cap], cfg)
        over_cap_calls, over_kept = self._count_ratio_calls(pool, cfg)

        upper_bound = cap * (cap - 1) // 2
        assert at_cap_calls <= upper_bound
        # 캡 초과분은 비교 없이 통과하므로 비교 횟수가 증가하지 않는다 (O(N²) 방향 증가 없음)
        assert over_cap_calls <= at_cap_calls
        # 캡 초과분(300건)은 개별 건으로 그대로 집계에 포함된다 (raw-count 방향 안전 열화)
        assert len(over_kept) >= len(pool) - cap

    def test_over_cap_wallclock_does_not_exceed_at_cap(self, make_theme_news):
        """보조 지표: 캡 초과(500) 실행 시간이 캡 도달(200) 대비 유의하게 늘지 않는다."""
        cfg = _enabled_guard(dedup_max_comparison_batch=200)
        pool = [
            make_theme_news(f"{_DISTINCT_TITLES[i % 6]} 심층분석 {i}편", hours_ago=1.0)
            for i in range(500)
        ]

        def _elapsed(items) -> float:
            start = time.perf_counter()
            det_module._dedup_near_duplicate_articles(items, cfg)
            return time.perf_counter() - start

        at_cap = min(_elapsed(pool[:200]) for _ in range(3))
        over_cap = min(_elapsed(pool) for _ in range(3))

        # 정렬/슬라이스 오버헤드만 추가되므로 1.2배(20%) 이내여야 한다.
        assert over_cap <= at_cap * 1.2 + 0.05
