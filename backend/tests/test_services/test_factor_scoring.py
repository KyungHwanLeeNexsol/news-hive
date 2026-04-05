"""factor_scoring 모듈 특성화 테스트 + SPEC-AI-002 유닛 테스트.

SPEC-AI-002 PRESERVE 단계: 기존 동작을 캡처하여 리팩터링 시 회귀 방지.
SPEC-AI-002 IMPROVE 단계: REQ-AI-014, REQ-AI-015 새 기능 테스트.
"""

import json


from app.services.factor_scoring import (
    compute_technical_score,
    compute_supply_demand_score,
    compute_news_sentiment_score,
    compute_valuation_score,
    compute_composite_score,
    build_factor_scores_json,
    analyze_multi_timeframe,
    detect_volume_spike,
)


class TestCharacterizeComputeTechnicalScore:
    """compute_technical_score 기존 동작 캡처."""

    def test_empty_market_data_returns_50(self) -> None:
        """빈 데이터 → 기본 중립 점수 50."""
        assert compute_technical_score({}) == 50

    def test_rsi_below_30_adds_20(self) -> None:
        """RSI < 30 과매도 → +20."""
        result = compute_technical_score({"rsi": 25})
        assert result == 70  # 50 + 20

    def test_rsi_between_30_and_40_adds_10(self) -> None:
        """RSI 30~40 → +10."""
        result = compute_technical_score({"rsi": 35})
        assert result == 60  # 50 + 10

    def test_rsi_above_70_subtracts_20(self) -> None:
        """RSI > 70 과매수 → -20."""
        result = compute_technical_score({"rsi": 75})
        assert result == 30  # 50 - 20

    def test_rsi_between_60_and_70_subtracts_10(self) -> None:
        """RSI 60~70 → -10."""
        result = compute_technical_score({"rsi": 65})
        assert result == 40  # 50 - 10

    def test_macd_golden_cross_adds_15(self) -> None:
        """MACD 골든크로스 → +15."""
        result = compute_technical_score({"macd_signal": "golden_cross"})
        assert result == 65  # 50 + 15

    def test_macd_dead_cross_subtracts_15(self) -> None:
        """MACD 데드크로스 → -15."""
        result = compute_technical_score({"macd_signal": "dead_cross"})
        assert result == 35  # 50 - 15

    def test_sma_bullish_adds_15(self) -> None:
        """SMA 정배열 → +15."""
        result = compute_technical_score({"sma_alignment": "bullish"})
        assert result == 65  # 50 + 15

    def test_sma_bearish_subtracts_15(self) -> None:
        """SMA 역배열 → -15."""
        result = compute_technical_score({"sma_alignment": "bearish"})
        assert result == 35  # 50 - 15

    def test_price_5d_trend_strong_up(self) -> None:
        """5일 추세 > 5% → +10."""
        result = compute_technical_score({"price_5d_trend": 6})
        assert result == 60  # 50 + 10

    def test_price_5d_trend_mild_up(self) -> None:
        """5일 추세 0~5% → +5."""
        result = compute_technical_score({"price_5d_trend": 3})
        assert result == 55  # 50 + 5

    def test_price_5d_trend_strong_down(self) -> None:
        """5일 추세 < -5% → -10."""
        result = compute_technical_score({"price_5d_trend": -6})
        assert result == 40  # 50 - 10

    def test_bollinger_below_lower_adds_10(self) -> None:
        """볼린저 하한 돌파 → +10."""
        result = compute_technical_score({"bollinger_position": "below_lower"})
        assert result == 60  # 50 + 10

    def test_bollinger_above_upper_subtracts_10(self) -> None:
        """볼린저 상한 돌파 → -10."""
        result = compute_technical_score({"bollinger_position": "above_upper"})
        assert result == 40  # 50 - 10

    def test_combined_bullish_signals(self) -> None:
        """복합 강세 신호 조합."""
        data = {
            "rsi": 25,           # +20
            "macd_signal": "golden_cross",  # +15
            "sma_alignment": "bullish",     # +15
            "price_5d_trend": 6,            # +10
            "bollinger_position": "below_lower",  # +10
        }
        result = compute_technical_score(data)
        # 50 + 20 + 15 + 15 + 10 + 10 = 120 → clamped to 100
        assert result == 100

    def test_combined_bearish_signals(self) -> None:
        """복합 약세 신호 조합."""
        data = {
            "rsi": 75,           # -20
            "macd_signal": "dead_cross",    # -15
            "sma_alignment": "bearish",     # -15
            "price_5d_trend": -6,           # -10
            "bollinger_position": "above_upper",  # -10
        }
        result = compute_technical_score(data)
        # 50 - 20 - 15 - 15 - 10 - 10 = -20 → clamped to 0
        assert result == 0

    def test_score_is_clamped_0_to_100(self) -> None:
        """점수 범위는 항상 0~100."""
        high = compute_technical_score({
            "rsi": 10, "macd_signal": "golden_cross",
            "sma_alignment": "bullish", "price_5d_trend": 10,
            "bollinger_position": "below_lower",
        })
        low = compute_technical_score({
            "rsi": 90, "macd_signal": "dead_cross",
            "sma_alignment": "bearish", "price_5d_trend": -10,
            "bollinger_position": "above_upper",
        })
        assert 0 <= high <= 100
        assert 0 <= low <= 100


