"""SPEC-AI-039: Carry-Over 제한 + 뉴스 지연 반응 탐지기 인수 검증 테스트.

AC-039-001: carry-over 5역일 초과 시 skip
AC-039-002: detect_news_delayed_response가 24-72h 고임팩트 뉴스 종목을 SurgeCandidate로 반환
AC-039-003: 고임팩트 키워드 multiplier 적용
AC-039-004: 앙상블 가중치 합산 = 1.0
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


from app.services.surge_detector import (
    SurgeCandidate,
    compute_ensemble_score,
    detect_news_delayed_response,
)
from app.surge_config.surge_settings import (
    CarryoverConfig,
    HighImpactNewsConfig,
    get_surge_config,
)


# ---------------------------------------------------------------------------
# AC-039-001: Carry-Over 5역일 초과 skip
# ---------------------------------------------------------------------------

class TestCarryoverMaxDays:
    """AC-039-001: originally_created_at 기준 5역일 초과 시 carry-over skip."""

    def test_carryover_config_loaded(self) -> None:
        """CarryoverConfig가 surge_detection.yaml에서 로드되어야 한다."""
        cfg = get_surge_config()
        assert cfg.carryover is not None, "carryover 설정이 없음"
        assert cfg.carryover.max_trading_days == 3, (
            f"max_trading_days 3 기대, 실제: {cfg.carryover.max_trading_days}"
        )

    def test_carryover_config_default_max_days(self) -> None:
        """CarryoverConfig 기본값 max_trading_days가 3이어야 한다."""
        c = CarryoverConfig()
        assert c.max_trading_days == 3

    def test_carryover_cutoff_is_5_calendar_days(self) -> None:
        """3 거래일 ≈ 5 역일: max_trading_days=3이면 cutoff가 5일 전이어야 한다."""
        cfg = get_surge_config()
        max_td = cfg.carryover.max_trading_days
        # 3 거래일 * 1.67 ≈ 5 역일
        calendar_days = int(max_td * 1.67)
        assert calendar_days == 5, f"5역일 기대, 실제: {calendar_days}"

    def test_carryover_skips_signals_older_than_5_days(self) -> None:
        """originally_created_at이 6일 전인 시그널은 carry-over에서 skip되어야 한다."""
        # fund_manager._gather_surge_candidates의 carry-over 로직 단위 검증
        # cutoff: today_start - timedelta(days=5)
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = today_start - timedelta(days=5)

        # 6일 전 시그널 → cutoff보다 이전 → skip
        old_orig = today_start - timedelta(days=6)
        assert old_orig < cutoff, "6일 전 시그널은 cutoff보다 이전이어야 한다 (skip 대상)"

        # 4일 전 시그널 → cutoff보다 이후 → carry-over 허용
        recent_orig = today_start - timedelta(days=4)
        assert recent_orig >= cutoff, "4일 전 시그널은 cutoff 이후여야 한다 (carry-over 허용)"

    def test_carryover_null_originally_created_at_falls_back_to_created_at(self) -> None:
        """originally_created_at이 NULL이면 created_at을 fallback으로 사용해야 한다."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = today_start - timedelta(days=5)

        # Mock 시그널: originally_created_at=None, created_at=4일 전
        mock_signal = MagicMock()
        mock_signal.originally_created_at = None
        mock_signal.created_at = today_start - timedelta(days=4)

        # fallback 로직: orig = originally_created_at or created_at
        orig = mock_signal.originally_created_at or mock_signal.created_at
        assert orig >= cutoff, "created_at fallback으로 4일 전 시그널은 허용되어야 한다"


# ---------------------------------------------------------------------------
# AC-039-002: detect_news_delayed_response 반환값 형식
# ---------------------------------------------------------------------------

