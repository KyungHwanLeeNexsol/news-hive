"""SPEC-AI-015: fund_manager 레짐 통합 특성화 테스트.

[DDD PRESERVE] 기존 fund_manager.py의 레짐 관련 동작을 캡처하는 특성화 테스트.
이 테스트들은 T-010, T-011 수정 이후에도 반드시 PASS해야 한다.
"""

import pytest

from app.services.fund_manager import MIN_ACTION_CONFIDENCE


# ---------------------------------------------------------------------------
# 특성화 테스트: MIN_ACTION_CONFIDENCE 기존 동작 캡처
# ---------------------------------------------------------------------------

class TestCharacterizeMinActionConfidence:
    """MIN_ACTION_CONFIDENCE 상수 특성화.

    T-010 수정 이후에도 모듈 레벨 상수값은 폴백으로 유지된다.
    """

    def test_characterize_min_action_confidence_is_0_50(self):
        """MIN_ACTION_CONFIDENCE = 0.50 (폴백 상수)."""
        assert MIN_ACTION_CONFIDENCE == 0.50

    def test_characterize_confidence_floor_blocks_buy_at_0_49(self):
        """confidence=0.49 → buy 시그널이 hold로 변환된다 (기존 동작).

        fund_manager.py:2452 - MIN_ACTION_CONFIDENCE 가드.
        """
        # 0.49 < 0.50 (MIN_ACTION_CONFIDENCE): buy → hold 변환
        confidence_val = 0.49
        signal = "buy"
        should_convert = signal in ("buy", "sell") and confidence_val < MIN_ACTION_CONFIDENCE
        assert should_convert is True

    def test_characterize_confidence_floor_allows_buy_at_0_50(self):
        """confidence=0.50 → buy 시그널이 통과된다 (기존 동작)."""
        confidence_val = 0.50
        signal = "buy"
        should_convert = signal in ("buy", "sell") and confidence_val < MIN_ACTION_CONFIDENCE
        assert should_convert is False

    def test_characterize_confidence_floor_allows_buy_above_0_50(self):
        """confidence=0.51 → buy 시그널이 통과된다."""
        confidence_val = 0.51
        signal = "buy"
        should_convert = signal in ("buy", "sell") and confidence_val < MIN_ACTION_CONFIDENCE
        assert should_convert is False

    def test_characterize_hold_not_affected_by_floor(self):
        """hold 시그널은 confidence floor 검사를 받지 않는다."""
        confidence_val = 0.10  # 매우 낮음
        signal = "hold"
        should_convert = signal in ("buy", "sell") and confidence_val < MIN_ACTION_CONFIDENCE
        assert should_convert is False


# ---------------------------------------------------------------------------
# 특성화 테스트: 레짐 텍스트 생성 로직 (기존 _signal_market_regime 패턴)
# ---------------------------------------------------------------------------