class TestCharacterizeComputeSupplyDemandScore:
    """compute_supply_demand_score 기존 동작 캡처."""

    def test_empty_data_returns_50(self) -> None:
        """빈 데이터 → 중립 50."""
        assert compute_supply_demand_score({}) == 50

    def test_foreign_net_positive(self) -> None:
        """외국인 순매수 양수 → 가산."""
        result = compute_supply_demand_score({"foreign_net_5d": 50000})
        assert result == 55  # 50 + min(15, 50000/10000) = 50 + 5

    def test_foreign_net_negative(self) -> None:
        """외국인 순매도 → 감산."""
        result = compute_supply_demand_score({"foreign_net_5d": -50000})
        assert result == 45  # 50 - 5

    def test_institution_net_positive(self) -> None:
        """기관 순매수 양수 → 가산."""
        result = compute_supply_demand_score({"institution_net_5d": 100000})
        assert result == 60  # 50 + min(15, 10) = 60

    def test_strong_buy_momentum(self) -> None:
        """강한 매수세 → +10."""
        result = compute_supply_demand_score({"supply_momentum": "strong_buy"})
        assert result == 60

    def test_strong_sell_momentum(self) -> None:
        """강한 매도세 → -10."""
        result = compute_supply_demand_score({"supply_momentum": "strong_sell"})
        assert result == 40

    def test_volume_ratio_above_2(self) -> None:
        """거래량 2배 이상 → +10."""
        result = compute_supply_demand_score({"volume_ratio": 2.5})
        assert result == 60

    def test_volume_ratio_below_2_no_effect(self) -> None:
        """거래량 2배 미만 → 영향 없음."""
        result = compute_supply_demand_score({"volume_ratio": 1.5})
        assert result == 50

    def test_combined_bullish_supply_demand(self) -> None:
        """복합 수급 강세."""
        data = {
            "foreign_net_5d": 150000,   # +15 (capped)
            "institution_net_5d": 150000,  # +15 (capped)
            "supply_momentum": "strong_buy",  # +10
            "volume_ratio": 3.0,              # +10
        }
        result = compute_supply_demand_score(data)
        # 50 + 15 + 15 + 10 + 10 = 100
        assert result == 100


class TestCharacterizeComputeNewsSentimentScore:
    """compute_news_sentiment_score 기존 동작 캡처."""

    def test_no_news_returns_50(self) -> None:
        """뉴스 없음 → 중립 50."""
        assert compute_news_sentiment_score([]) == 50

    def test_positive_news(self) -> None:
        """긍정 뉴스 → 가산."""
        news = [{"sentiment": "positive", "weight": 1.0}]
        result = compute_news_sentiment_score(news)
        assert result == 60  # 50 + 10*1.0

    def test_negative_news(self) -> None:
        """부정 뉴스 → 감산."""
        news = [{"sentiment": "negative", "weight": 1.0}]
        result = compute_news_sentiment_score(news)
        assert result == 40  # 50 - 10*1.0

    def test_impact_stats_positive(self) -> None:
        """긍정적 과거 반응 → 가산."""
        result = compute_news_sentiment_score(
            [{"sentiment": "neutral"}],
            impact_stats={"avg_return_5d": 3.0},
        )
        # 50 + 0(neutral) + min(15, 3*3) = 50 + 9 = 59
        assert result == 59


class TestCharacterizeComputeValuationScore:
    """compute_valuation_score 기존 동작 캡처."""

    def test_empty_returns_50(self) -> None:
        assert compute_valuation_score({}) == 50

    def test_low_per_ratio(self) -> None:
        """PER이 업종 평균 대비 저평가 → 가산."""
        result = compute_valuation_score({"per": 7, "industry_per": 12})
        # ratio = 7/12 ≈ 0.58 < 0.7 → +20
        assert result == 70

    def test_high_per_ratio(self) -> None:
        """PER이 업종 평균 대비 고평가 → 감산."""
        result = compute_valuation_score({"per": 20, "industry_per": 12})
        # ratio = 20/12 ≈ 1.67 > 1.5 → -20
        assert result == 30