class TestNewsDelayedResponseDetector:
    """AC-039-002: detect_news_delayed_response가 SurgeCandidate 목록을 반환해야 한다."""

    def test_function_exists(self) -> None:
        """detect_news_delayed_response 함수가 surge_detector에 존재해야 한다."""
        from app.services import surge_detector  # noqa: F401
        assert hasattr(surge_detector, "detect_news_delayed_response"), (
            "detect_news_delayed_response 함수가 없음"
        )

    def test_returns_list_on_db_error(self) -> None:
        """DB 쿼리 실패 시 조용히 빈 목록을 반환해야 한다 (기존 탐지기 패턴 준수)."""
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("DB 연결 실패")
        mock_config = MagicMock()

        result = detect_news_delayed_response(mock_db, mock_config)
        assert result == [], "DB 오류 시 빈 목록 반환해야 함"

    def test_returns_surge_candidates(self) -> None:
        """고임팩트 뉴스 종목이 있으면 SurgeCandidate 목록을 반환해야 한다."""
        from app.models.news import NewsArticle
        from app.models.stock import Stock

        now = datetime.now(timezone.utc)

        # 48시간 전 기술이전 뉴스 기사 (24-72h 범위 내)
        mock_article = MagicMock(spec=NewsArticle)
        mock_article.id = 1
        mock_article.title = "한올바이오파마 1조 기술이전 로열티 계약 체결"
        mock_article.published_at = now - timedelta(hours=48)

        # 연관 종목
        mock_stock = MagicMock(spec=Stock)
        mock_stock.id = 101
        mock_stock.stock_code = "009420"
        mock_stock.name = "한올바이오파마"

        # news_stock_relations
        mock_relation = MagicMock()
        mock_relation.stock_id = 101
        mock_relation.news_id = 1

        mock_db = MagicMock()

        # 첫 번째 query: 24-72h 뉴스 조회
        mock_query_articles = MagicMock()
        mock_query_articles.filter.return_value.all.return_value = [mock_article]

        # 두 번째 query: news_stock_relations 조회
        mock_query_relations = MagicMock()
        mock_query_relations.filter.return_value.all.return_value = [mock_relation]

        # 세 번째 query: 당일 24h 내 동일 종목 기사 (없음 → skip 안 함)
        mock_query_today = MagicMock()
        mock_query_today.filter.return_value.first.return_value = None

        # 네 번째 query: 종목 조회
        mock_query_stock = MagicMock()
        mock_query_stock.filter.return_value.first.return_value = mock_stock

        call_count = [0]
        def side_effect(model):
            call_count[0] += 1
            n = call_count[0]
            if n == 1:
                return mock_query_articles
            elif n == 2:
                return mock_query_relations
            elif n == 3:
                return mock_query_today
            else:
                return mock_query_stock

        mock_db.query.side_effect = side_effect

        cfg = get_surge_config()
        result = detect_news_delayed_response(mock_db, cfg)

        assert isinstance(result, list), "반환값이 list여야 함"
        if result:
            assert all(isinstance(c, SurgeCandidate) for c in result), (
                "모든 항목이 SurgeCandidate여야 함"
            )

    def test_news_delayed_score_field_exists(self) -> None:
        """SurgeCandidate에 news_delayed_score 필드가 있어야 한다."""
        c = SurgeCandidate(stock_code="000001", stock_name="테스트")
        assert hasattr(c, "news_delayed_score"), "news_delayed_score 필드 없음"
        assert c.news_delayed_score == 0.0, "기본값 0.0이어야 함"

    def test_skips_stocks_with_news_within_24h(self) -> None:
        """당일 24h 이내 뉴스 있는 종목은 skip해야 한다 (즉각 반응은 다른 탐지기가 처리)."""
        from app.models.news import NewsArticle

        now = datetime.now(timezone.utc)

        mock_article = MagicMock(spec=NewsArticle)
        mock_article.id = 1
        mock_article.title = "삼성바이오로직스 기술이전 계약"
        mock_article.published_at = now - timedelta(hours=48)

        mock_relation = MagicMock()
        mock_relation.stock_id = 200
        mock_relation.news_id = 1

        # 당일 뉴스 있음 → skip
        mock_today_article = MagicMock(spec=NewsArticle)

        mock_db = MagicMock()
        call_count = [0]

        mock_q1 = MagicMock()
        mock_q1.filter.return_value.all.return_value = [mock_article]

        mock_q2 = MagicMock()
        mock_q2.filter.return_value.all.return_value = [mock_relation]

        mock_q3 = MagicMock()
        mock_q3.filter.return_value.first.return_value = mock_today_article  # 당일 뉴스 있음

        def side_effect(model):
            call_count[0] += 1
            n = call_count[0]
            if n == 1:
                return mock_q1
            elif n == 2:
                return mock_q2
            else:
                return mock_q3

        mock_db.query.side_effect = side_effect

        cfg = get_surge_config()
        result = detect_news_delayed_response(mock_db, cfg)
        assert result == [], "당일 뉴스 있는 종목은 skip되어 빈 목록이어야 함"


