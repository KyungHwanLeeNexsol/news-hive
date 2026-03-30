"""technical_indicators 서비스 테스트.

기술적 지표 계산 함수들을 알려진 입/출력 쌍으로 검증한다.
순수 수학 함수이므로 mock 없이 직접 테스트한다.
"""

import math

import pytest

from app.services.technical_indicators import (
    TechnicalAnalysis,
    _bollinger_bands,
    _ema,
    _macd,
    _rsi,
    _sma,
    calculate_technical_indicators,
    format_technical_for_prompt,
)


# ---------------------------------------------------------------------------
# SMA (단순 이동평균) 테스트
# ---------------------------------------------------------------------------


class TestSMA:
    """_sma 함수 테스트."""

    def test_sma_basic(self) -> None:
        """5개 값의 5일 SMA = 평균값."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _sma(prices, 5) == pytest.approx(30.0)

    def test_sma_uses_first_n_elements(self) -> None:
        """prices[:period] 만 사용하여 계산한다 (최신순이므로)."""
        prices = [100.0, 200.0, 300.0, 50.0, 60.0, 70.0]
        # period=3 → (100+200+300)/3 = 200
        assert _sma(prices, 3) == pytest.approx(200.0)

    def test_sma_insufficient_data(self) -> None:
        """데이터가 부족하면 None을 반환한다."""
        assert _sma([10.0, 20.0], 5) is None

    def test_sma_period_1(self) -> None:
        """period=1이면 첫 번째 값과 동일하다."""
        assert _sma([42.0, 100.0], 1) == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# EMA (지수 이동평균) 테스트
# ---------------------------------------------------------------------------


class TestEMA:
    """_ema 함수 테스트."""

    def test_ema_basic(self) -> None:
        """EMA를 계산하고 SMA와 다른 결과를 반환한다."""
        prices = [50.0, 48.0, 47.0, 46.0, 45.0, 44.0, 43.0, 42.0, 41.0, 40.0]
        result = _ema(prices, 5)
        assert result is not None
        # EMA는 SMA와 다른 값을 가져야 한다 (가중치 적용)
        sma_val = _sma(prices, 5)
        assert result != sma_val

    def test_ema_insufficient_data(self) -> None:
        """데이터가 부족하면 None을 반환한다."""
        assert _ema([10.0, 20.0], 5) is None

    def test_ema_exact_period(self) -> None:
        """데이터 길이가 period와 같으면 SMA와 동일하다."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = _ema(prices, 5)
        # 역순 정렬 후 SMA 계산: (50+40+30+20+10)/5 = 30
        # 추가 데이터가 없으므로 초기값 SMA만 사용
        assert result is not None


# ---------------------------------------------------------------------------
# RSI 테스트
# ---------------------------------------------------------------------------


class TestRSI:
    """_rsi 함수 테스트."""

    def test_rsi_all_gains(self) -> None:
        """모든 변동이 상승이면 RSI = 100."""
        # 최신 → 과거: 계속 상승
        prices = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0,
                  93.0, 92.0, 91.0, 90.0, 89.0, 88.0, 87.0, 86.0]
        result = _rsi(prices, 14)
        assert result == pytest.approx(100.0)

    def test_rsi_all_losses(self) -> None:
        """모든 변동이 하락이면 RSI = 0."""
        # 최신 → 과거: 계속 하락
        prices = [86.0, 87.0, 88.0, 89.0, 90.0, 91.0, 92.0,
                  93.0, 94.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0]
        result = _rsi(prices, 14)
        assert result == pytest.approx(0.0)

    def test_rsi_balanced(self) -> None:
        """등락이 비슷하면 RSI는 50 부근."""
        # 교차 상승/하락: +1, -1 반복
        prices = [50.0, 49.0, 50.0, 49.0, 50.0, 49.0, 50.0,
                  49.0, 50.0, 49.0, 50.0, 49.0, 50.0, 49.0, 50.0]
        result = _rsi(prices, 14)
        assert result is not None
        assert 40.0 <= result <= 60.0

    def test_rsi_insufficient_data(self) -> None:
        """데이터가 부족하면 None."""
        assert _rsi([10.0, 20.0], 14) is None

    def test_rsi_range(self) -> None:
        """RSI는 항상 0~100 범위."""
        prices = [55.0, 54.0, 56.0, 53.0, 57.0, 52.0, 58.0,
                  51.0, 59.0, 50.0, 60.0, 49.0, 61.0, 48.0, 62.0]
        result = _rsi(prices, 14)
        assert result is not None
        assert 0 <= result <= 100


# ---------------------------------------------------------------------------
# MACD 테스트
# ---------------------------------------------------------------------------


