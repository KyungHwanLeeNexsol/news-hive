"""SPEC-AI-098: 테마 클러스터 뉴스-종목 매칭 일원화, 종목명 별칭 확장,
theme_news_carry 재활성화 관측성 — 검증 스위트.

AC-098-001 ~ AC-098-010 검증. conftest.py 공유 픽스처(db, make_stock, make_news)와
test_surge_scoring.py의 실제 YAML 기반 surge_config 픽스처 관례를 재사용한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.sector import Sector
from app.models.stock import Stock
from app.services import surge_detector as det_module
from app.services.keyword_matcher import _keyword_in_text
from app.services.keyword_tagging_service import (
    _compute_keyword_distribution_metrics,
    _compute_theme_news_carry_contribution_ratio,
    run_theme_news_carry_observability_check,
)
from app.surge_config.surge_settings import SurgeDetectionConfig, get_surge_config


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


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
    _counter = [0]

    def _factory(name: str, stock_code: str, market_cap: int = 2000) -> Stock:
        _counter[0] += 1
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
            title=title, content=content, url=f"https://example.com/spec-ai-098/{_counter[0]}",
            source="test", published_at=published_at, collected_at=published_at,
            sentiment="positive",
        )
        db.add(article)
        db.flush()
        return article

    return _factory


def _disable_price_bonus():
    """가격 보너스를 0으로 고정하는 price_change_provider 오버라이드 컨텍스트."""
    return patch.object(det_module, "_price_change_provider", lambda code: {"change_rate": 0.0})


# ---------------------------------------------------------------------------
# AC-098-001/002: 경계 가드 매칭 (keyword_matcher._keyword_in_text 재사용)
# ---------------------------------------------------------------------------


class TestBoundaryGuardMatching:
    """AC-098-001/002: 별칭 조사 활용형 매칭 + 오탐 방지 + 영문 대소문자 무관 매칭."""

    def test_ac098_001_alias_with_josa_matches(self):
        """AC-098-001: 별칭에 조사가 붙은 형태("LG전자가")도 매칭되어야 한다."""
        text = "lg전자가 신규 배터리 공장을 발표했다".lower()
        assert _keyword_in_text("LG전자", text) is True

    def test_ac098_002_short_alias_no_false_positive_and_case_insensitive(self):
        """AC-098-002: 부분 문자열 오탐 방지 + 영문 대소문자 무관 매칭 — 두 조건 모두 PASS해야 한다."""
        # 오탐 방지: "SDS"가 다른 고유명사(SDSCORP)의 일부로 우연히 일치하지 않아야 한다.
        no_false_positive = not _keyword_in_text("SDS", "sdscorp가 상장했다".lower())
        # 영문 대소문자 무관: "SKT"가 소문자로 등장해도 매칭되어야 한다.
        case_insensitive_match = _keyword_in_text("SKT", "skt가 5G 투자를 확대한다".lower())
        assert no_false_positive and case_insensitive_match

    def test_ac098_001_integration_subsidiary_mention_promotes_to_stock_specific(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """시나리오 1: 별칭이 붙은 종목 언급이 detect_theme_news_cluster()에서 실제로
        stock_specific_count>=1로 승격되어 60/40 블렌딩 경로로 전환되는지 확인한다."""
        make_theme_stock("엘지전자", "066570")
        [make_theme_news(f"반도체 업황 개선 기사 {i}") for i in range(2)]
        # "엘지전자"의 등록된 별칭 "LG전자"가 조사 붙은 형태로 등장
        make_theme_news("LG전자가 반도체 소재 신제품을 출시했다", content="LG전자 신제품")

        with _disable_price_bonus():
            result = det_module.detect_theme_news_cluster(db, [], surge_config)

        candidate = next((c for c in result if c.stock_code == "066570"), None)
        assert candidate is not None
        # 60/40 블렌딩 경로(직접 언급) 점수는 섹터 전용 페널티(0.5×best_theme_base)보다 커야 한다.
        theme_base = min(1.0, 3 / 10)
        sector_only_score = theme_base * surge_config.theme_cluster.sector_only_penalty
        assert candidate.theme_cluster_score > sector_only_score


# ---------------------------------------------------------------------------
# AC-098-003/004/005: 섹터 전용 스코어링 설정화
# ---------------------------------------------------------------------------


class TestSectorOnlyScoringConfig:
    """AC-098-003/004/005: 섹터 전용 페널티 설정화 + 절단 로직."""

    def test_ac098_003_default_byte_equivalent_to_legacy_hardcoded_value(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """AC-098-003: 기본값(0.5, None)에서는 이전 하드코딩 0.5× 페널티와 완전히 동일하다."""
        assert surge_config.theme_cluster.sector_only_penalty == 0.5
        assert surge_config.theme_cluster.sector_only_max_candidates is None

        make_theme_stock("삼성전자", "005930")
        [make_theme_news(f"반도체 업황 기사 {i}") for i in range(3)]  # 종목 전용 언급 없음

        with _disable_price_bonus():
            result = det_module.detect_theme_news_cluster(db, [], surge_config)

        candidate = next(c for c in result if c.stock_code == "005930")
        theme_base = min(1.0, 3 / 10)
        expected_legacy_score = theme_base * 0.5  # 본 SPEC 적용 이전 하드코딩 값
        assert candidate.theme_cluster_score == pytest.approx(expected_legacy_score)

    def test_ac098_004_custom_penalty_applies_only_to_sector_only_candidates(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """AC-098-004: sector_only_penalty=0.3 설정 시 섹터 전용 점수만 반영, 직접 언급 종목은 무영향."""
        surge_config.theme_cluster.sector_only_penalty = 0.3

        sector_only_stock = make_theme_stock("삼성전자", "005930")
        direct_stock = make_theme_stock("에스케이하이닉스", "000660")
        [make_theme_news(f"반도체 업황 기사 {i}") for i in range(3)]
        make_theme_news("SK하이닉스가 신규 라인을 증설한다", content="SK하이닉스 증설")

        with _disable_price_bonus():
            result = det_module.detect_theme_news_cluster(db, [], surge_config)

        sector_only_candidate = next(c for c in result if c.stock_code == sector_only_stock.stock_code)
        direct_candidate = next(c for c in result if c.stock_code == direct_stock.stock_code)

        theme_base = min(1.0, 3 / 10)
        assert sector_only_candidate.theme_cluster_score == pytest.approx(theme_base * 0.3)
        # 직접 언급 종목은 60/40 블렌딩 산식 그대로 — sector_only_penalty와 무관
        assert direct_candidate.theme_cluster_score > theme_base * 0.3

    def test_ac098_005_max_candidates_truncates_sector_only_but_not_direct_mention(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """AC-098-005: 섹터 전용 후보 10개 + 직접 언급 5개 fixture에 상한=3 적용 시
        결과가 섹터 전용 3개 + 직접 언급 5개(총 8개)여야 한다 — 두 조건 모두 성립해야 PASS."""
        surge_config.theme_cluster.sector_only_max_candidates = 3

        sector_only_codes = []
        for i in range(10):
            s = make_theme_stock(f"섹터전용종목{i}", f"1{i:05d}")
            sector_only_codes.append(s.stock_code)

        direct_codes = []
        for i in range(5):
            s = make_theme_stock(f"직접언급종목{i}", f"2{i:05d}")
            direct_codes.append(s.stock_code)

        [make_theme_news(f"반도체 업황 기사 {i}") for i in range(3)]
        for i, name in enumerate([f"직접언급종목{i}" for i in range(5)]):
            make_theme_news(f"{name}이 신규 투자를 발표했다", content=name)

        with _disable_price_bonus():
            result = det_module.detect_theme_news_cluster(db, [], surge_config)

        result_codes = {c.stock_code for c in result}
        kept_sector_only = result_codes & set(sector_only_codes)
        kept_direct = result_codes & set(direct_codes)

        assert len(kept_sector_only) == 3
        assert len(kept_direct) == 5

    def test_ac098_005_edge_case_max_candidates_larger_than_pool_is_noop(
        self, db: Session, surge_config: SurgeDetectionConfig, make_theme_stock, make_theme_news,
    ):
        """§D Edge Cases: sector_only_max_candidates가 후보 수보다 크면 절단 없이 전량 유지된다."""
        surge_config.theme_cluster.sector_only_max_candidates = 100
        make_theme_stock("삼성전자", "005930")
        [make_theme_news(f"반도체 업황 기사 {i}") for i in range(3)]

        with _disable_price_bonus():
            result = det_module.detect_theme_news_cluster(db, [], surge_config)

        assert any(c.stock_code == "005930" for c in result)


# ---------------------------------------------------------------------------
# AC-098-006: 별칭 후보 제안 스크립트
# ---------------------------------------------------------------------------


class TestSuggestStockNameAliasesScript:
    """AC-098-006: 별칭 후보 스크립트가 표를 자동 수정하지 않는다 + 후보 식별 정확도."""

    def test_ac098_006_finds_transliteration_candidate_and_never_mutates_alias_dict(self):
        """미등록 종목명 중 음역 패턴(에스케이 등) 후보를 정확히 식별하고,
        _STOCK_NAME_ALIASES 딕셔너리는 원본 그대로 보존되어야 한다 — 두 검증 모두 PASS해야 한다."""
        from app.services.surge_detector import _STOCK_NAME_ALIASES
        from scripts.suggest_stock_name_aliases import _find_candidate_alias

        before = json.dumps(_STOCK_NAME_ALIASES, sort_keys=True, ensure_ascii=False)

        # "에스케이" 세그먼트를 포함하는 미등록 종목명 → "SK"로 치환된 후보를 식별해야 한다.
        found = _find_candidate_alias("에스케이머티리얼즈")
        assert found is not None
        segment, replacement, candidate_alias = found
        assert segment == "에스케이"
        assert replacement == "SK"
        assert candidate_alias == "SK머티리얼즈"

        # 음역 패턴이 전혀 없는 종목명은 후보를 생성하지 않아야 한다.
        assert _find_candidate_alias("카카오뱅크") is None

        after = json.dumps(_STOCK_NAME_ALIASES, sort_keys=True, ensure_ascii=False)
        assert before == after  # 자동 수정 없음

    def test_ac098_006_suggest_candidates_excludes_already_registered_names(self, db: Session):
        """§D Edge Cases: 이미 등록된 별칭 키(예: "엘지전자")는 후보로 재제시되지 않는다."""
        from scripts.suggest_stock_name_aliases import suggest_candidates

        sector = Sector(name="테스트섹터")
        db.add(sector)
        db.flush()
        db.add(Stock(name="엘지전자", stock_code="066570", sector_id=sector.id))
        db.add(Stock(name="에스케이머티리얼즈", stock_code="036490", sector_id=sector.id))
        db.commit()

        candidates = suggest_candidates(db=db)
        names = {c["stock_name"] for c in candidates}

        assert "엘지전자" not in names  # 이미 _STOCK_NAME_ALIASES 키로 등록됨
        assert "에스케이머티리얼즈" in names


# ---------------------------------------------------------------------------
# AC-098-007/008/009: theme_news_carry 관측성 로깅
# ---------------------------------------------------------------------------


class TestThemeNewsCarryObservability:
    """AC-098-007/008/009: 키워드 분포 지표 + 기여 비율 로깅 + 임계값 초과 Telegram 경보."""

    def test_ac098_007_keyword_distribution_metrics_logged(
        self, db: Session, caplog: pytest.LogCaptureFixture,
    ):
        """AC-098-007: AC-AI091-009 정의와 동일한 10개 보유 비율 + 중앙값이 로그에 포함된다."""
        sector = Sector(name="테스트섹터")
        db.add(sector)
        db.flush()
        db.add(Stock(name="종목A", stock_code="111111", sector_id=sector.id, keywords=["k"] * 10))
        db.add(Stock(name="종목B", stock_code="222222", sector_id=sector.id, keywords=["k"] * 2))
        db.commit()

        full_cap_pct, median_length, tagged_count = _compute_keyword_distribution_metrics(db)

        assert tagged_count == 2
        assert full_cap_pct == pytest.approx(50.0)  # 2개 중 1개가 10개 보유
        assert median_length == pytest.approx(6.0)  # median(2, 10)

        with caplog.at_level(logging.INFO):
            run_theme_news_carry_observability_check(db)
        assert "10개보유비율=50.00%" in caplog.text

    def test_ac098_008_daily_contribution_ratio_logged(
        self, db: Session, caplog: pytest.LogCaptureFixture,
    ):
        """AC-098-008: 당일 surge_candidate 시그널 중 theme_news_carry 기여 비율이 로깅된다."""
        sector = Sector(name="테스트섹터")
        db.add(sector)
        db.flush()
        stock = Stock(name="종목A", stock_code="111111", sector_id=sector.id)
        db.add(stock)
        db.flush()

        now = datetime.now(timezone.utc)
        db.add(FundSignal(
            stock_id=stock.id, signal="buy", confidence=0.8, reasoning="test",
            signal_type="surge_candidate", created_at=now,
            surge_metadata=json.dumps({"surge_basis": ["theme_news_carry"]}),
        ))
        db.add(FundSignal(
            stock_id=stock.id, signal="buy", confidence=0.8, reasoning="test",
            signal_type="surge_candidate", created_at=now,
            surge_metadata=json.dumps({"surge_basis": ["volume_breakout"]}),
        ))
        db.commit()

        ratio = _compute_theme_news_carry_contribution_ratio(db)
        assert ratio == pytest.approx(0.5)

        with caplog.at_level(logging.INFO):
            run_theme_news_carry_observability_check(db)
        assert "기여비율=50.00%" in caplog.text

    def test_ac098_008_edge_case_zero_signals_returns_none_not_zero_division(self, db: Session):
        """§D Edge Cases: 당일 시그널 0건이면 ZeroDivisionError 없이 None(측정 불가)을 반환한다."""
        assert _compute_theme_news_carry_contribution_ratio(db) is None

    def test_ac098_009_alert_sent_when_ratio_exceeds_threshold(
        self, db: Session, monkeypatch: pytest.MonkeyPatch,
    ):
        """AC-098-009: 임계값 설정 + 초과 시 기존 Telegram 채널로 경보가 발송된다."""
        from app.surge_config.surge_settings import ThemeNewsCarryConfig

        sector = Sector(name="테스트섹터")
        db.add(sector)
        db.flush()
        stock = Stock(name="종목A", stock_code="111111", sector_id=sector.id)
        db.add(stock)
        db.flush()
        db.add(FundSignal(
            stock_id=stock.id, signal="buy", confidence=0.8, reasoning="test",
            signal_type="surge_candidate", created_at=datetime.now(timezone.utc),
            surge_metadata=json.dumps({"surge_basis": ["theme_news_carry"]}),
        ))
        db.commit()

        theme_news_carry_config = ThemeNewsCarryConfig(observability_alert_threshold=0.3)
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "12345")

        with patch(
            "app.services.telegram_service.send_telegram_message",
            new_callable=AsyncMock, return_value=True,
        ) as mock_send:
            result = run_theme_news_carry_observability_check(db, config=theme_news_carry_config)

        assert result["alert_sent"] is True
        mock_send.assert_awaited_once()

    def test_ac098_009_alert_skipped_when_chat_id_unset_fail_open(
        self, db: Session, monkeypatch: pytest.MonkeyPatch,
    ):
        """AC-098-009: TELEGRAM_ADMIN_CHAT_ID 미설정 시 fail-open — 경보 스킵, 예외 없음."""
        from app.surge_config.surge_settings import ThemeNewsCarryConfig

        sector = Sector(name="테스트섹터")
        db.add(sector)
        db.flush()
        stock = Stock(name="종목A", stock_code="111111", sector_id=sector.id)
        db.add(stock)
        db.flush()
        db.add(FundSignal(
            stock_id=stock.id, signal="buy", confidence=0.8, reasoning="test",
            signal_type="surge_candidate", created_at=datetime.now(timezone.utc),
            surge_metadata=json.dumps({"surge_basis": ["theme_news_carry"]}),
        ))
        db.commit()

        theme_news_carry_config = ThemeNewsCarryConfig(observability_alert_threshold=0.3)
        monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)

        result = run_theme_news_carry_observability_check(db, config=theme_news_carry_config)
        assert result["alert_sent"] is False

    def test_ac098_009_config_none_never_alerts(self, db: Session):
        """config가 주어지지 않으면(스케줄러 잡 미배선 상태) 경보 로직이 완전히 스킵된다."""
        result = run_theme_news_carry_observability_check(db, config=None)
        assert result["alert_sent"] is False