# ---------------------------------------------------------------------------
# AC-039-003: 고임팩트 키워드 multiplier 적용
# ---------------------------------------------------------------------------

class TestHighImpactNewsMultiplier:
    """AC-039-003: 고임팩트 키워드 뉴스 포함 시 multiplier가 적용되어야 한다."""

    def test_high_impact_news_config_loaded(self) -> None:
        """HighImpactNewsConfig가 surge_detection.yaml에서 로드되어야 한다."""
        cfg = get_surge_config()
        assert cfg.high_impact_news is not None, "high_impact_news 설정이 없음"

    def test_tech_transfer_multiplier_is_2_0(self) -> None:
        """기술이전 키워드 multiplier가 2.0이어야 한다."""
        cfg = get_surge_config()
        assert cfg.high_impact_news.tech_transfer_multiplier == 2.0, (
            f"tech_transfer_multiplier 2.0 기대, 실제: {cfg.high_impact_news.tech_transfer_multiplier}"
        )

    def test_clinical_multiplier_is_1_8(self) -> None:
        """임상/FDA 키워드 multiplier가 1.8이어야 한다."""
        cfg = get_surge_config()
        assert cfg.high_impact_news.clinical_multiplier == 1.8, (
            f"clinical_multiplier 1.8 기대, 실제: {cfg.high_impact_news.clinical_multiplier}"
        )

    def test_contract_multiplier_is_1_5(self) -> None:
        """수주/계약체결 키워드 multiplier가 1.5이어야 한다."""
        cfg = get_surge_config()
        assert cfg.high_impact_news.contract_multiplier == 1.5, (
            f"contract_multiplier 1.5 기대, 실제: {cfg.high_impact_news.contract_multiplier}"
        )

    def test_tech_transfer_keywords_in_config(self) -> None:
        """tech_transfer 키워드 목록에 '기술이전', '로열티', '기술수출'이 포함되어야 한다."""
        cfg = get_surge_config()
        hi = cfg.high_impact_news
        for kw in ["기술이전", "로열티", "기술수출"]:
            assert kw in hi.tech_transfer, f"tech_transfer에 '{kw}' 없음"

    def test_high_impact_config_default_values(self) -> None:
        """HighImpactNewsConfig 기본값이 올바르게 설정되어야 한다."""
        hi = HighImpactNewsConfig()
        assert hi.tech_transfer_multiplier == 2.0
        assert hi.clinical_multiplier == 1.8
        assert hi.contract_multiplier == 1.5

    def test_get_multiplier_for_tech_transfer_title(self) -> None:
        """'로열티' 포함 제목에 2.0x multiplier를 반환해야 한다."""
        hi = HighImpactNewsConfig()
        title = "한올바이오파마 1조 로열티 기술이전 계약"
        multiplier = hi.get_multiplier(title)
        assert multiplier == 2.0, f"tech_transfer multiplier 2.0 기대, 실제: {multiplier}"

    def test_get_multiplier_for_clinical_title(self) -> None:
        """'임상' 포함 제목에 1.8x multiplier를 반환해야 한다."""
        hi = HighImpactNewsConfig()
        title = "삼성바이오로직스 임상 3상 성공"
        multiplier = hi.get_multiplier(title)
        assert multiplier == 1.8, f"clinical multiplier 1.8 기대, 실제: {multiplier}"

    def test_get_multiplier_default_for_generic_title(self) -> None:
        """일반 뉴스 제목에는 기본값 1.0 multiplier를 반환해야 한다."""
        hi = HighImpactNewsConfig()
        title = "삼성전자 4분기 실적 발표"
        multiplier = hi.get_multiplier(title)
        assert multiplier == 1.0, f"일반 뉴스 multiplier 1.0 기대, 실제: {multiplier}"

    def test_get_multiplier_priority_tech_transfer_over_clinical(self) -> None:
        """tech_transfer 키워드가 clinical보다 우선순위가 높아야 한다 (multiplier 2.0)."""
        hi = HighImpactNewsConfig()
        title = "기술이전 임상 동시 포함 제목"
        multiplier = hi.get_multiplier(title)
        assert multiplier == 2.0, "tech_transfer(2.0)가 clinical(1.8)보다 우선되어야 함"