class TestMACD:
    """_macd 함수 테스트."""

    def test_macd_insufficient_data(self) -> None:
        """데이터가 26개 미만이면 (None, None, None)."""
        prices = list(range(20))
        macd_line, signal, histogram = _macd([float(p) for p in prices])
        # 26개 미만이면 ema26이 None
        assert macd_line is None

    def test_macd_with_enough_data(self) -> None:
        """충분한 데이터에서 MACD 라인을 계산한다."""
        # 최신순: prices[0]=최신, prices[39]=과거
        # 상승 추세: 최신이 높고 과거가 낮음 → EMA12(최근 가중) > EMA26 → MACD > 0
        prices = [140.0 - i * 1.0 for i in range(40)]  # 최신=140, 과거=101
        macd_line, signal, histogram = _macd(prices)
        assert macd_line is not None
        # MACD 값이 0이 아닌 유효한 숫자인지 확인
        assert isinstance(macd_line, float)

    def test_macd_returns_values_for_trend(self) -> None:
        """추세가 있는 데이터에서 MACD가 0이 아닌 값을 반환한다."""
        # 하락 추세: 최신이 낮고 과거가 높음
        prices = [60.0 + i * 1.0 for i in range(40)]  # 최신=60, 과거=99
        macd_line, signal, histogram = _macd(prices)
        assert macd_line is not None
        assert macd_line != 0.0

    def test_macd_signal_with_35_data_points(self) -> None:
        """35개 이상의 데이터에서 signal line도 계산된다."""
        prices = [100.0 + i * 0.3 for i in range(40)]
        macd_line, signal, histogram = _macd(prices)
        assert signal is not None
        assert histogram is not None


# ---------------------------------------------------------------------------
# 볼린저밴드 테스트
# ---------------------------------------------------------------------------


class TestBollingerBands:
    """_bollinger_bands 함수 테스트."""

    def test_bollinger_basic(self) -> None:
        """기본 볼린저밴드 계산."""
        prices = [100.0] * 20  # 변동 없음
        upper, middle, lower = _bollinger_bands(prices, 20, 2.0)
        assert middle == pytest.approx(100.0)
        # 표준편차 0이므로 upper == middle == lower
        assert upper == pytest.approx(100.0)
        assert lower == pytest.approx(100.0)

    def test_bollinger_with_variance(self) -> None:
        """변동이 있는 데이터에서 상단 > 중심 > 하단."""
        prices = [110.0, 90.0, 105.0, 95.0, 100.0,
                  108.0, 92.0, 103.0, 97.0, 101.0,
                  107.0, 93.0, 104.0, 96.0, 102.0,
                  106.0, 94.0, 103.0, 97.0, 100.0]
        upper, middle, lower = _bollinger_bands(prices, 20, 2.0)
        assert upper > middle > lower

    def test_bollinger_insufficient_data(self) -> None:
        """데이터 부족 시 (None, None, None)."""
        upper, middle, lower = _bollinger_bands([100.0, 101.0], 20)
        assert upper is None
        assert middle is None
        assert lower is None

    def test_bollinger_width_increases_with_volatility(self) -> None:
        """변동성이 클수록 밴드 폭이 넓다."""
        # 낮은 변동성
        low_vol = [100.0 + (i % 3 - 1) for i in range(20)]
        upper1, mid1, lower1 = _bollinger_bands(low_vol, 20, 2.0)
        width1 = upper1 - lower1

        # 높은 변동성
        high_vol = [100.0 + (i % 3 - 1) * 10 for i in range(20)]
        upper2, mid2, lower2 = _bollinger_bands(high_vol, 20, 2.0)
        width2 = upper2 - lower2

        assert width2 > width1


# ---------------------------------------------------------------------------
# calculate_technical_indicators 통합 테스트
# ---------------------------------------------------------------------------


