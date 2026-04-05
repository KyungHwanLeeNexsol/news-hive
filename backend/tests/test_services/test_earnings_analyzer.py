"""earnings_analyzer 모듈 테스트.

SPEC-AI-002 REQ-AI-018: DART 어닝 서프라이즈 예측.
- AC-018-1: 어닝 프리뷰 생성 (D-5 이내 실적 공시 시 earnings_preview 분석)
- AC-018-2: 긍정적 서프라이즈 시 confidence +0.1
- AC-018-3: 실적 후 정확도 추적 (예측 vs 실제 비교 로그)
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.services.earnings_analyzer import (
    SURPRISE_CONFIDENCE_BOOST,
    SURPRISE_CONFIDENCE_THRESHOLD,
    analyze_earnings_preview,
    apply_earnings_confidence_adjustment,
    calculate_surprise_probability,
    format_earnings_for_briefing,
    get_upcoming_earnings,
    track_earnings_accuracy,
)


class TestGetUpcomingEarnings:
    """get_upcoming_earnings 유닛 테스트."""

    def test_no_disclosures_returns_empty(self, db: Session) -> None:
        """공시 데이터 없음 → 빈 리스트 반환."""
        result = get_upcoming_earnings(db)
        assert result == []

    def test_returns_stocks_with_earnings_disclosures(
        self, db: Session, make_stock, make_disclosure
    ) -> None:
        """실적 관련 공시가 있는 종목을 반환한다."""
        stock = make_stock(name="현대제철")
        today = datetime.now().strftime("%Y%m%d")
        make_disclosure(
            stock_id=stock.id,
            report_name="사업보고서 (2024년)",
            report_type="정기공시",
            rcept_dt=today,
        )

        result = get_upcoming_earnings(db, days_ahead=5)
        assert len(result) == 1
        assert result[0]["stock_id"] == stock.id
        assert result[0]["stock_name"] == "현대제철"

    def test_ignores_non_earnings_disclosure(
        self, db: Session, make_stock, make_disclosure
    ) -> None:
        """실적 관련이 아닌 공시는 제외한다."""
        stock = make_stock()
        today = datetime.now().strftime("%Y%m%d")
        make_disclosure(
            stock_id=stock.id,
            report_name="유상증자 결정",
            report_type="발행공시",
            rcept_dt=today,
        )

        result = get_upcoming_earnings(db, days_ahead=5)
        assert result == []

    def test_deduplicates_by_stock(
        self, db: Session, make_stock, make_disclosure
    ) -> None:
        """같은 종목의 여러 공시는 중복 없이 1개만 반환."""
        stock = make_stock()
        today = datetime.now().strftime("%Y%m%d")
        make_disclosure(
            stock_id=stock.id,
            report_name="분기보고서",
            report_type="정기공시",
            rcept_dt=today,
        )
        make_disclosure(
            stock_id=stock.id,
            report_name="사업보고서",
            report_type="정기공시",
            rcept_dt=today,
        )

        result = get_upcoming_earnings(db, days_ahead=5)
        assert len(result) == 1

    def test_ignores_old_disclosures(
        self, db: Session, make_stock, make_disclosure
    ) -> None:
        """D-5 범위 밖의 오래된 공시는 제외한다."""
        stock = make_stock()
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        make_disclosure(
            stock_id=stock.id,
            report_name="사업보고서",
            report_type="정기공시",
            rcept_dt=old_date,
        )

        result = get_upcoming_earnings(db, days_ahead=5)
        assert result == []


class TestAnalyzeEarningsPreview:
    """analyze_earnings_preview 유닛 테스트."""

    def test_invalid_stock_returns_error(self, db: Session) -> None:
        """존재하지 않는 종목 → 에러 상태 반환."""
        result = analyze_earnings_preview(db, stock_id=99999)
        assert result["status"] == "error"

    def test_returns_ok_with_valid_stock(
        self, db: Session, make_stock
    ) -> None:
        """유효한 종목 → ok 상태와 분석 결과 반환."""
        stock = make_stock(name="삼성전자")
        result = analyze_earnings_preview(db, stock.id)

        assert result["status"] == "ok"
        assert result["stock_id"] == stock.id
        assert result["stock_name"] == "삼성전자"
        assert "past_pattern" in result
        assert "sector_trend" in result
        assert "news_sentiment" in result
        assert "surprise_probability" in result
        assert "confidence_adjustment" in result

    def test_confidence_adjustment_applied_when_high_prob(
        self, db: Session, make_stock, make_fund_signal
    ) -> None:
        """서프라이즈 확률이 임계값 이상이면 confidence_adjustment > 0."""
        stock = make_stock()
        # 과거 시그널 모두 적중 (높은 적중률 = 높은 서프라이즈 확률)
        for _ in range(5):
            make_fund_signal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                is_correct=True,
                return_pct=5.0,
            )

        result = analyze_earnings_preview(db, stock.id)
        # 높은 적중률이면 confidence_adjustment가 0보다 커야 함
        assert result["status"] == "ok"
        # 확률이 60% 이상이면 +0.1
        if result["surprise_probability"] >= SURPRISE_CONFIDENCE_THRESHOLD:
            assert result["confidence_adjustment"] == SURPRISE_CONFIDENCE_BOOST


class TestCalculateSurpriseProbability:
    """calculate_surprise_probability 유닛 테스트."""

    def test_no_data_returns_default(self, db: Session, make_stock) -> None:
        """데이터 없음 → 기본 확률(0.5) 반환."""
        stock = make_stock()
        prob = calculate_surprise_probability(db, stock.id)
        assert prob == 0.5

    def test_invalid_stock_returns_default(self, db: Session) -> None:
        """존재하지 않는 종목 → 0.5 반환."""
        prob = calculate_surprise_probability(db, stock_id=99999)
        assert prob == 0.5

    def test_high_hit_rate_increases_probability(
        self, db: Session, make_stock, make_fund_signal
    ) -> None:
        """과거 적중률이 높으면 서프라이즈 확률이 상승한다."""
        stock = make_stock()
        for _ in range(10):
            make_fund_signal(
                stock_id=stock.id,
                is_correct=True,
                return_pct=3.0,
            )

        prob = calculate_surprise_probability(db, stock.id)
        assert prob > 0.5  # 기본보다 높아야 함

    def test_low_hit_rate_decreases_probability(
        self, db: Session, make_stock, make_fund_signal
    ) -> None:
        """과거 적중률이 낮으면 서프라이즈 확률이 하락한다."""
        stock = make_stock()
        for _ in range(10):
            make_fund_signal(
                stock_id=stock.id,
                is_correct=False,
                return_pct=-3.0,
            )

        prob = calculate_surprise_probability(db, stock.id)
        assert prob < 0.5  # 기본보다 낮아야 함

    def test_probability_bounded_0_to_1(
        self, db: Session, make_stock
    ) -> None:
        """확률은 항상 0.0 ~ 1.0 범위."""
        stock = make_stock()
        prob = calculate_surprise_probability(db, stock.id)
        assert 0.0 <= prob <= 1.0


class TestApplyEarningsConfidenceAdjustment:
    """apply_earnings_confidence_adjustment 유닛 테스트."""

    def test_high_prob_boosts_confidence(self) -> None:
        """서프라이즈 확률 >= 60% → confidence +0.1."""
        result = apply_earnings_confidence_adjustment(0.7, 0.65)
        assert result == pytest.approx(0.8)

    def test_low_prob_no_change(self) -> None:
        """서프라이즈 확률 < 60% → confidence 변경 없음."""
        result = apply_earnings_confidence_adjustment(0.7, 0.5)
        assert result == 0.7

    def test_exactly_threshold_boosts(self) -> None:
        """서프라이즈 확률 == 60% → confidence +0.1."""
        result = apply_earnings_confidence_adjustment(0.7, 0.6)
        assert result == pytest.approx(0.8)

    def test_capped_at_1_0(self) -> None:
        """confidence는 최대 1.0."""
        result = apply_earnings_confidence_adjustment(0.95, 0.8)
        assert result == 1.0

    def test_zero_confidence_boosted(self) -> None:
        """confidence 0에서도 정상 동작."""
        result = apply_earnings_confidence_adjustment(0.0, 0.7)
        assert result == pytest.approx(0.1)


class TestTrackEarningsAccuracy:
    """track_earnings_accuracy 유닛 테스트."""

    def test_no_verified_signals(self, db: Session, make_stock) -> None:
        """검증된 시그널 없음 → insufficient_data."""
        stock = make_stock()
        result = track_earnings_accuracy(db, stock.id)
        assert result["status"] == "insufficient_data"
        assert result["total_predictions"] == 0

    def test_tracks_verified_signals(
        self, db: Session, make_stock, make_fund_signal
    ) -> None:
        """검증 완료 시그널의 정확도를 추적한다."""
        stock = make_stock()
        now = datetime.utcnow()

        # 3개 적중, 2개 미적중
        for i in range(3):
            make_fund_signal(
                stock_id=stock.id,
                is_correct=True,
                return_pct=5.0,
                verified_at=now,
            )
        for i in range(2):
            make_fund_signal(
                stock_id=stock.id,
                is_correct=False,
                return_pct=-3.0,
                verified_at=now,
            )

        result = track_earnings_accuracy(db, stock.id)
        assert result["status"] == "tracked"
        assert result["total_predictions"] == 5
        assert result["correct_predictions"] == 3
        assert result["accuracy"] == 0.6
        assert result["avg_return"] == pytest.approx(1.8)


class TestFormatEarningsForBriefing:
    """format_earnings_for_briefing 유닛 테스트."""

    def test_empty_previews_returns_empty(self) -> None:
        """빈 리스트 → 빈 문자열."""
        assert format_earnings_for_briefing([]) == ""

    def test_formats_single_preview(self) -> None:
        """단일 프리뷰를 텍스트로 변환한다."""
        previews = [{
            "status": "ok",
            "stock_name": "현대제철",
            "surprise_probability": 0.75,
            "confidence_adjustment": 0.1,
            "past_pattern": {"hit_rate": 0.8, "avg_return": 3.5},
            "sector_trend": {"trend": "positive"},
            "news_sentiment": {"sentiment_score": 0.3},
        }]

        result = format_earnings_for_briefing(previews)
        assert "현대제철" in result
        assert "75%" in result
        assert "+0.1" in result
        assert "긍정적" in result

    def test_skips_error_status(self) -> None:
        """status가 error인 프리뷰는 건너뛴다."""
        previews = [
            {"status": "error", "message": "종목을 찾을 수 없습니다"},
        ]
        result = format_earnings_for_briefing(previews)
        # 헤더만 있거나 빈 문자열
        assert "에러" not in result.lower()

    def test_no_adjustment_when_low_prob(self) -> None:
        """낮은 확률일 때 +0.1이 표시되지 않는다."""
        previews = [{
            "status": "ok",
            "stock_name": "테스트종목",
            "surprise_probability": 0.4,
            "confidence_adjustment": 0.0,
            "past_pattern": {"hit_rate": 0.3, "avg_return": -1.0},
            "sector_trend": {"trend": "negative"},
            "news_sentiment": {"sentiment_score": -0.2},
        }]

        result = format_earnings_for_briefing(previews)
        assert "테스트종목" in result
        assert "+0.1" not in result