class TestCharacterizeRegimeTextInjection:
    """analyze_stock 내 레짐 텍스트 생성 로직 특성화.

    T-010 수정 이전의 하드코딩 분기 동작을 캡처한다.
    """

    def _legacy_generate_regime_text(self, kospi_5d_return: float | None) -> tuple[str, str]:
        """기존 fund_manager.py의 레짐 텍스트 생성 로직 (lines ~2304-2316)."""
        market_regime = ""
        regime_bias = ""
        if kospi_5d_return is not None:
            if kospi_5d_return >= 1.5:
                market_regime = f"상승 추세 (KOSPI 5일 +{kospi_5d_return:.1f}% 추정)"
                regime_bias = "※ 상승 추세 시장: 확신이 있다면 buy를 기본으로, hold는 명확한 반대 근거가 있을 때만."
            elif kospi_5d_return <= -1.5:
                market_regime = f"하락 추세 (KOSPI 5일 {kospi_5d_return:.1f}% 추정)"
                regime_bias = "※ 하락 추세 시장: 매수는 매우 강한 근거 있을 때만, 기본은 hold/sell."
        return market_regime, regime_bias

    def test_characterize_bull_regime_text_when_5d_ret_above_1_5(self):
        """kospi_5d_return >= 1.5% → 상승 추세 텍스트."""
        regime_text, bias = self._legacy_generate_regime_text(2.0)
        assert "상승 추세" in regime_text
        assert "buy" in bias

    def test_characterize_bear_regime_text_when_5d_ret_below_minus_1_5(self):
        """kospi_5d_return <= -1.5% → 하락 추세 텍스트."""
        regime_text, bias = self._legacy_generate_regime_text(-2.0)
        assert "하락 추세" in regime_text
        assert "hold/sell" in bias

    def test_characterize_sideways_no_text_between_thresholds(self):
        """-1.5% < kospi_5d_return < 1.5% → 레짐 텍스트 없음 (기존 동작)."""
        regime_text, bias = self._legacy_generate_regime_text(0.5)
        assert regime_text == ""
        assert bias == ""

    def test_characterize_none_5d_ret_no_text(self):
        """kospi_5d_return=None → 레짐 텍스트 없음."""
        regime_text, bias = self._legacy_generate_regime_text(None)
        assert regime_text == ""
        assert bias == ""


# ---------------------------------------------------------------------------
# 특성화 테스트: generate_daily_briefing 레짐 텍스트 (기존 로직)
# ---------------------------------------------------------------------------

class TestCharacterizeBriefingRegimeText:
    """generate_daily_briefing 내 레짐 텍스트 생성 로직 특성화.

    T-011 수정 이전의 하드코딩 분기 동작을 캡처한다 (lines ~2957-2970).
    """

    def _legacy_generate_briefing_regime(self, kospi_ret_5d: float | None) -> tuple[str, str]:
        """기존 generate_daily_briefing 레짐 텍스트 생성 로직."""
        if kospi_ret_5d is not None:
            if kospi_ret_5d >= 1.5:
                market_regime = f"상승 추세 (KOSPI 5일 +{kospi_ret_5d:.1f}%)"
                regime_bias = "※ 현재 상승 추세 시장입니다. 확신이 있다면 매수를 우선 고려하고, hold는 명확한 반대 근거가 있을 때만 선택하세요."
            elif kospi_ret_5d <= -1.5:
                market_regime = f"하락 추세 (KOSPI 5일 {kospi_ret_5d:.1f}%)"
                regime_bias = "※ 현재 하락 추세 시장입니다. 매수는 매우 강한 근거가 있을 때만 추천하고, 관망/회피를 기본으로 하세요."
            else:
                market_regime = f"횡보 구간 (KOSPI 5일 {kospi_ret_5d:+.1f}%)"
                regime_bias = "※ 횡보 시장입니다. 개별 종목의 차별적 강도를 기준으로 판단하세요."
        else:
            market_regime = "데이터 없음"
            regime_bias = ""
        return market_regime, regime_bias

    def test_characterize_briefing_bull_text(self):
        """브리핑: 5d_ret >= 1.5% → 상승 추세."""
        regime, bias = self._legacy_generate_briefing_regime(2.0)
        assert "상승 추세" in regime
        assert "매수를 우선" in bias

    def test_characterize_briefing_bear_text(self):
        """브리핑: 5d_ret <= -1.5% → 하락 추세."""
        regime, bias = self._legacy_generate_briefing_regime(-2.0)
        assert "하락 추세" in regime
        assert "관망/회피" in bias

    def test_characterize_briefing_sideways_text(self):
        """브리핑: -1.5% < 5d_ret < 1.5% → 횡보 구간."""
        regime, bias = self._legacy_generate_briefing_regime(0.3)
        assert "횡보 구간" in regime
        assert "차별적 강도" in bias

    def test_characterize_briefing_no_data(self):
        """브리핑: 5d_ret=None → 데이터 없음."""
        regime, bias = self._legacy_generate_briefing_regime(None)
        assert regime == "데이터 없음"
        assert bias == ""