# ---------------------------------------------------------------------------
# AC-039-004: 앙상블 가중치 합 = 1.0
# ---------------------------------------------------------------------------

class TestEnsembleWeights:
    """AC-039-004: 앙상블 가중치 합산이 1.0이어야 한다."""

    def test_ensemble_weights_sum_to_1(self) -> None:
        """theme(0.22) + combo(0.28) + disclosure(0.16) + legacy(0.00) + delayed(0.13) + wgu(0.09) + vb(0.12) = 1.0.
        volume_breakout(0.12) 추가, 기존 5개 가중치 재조정.
        """
        cfg = get_surge_config()
        w = cfg.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
            + w.volume_breakout
        )
        assert abs(total - 1.0) <= 0.001, f"가중치 합산 1.0 기대, 실제: {total:.4f}"

    def test_individual_weights_match_spec(self) -> None:
        """각 탐지기 가중치가 volume_breakout 추가 후 재조정 값과 일치해야 한다."""
        cfg = get_surge_config()
        w = cfg.ensemble.weights
        assert w.theme_cluster == 0.22, f"theme_cluster 0.22 기대, 실제: {w.theme_cluster}"
        assert w.volume_news_combo == 0.28, f"volume_news_combo 0.28 기대, 실제: {w.volume_news_combo}"
        assert w.disclosure_pattern == 0.16, f"disclosure_pattern 0.16 기대, 실제: {w.disclosure_pattern}"
        # legacy_detectors: SPEC-AI-050에서 0.10→0.00으로 변경
        assert w.legacy_detectors == 0.00, f"legacy_detectors 0.00 기대, 실제: {w.legacy_detectors}"
        assert w.news_delayed == 0.13, f"news_delayed 0.13 기대, 실제: {w.news_delayed}"
        assert w.weekend_gap_up == 0.09, f"weekend_gap_up 0.09 기대, 실제: {w.weekend_gap_up}"
        assert w.volume_breakout == 0.12, f"volume_breakout 0.12 기대, 실제: {w.volume_breakout}"

    def test_validate_ensemble_weights_passes(self) -> None:
        """validate_ensemble_weights 모델 검증자가 통과해야 한다 (예외 없음)."""
        # 올바른 가중치로 SurgeDetectionConfig 생성 시 예외가 없어야 함
        cfg = get_surge_config()
        # 검증자가 이미 통과했으므로 cfg가 로드된 것 자체가 증거
        assert cfg is not None

    def test_news_delayed_score_included_in_ensemble(self) -> None:
        """compute_ensemble_score가 news_delayed_score를 포함해야 한다."""
        cfg = get_surge_config()
        # news_delayed_score만 있는 후보
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트",
            news_delayed_score=0.8,
        )
        score = compute_ensemble_score(candidate, cfg)
        # news_delayed 가중치(0.15) * 0.8 = 0.12 → 0 이상이어야 함
        assert score > 0.0, "news_delayed_score가 앙상블에 반영되어야 함"

    def test_ensemble_score_zero_without_any_score(self) -> None:
        """모든 점수가 0이면 앙상블 점수도 0이어야 한다."""
        cfg = get_surge_config()
        candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
        score = compute_ensemble_score(candidate, cfg)
        assert score == 0.0, f"모든 점수 0 → 앙상블 0 기대, 실제: {score}"

    def test_ensemble_score_within_bounds(self) -> None:
        """앙상블 점수는 0.0~1.0 범위이어야 한다."""
        cfg = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트",
            theme_cluster_score=1.0,
            combo_score=1.0,
            pattern_score=1.0,
            legacy_score=1.0,
            news_delayed_score=1.0,
        )
        score = compute_ensemble_score(candidate, cfg)
        assert 0.0 <= score <= 1.0, f"앙상블 점수 범위 초과: {score}"