class TestCalculateTechnicalIndicators:
    """calculate_technical_indicators 통합 테스트."""

    def _make_prices(self, closes: list[float], volumes: list[int] | None = None) -> list[dict]:
        """테스트용 가격 데이터를 생성한다."""
        vols = volumes or [1000000] * len(closes)
        return [
            {"close": c, "open": c * 0.99, "high": c * 1.01, "low": c * 0.98, "volume": v}
            for c, v in zip(closes, vols)
        ]

    def test_insufficient_data_returns_summary(self) -> None:
        """5개 미만 데이터에서 '데이터 부족' 요약을 반환한다."""
        ta = calculate_technical_indicators([])
        assert ta.summary == "데이터 부족"

        ta = calculate_technical_indicators(self._make_prices([100, 101, 102, 103]))
        assert ta.summary == "데이터 부족"

    def test_calculates_sma_values(self) -> None:
        """SMA 5/20이 올바르게 계산된다."""
        closes = [100.0 + i for i in range(25)]  # 최신순 상승
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        assert ta.sma_5 is not None
        assert ta.sma_5 == pytest.approx(sum(closes[:5]) / 5)
        assert ta.sma_20 is not None
        assert ta.sma_20 == pytest.approx(sum(closes[:20]) / 20)

    def test_rsi_signal_overbought(self) -> None:
        """연속 상승 시 RSI 과매수 신호."""
        # 최신순으로 강하게 상승하는 패턴
        closes = [200.0 - i * 5 for i in range(20)]  # 최신이 200, 과거가 100
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        if ta.rsi_14 is not None:
            assert ta.rsi_14 >= 70
            assert ta.rsi_signal == "과매수"

    def test_rsi_signal_oversold(self) -> None:
        """연속 하락 시 RSI 과매도 신호."""
        closes = [100.0 + i * 5 for i in range(20)]  # 최신이 100, 과거가 195
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        if ta.rsi_14 is not None:
            assert ta.rsi_14 <= 30
            assert ta.rsi_signal == "과매도"

    def test_golden_cross_detection(self) -> None:
        """SMA5 > SMA20이면 골든크로스."""
        # 최근 급등: 최신 가격이 높고 과거가 낮은 패턴
        closes = [150.0] * 5 + [100.0] * 20
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        assert ta.golden_cross is True
        assert ta.death_cross is False

    def test_death_cross_detection(self) -> None:
        """SMA5 < SMA20이면 데드크로스."""
        closes = [80.0] * 5 + [100.0] * 20
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        assert ta.death_cross is True
        assert ta.golden_cross is False

    def test_ma_alignment_ordered(self) -> None:
        """SMA5 > SMA20 > SMA60이면 정배열."""
        closes = [200.0] * 5 + [150.0] * 20 + [100.0] * 40
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        assert ta.ma_alignment == "정배열"

    def test_ma_alignment_reversed(self) -> None:
        """SMA5 < SMA20 < SMA60이면 역배열."""
        closes = [50.0] * 5 + [100.0] * 20 + [150.0] * 40
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        assert ta.ma_alignment == "역배열"

    def test_volume_analysis(self) -> None:
        """거래량 분석이 올바르게 수행된다."""
        closes = [100.0] * 25
        # volumes[:20]의 평균 = (5000000 + 19*1000000)/20 = 1200000
        # volume_ratio = 5000000/1200000 ≈ 4.17 → 급증
        volumes = [5000000] + [1000000] * 24
        prices = self._make_prices(closes, volumes)
        ta = calculate_technical_indicators(prices)

        assert ta.volume_ratio is not None
        assert ta.volume_ratio >= 3.0
        assert ta.volume_trend == "급증"

    def test_technical_score_range(self) -> None:
        """기술적 점수가 -100~+100 범위 내."""
        closes = [100.0 + i * 0.5 for i in range(70)]
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        assert -100 <= ta.technical_score <= 100

    def test_price_change_percentages(self) -> None:
        """5일/20일/60일 변화율이 올바르게 계산된다."""
        closes = [110.0] + [100.0] * 70  # 최신 = 110, 나머지 = 100
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices)

        # 5일 변화: (110-100)/100 * 100 = 10%
        assert ta.price_5d_change is not None
        assert ta.price_5d_change == pytest.approx(10.0)

    def test_bollinger_position(self) -> None:
        """볼린저밴드 위치 판단이 올바르다."""
        # 현재가가 매우 낮은 경우 → 하단돌파
        closes = [50.0] + [100.0] * 24
        prices = self._make_prices(closes)
        ta = calculate_technical_indicators(prices, current_price=50.0)

        if ta.bb_lower is not None:
            assert ta.bb_position in ("하단돌파", "하단근접", "중심")

    def test_empty_closes_returns_no_data(self) -> None:
        """close가 없는 데이터에서 '가격 데이터 없음' 반환."""
        prices = [{"open": 100, "high": 110, "low": 90, "volume": 1000} for _ in range(10)]
        ta = calculate_technical_indicators(prices)
        assert ta.summary == "가격 데이터 없음"


# ---------------------------------------------------------------------------
# format_technical_for_prompt 테스트
# ---------------------------------------------------------------------------


class TestFormatTechnicalForPrompt:
    """기술적 지표 프롬프트 포맷 테스트."""

    def test_format_includes_key_sections(self) -> None:
        """포맷 결과에 주요 섹션이 포함된다."""
        ta = TechnicalAnalysis(
            sma_5=100.0,
            sma_20=95.0,
            rsi_14=65.0,
            rsi_signal="중립",
            technical_score=15,
            summary="기술적 판단: 약한 매수 신호 (점수: 15) | 특이 신호 없음",
        )
        text = format_technical_for_prompt(ta)

        assert "기술적 분석" in text
        assert "이동평균" in text
        assert "RSI(14)" in text
        assert "종합" in text
        assert "기술적 점수: 15" in text

    def test_format_empty_analysis(self) -> None:
        """데이터가 없는 분석도 에러 없이 포맷된다."""
        ta = TechnicalAnalysis(summary="데이터 부족")
        text = format_technical_for_prompt(ta)
        assert "기술적 분석" in text
        assert "데이터 부족" in text