class TestCharacterizeComputeCompositeScore:
    """compute_composite_score 기존 동작 캡처."""

    def test_equal_scores(self) -> None:
        scores = {
            "news_sentiment": 50,
            "technical": 50,
            "supply_demand": 50,
            "valuation": 50,
        }
        assert compute_composite_score(scores) == 50.0

    def test_weighted_calculation(self) -> None:
        scores = {
            "news_sentiment": 80,
            "technical": 60,
            "supply_demand": 40,
            "valuation": 70,
        }
        # 기본 가중치 0.25 균등
        expected = round(80*0.25 + 60*0.25 + 40*0.25 + 70*0.25, 1)
        assert compute_composite_score(scores) == expected


class TestCharacterizeBuildFactorScoresJson:
    """build_factor_scores_json 기존 동작 캡처."""

    def test_returns_json_and_composite(self) -> None:
        json_str, composite = build_factor_scores_json(
            news_data=[],
            market_data={},
            financials={},
        )
        scores = json.loads(json_str)
        assert "news_sentiment" in scores
        assert "technical" in scores
        assert "supply_demand" in scores
        assert "valuation" in scores
        assert isinstance(composite, float)

    def test_all_neutral_data(self) -> None:
        """모든 데이터가 중립 → 모든 점수 50."""
        json_str, composite = build_factor_scores_json(
            news_data=[],
            market_data={},
            financials={},
        )
        scores = json.loads(json_str)
        assert scores["news_sentiment"] == 50
        assert scores["technical"] == 50
        assert scores["supply_demand"] == 50
        assert scores["valuation"] == 50
        assert composite == 50.0

    def test_includes_trend_alignment_and_volume_spike(self) -> None:
        """REQ-AI-014/015: JSON에 trend_alignment, volume_spike 포함."""
        json_str, _ = build_factor_scores_json(
            news_data=[],
            market_data={"sma_5_slope": 1.0, "sma_20_slope": 0.5, "price_vs_sma60": 2.0},
            financials={},
        )
        scores = json.loads(json_str)
        assert "trend_alignment" in scores
        assert "volume_spike" in scores
        assert "short_term" in scores
        assert "mid_term" in scores
        assert "long_term" in scores


# =============================================================================
# REQ-AI-014: 멀티 타임프레임 분석 테스트
# =============================================================================

class TestAnalyzeMultiTimeframe:
    """REQ-AI-014: analyze_multi_timeframe 유닛 테스트."""

    def test_empty_data_returns_mixed(self) -> None:
        """데이터 없음 → mixed."""
        result = analyze_multi_timeframe({})
        assert result["trend_alignment"] == "mixed"
        assert result["score_adjustment"] == 0
        assert result["confidence_adjustment"] == 0.0

    def test_all_up_aligned(self) -> None:
        """단기/중기/장기 모두 상승 → aligned, +15."""
        data = {
            "sma_5_slope": 1.0,
            "sma_20_slope": 0.5,
            "price_vs_sma60": 3.0,
        }
        result = analyze_multi_timeframe(data)
        assert result["trend_alignment"] == "aligned"
        assert result["short_term"] == "up"
        assert result["mid_term"] == "up"
        assert result["long_term"] == "up"
        assert result["score_adjustment"] == 15

    def test_all_down_aligned(self) -> None:
        """단기/중기/장기 모두 하락 → aligned, +15."""
        data = {
            "sma_5_slope": -1.0,
            "sma_20_slope": -0.5,
            "price_vs_sma60": -3.0,
        }
        result = analyze_multi_timeframe(data)
        assert result["trend_alignment"] == "aligned"
        assert result["score_adjustment"] == 15

    def test_short_up_long_down_divergent(self) -> None:
        """단기 상승 + 장기 하락 → divergent, confidence -0.1."""
        data = {
            "sma_5_slope": 1.0,
            "price_vs_sma60": -3.0,
        }
        result = analyze_multi_timeframe(data)
        assert result["trend_alignment"] == "divergent"
        assert result["score_adjustment"] == 0
        assert result["confidence_adjustment"] == -0.1

    def test_short_down_long_up_divergent(self) -> None:
        """단기 하락 + 장기 상승 → divergent."""
        data = {
            "sma_5_slope": -1.0,
            "price_vs_sma60": 3.0,
        }
        result = analyze_multi_timeframe(data)
        assert result["trend_alignment"] == "divergent"
        assert result["confidence_adjustment"] == -0.1

    def test_rsi_overrides_short_term_to_up(self) -> None:
        """RSI < 30 → 단기 '상승'으로 보정."""
        data = {
            "sma_5_slope": -0.5,  # 기울기는 하락이지만
            "rsi": 25,            # RSI 과매도 → 반등 기대
        }
        result = analyze_multi_timeframe(data)
        assert result["short_term"] == "up"

    def test_rsi_overrides_short_term_to_down(self) -> None:
        """RSI > 70 → 단기 '하락'으로 보정."""
        data = {
            "sma_5_slope": 0.5,   # 기울기는 상승이지만
            "rsi": 75,            # RSI 과매수 → 조정 우려
        }
        result = analyze_multi_timeframe(data)
        assert result["short_term"] == "down"

    def test_macd_golden_cross_overrides_mid_term(self) -> None:
        """MACD 골든크로스 → 중기 '상승'."""
        data = {"macd_signal": "golden_cross"}
        result = analyze_multi_timeframe(data)
        assert result["mid_term"] == "up"

    def test_macd_dead_cross_overrides_mid_term(self) -> None:
        """MACD 데드크로스 → 중기 '하락'."""
        data = {"macd_signal": "dead_cross"}
        result = analyze_multi_timeframe(data)
        assert result["mid_term"] == "down"

    def test_partial_alignment_two_same_direction(self) -> None:
        """2개 동일 방향 + 1개 neutral → aligned."""
        data = {
            "sma_5_slope": 1.0,   # short: up
            "price_vs_sma60": 2.0,  # long: up
            # mid: neutral (sma_20_slope 없음, macd_signal 없음)
        }
        result = analyze_multi_timeframe(data)
        assert result["trend_alignment"] == "aligned"

    def test_technical_score_with_aligned_trend(self) -> None:
        """aligned 추세 → technical score에 +15 가산."""
        base_score = compute_technical_score({})
        aligned_score = compute_technical_score({
            "sma_5_slope": 1.0,
            "sma_20_slope": 0.5,
            "price_vs_sma60": 3.0,
        })
        assert aligned_score == base_score + 15


# =============================================================================
# REQ-AI-015: 거래량 급증 감지 테스트
# =============================================================================

class TestDetectVolumeSpike:
    """REQ-AI-015: detect_volume_spike 유닛 테스트."""

    def test_no_spike_low_volume(self) -> None:
        """거래량 비율 < 2 → volume_spike = False."""
        result = detect_volume_spike({"volume_ratio": 1.5})
        assert result["volume_spike"] is False
        assert result["score_adjustment"] == 0

    def test_spike_without_price_rise(self) -> None:
        """거래량 2배 이상이지만 가격 하락 → score_adjustment = 0."""
        result = detect_volume_spike({"volume_ratio": 2.5, "price_5d_trend": -3})
        assert result["volume_spike"] is True
        assert result["score_adjustment"] == 0

    def test_spike_with_price_rise(self) -> None:
        """거래량 2배 이상 + 가격 상승 → score_adjustment = +10."""
        result = detect_volume_spike({"volume_ratio": 2.5, "price_5d_trend": 3})
        assert result["volume_spike"] is True
        assert result["score_adjustment"] == 10

    def test_spike_exactly_2x(self) -> None:
        """거래량 정확히 2배 → volume_spike = True."""
        result = detect_volume_spike({"volume_ratio": 2.0})
        assert result["volume_spike"] is True

    def test_empty_data(self) -> None:
        """빈 데이터 → volume_spike = False (기본 volume_ratio=1.0)."""
        result = detect_volume_spike({})
        assert result["volume_spike"] is False

    def test_supply_demand_with_volume_spike_and_rise(self) -> None:
        """REQ-AI-015: 거래량 급증 + 가격 상승 → supply_demand 점수 추가 가산.

        기존 volume_ratio > 2.0 가산(+10) + detect_volume_spike 추가(+10) = +20.
        """
        data = {
            "volume_ratio": 2.5,
            "price_5d_trend": 3,
        }
        result = compute_supply_demand_score(data)
        # 50 + 10(기존 volume>2) + 10(volume_spike+price_rise) = 70
        assert result == 70

    def test_supply_demand_volume_spike_no_rise(self) -> None:
        """거래량 급증이지만 가격 하락 → 기존 +10만 적용."""
        data = {
            "volume_ratio": 2.5,
            "price_5d_trend": -3,
        }
        result = compute_supply_demand_score(data)
        # 50 + 10(기존 volume>2) + 0(spike but no rise) = 60
        assert result == 60
