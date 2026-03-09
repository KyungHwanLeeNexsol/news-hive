"""기술적 지표 계산 모듈.

주가 히스토리 데이터로부터 SMA, EMA, RSI, MACD, 볼린저밴드,
볼륨 분석 등을 계산한다.
"""

import math
from dataclasses import dataclass, field


@dataclass
class TechnicalAnalysis:
    """기술적 지표 분석 결과."""
    # 이동평균선
    sma_5: float | None = None
    sma_20: float | None = None
    sma_60: float | None = None
    sma_120: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None

    # 이동평균 크로스 상태
    golden_cross: bool = False  # 단기 > 장기 (매수 신호)
    death_cross: bool = False   # 단기 < 장기 (매도 신호)
    ma_alignment: str = ""      # "정배열" / "역배열" / "혼조"

    # RSI
    rsi_14: float | None = None
    rsi_signal: str = ""  # "과매수" / "과매도" / "중립"

    # MACD
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    macd_cross: str = ""  # "골든크로스" / "데드크로스" / "없음"

    # 볼린저밴드
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_position: str = ""  # "상단돌파" / "상단근접" / "중심" / "하단근접" / "하단돌파"
    bb_width: float | None = None  # 밴드 폭 (변동성 척도)

    # 볼륨 분석
    volume_ratio: float | None = None  # 현재 거래량 / 20일 평균
    volume_trend: str = ""  # "급증" / "증가" / "보통" / "감소"
    obv_trend: str = ""     # "상승" / "하락" / "보합" (OBV 5일 추세)

    # 추세 강도
    price_5d_change: float | None = None
    price_20d_change: float | None = None
    price_60d_change: float | None = None
    volatility: float | None = None

    # 종합 판단
    technical_score: int = 0  # -100 ~ +100
    summary: str = ""


def _sma(prices: list[float], period: int) -> float | None:
    """단순 이동평균."""
    if len(prices) < period:
        return None
    return sum(prices[:period]) / period


def _ema(prices: list[float], period: int) -> float | None:
    """지수 이동평균. prices는 최신순."""
    if len(prices) < period:
        return None
    # 역순으로 (과거 → 최신)
    rev = list(reversed(prices[:period * 2] if len(prices) >= period * 2 else prices))
    multiplier = 2.0 / (period + 1)
    ema_val = sum(rev[:period]) / period  # 초기값 = SMA
    for price in rev[period:]:
        ema_val = (price - ema_val) * multiplier + ema_val
    return ema_val


def _rsi(prices: list[float], period: int = 14) -> float | None:
    """RSI (Relative Strength Index). prices는 최신순."""
    if len(prices) < period + 1:
        return None
    gains = []
    losses = []
    # prices[0]=최신, prices[1]=하루전 ...
    for i in range(period):
        change = prices[i] - prices[i + 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(prices: list[float]) -> tuple[float | None, float | None, float | None]:
    """MACD (12,26,9). Returns (macd_line, signal_line, histogram)."""
    ema12 = _ema(prices, 12)
    ema26 = _ema(prices, 26)
    if ema12 is None or ema26 is None:
        return None, None, None

    macd_line = ema12 - ema26

    # Signal line = 9-period EMA of MACD values
    # 간략화: 현재 MACD 값을 기준으로 추정
    # 정확한 계산을 위해서는 과거 MACD 시리즈가 필요하지만,
    # 단일 시점에서는 MACD 라인으로 방향성만 판단
    # 여러 시점의 MACD를 계산하여 signal 산출
    if len(prices) < 35:
        return macd_line, None, None

    macd_values = []
    for offset in range(9):
        shifted = prices[offset:]
        e12 = _ema(shifted, 12)
        e26 = _ema(shifted, 26)
        if e12 is not None and e26 is not None:
            macd_values.append(e12 - e26)

    if len(macd_values) < 9:
        return macd_line, None, None

    signal_line = sum(macd_values) / len(macd_values)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def _bollinger_bands(prices: list[float], period: int = 20, std_dev: float = 2.0
                     ) -> tuple[float | None, float | None, float | None]:
    """볼린저밴드 (상단, 중심, 하단)."""
    if len(prices) < period:
        return None, None, None

    middle = sum(prices[:period]) / period
    variance = sum((p - middle) ** 2 for p in prices[:period]) / period
    std = math.sqrt(variance)

    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def calculate_technical_indicators(
    prices: list[dict],
    current_price: float | None = None,
) -> TechnicalAnalysis:
    """주가 히스토리로부터 기술적 지표를 계산한다.

    Args:
        prices: [{close, open, high, low, volume, date}, ...] 최신순
        current_price: 현재가 (없으면 prices[0].close 사용)

    Returns:
        TechnicalAnalysis 결과
    """
    ta = TechnicalAnalysis()

    if not prices or len(prices) < 5:
        ta.summary = "데이터 부족"
        return ta

    closes = [p["close"] for p in prices if p.get("close")]
    volumes = [p["volume"] for p in prices if p.get("volume")]

    if not closes:
        ta.summary = "가격 데이터 없음"
        return ta

    price = current_price or closes[0]

    # ── 이동평균선 ──
    ta.sma_5 = _sma(closes, 5)
    ta.sma_20 = _sma(closes, 20)
    ta.sma_60 = _sma(closes, 60)
    ta.sma_120 = _sma(closes, 120)
    ta.ema_12 = _ema(closes, 12)
    ta.ema_26 = _ema(closes, 26)

    # 이동평균 크로스
    if ta.sma_5 and ta.sma_20:
        if ta.sma_5 > ta.sma_20:
            ta.golden_cross = True
        else:
            ta.death_cross = True

    # 이동평균 배열
    mas = [v for v in [ta.sma_5, ta.sma_20, ta.sma_60] if v is not None]
    if len(mas) >= 3:
        if mas[0] > mas[1] > mas[2]:
            ta.ma_alignment = "정배열"
        elif mas[0] < mas[1] < mas[2]:
            ta.ma_alignment = "역배열"
        else:
            ta.ma_alignment = "혼조"

    # ── RSI ──
    ta.rsi_14 = _rsi(closes, 14)
    if ta.rsi_14 is not None:
        if ta.rsi_14 >= 70:
            ta.rsi_signal = "과매수"
        elif ta.rsi_14 <= 30:
            ta.rsi_signal = "과매도"
        else:
            ta.rsi_signal = "중립"

    # ── MACD ──
    ta.macd_line, ta.macd_signal, ta.macd_histogram = _macd(closes)
    if ta.macd_histogram is not None:
        if ta.macd_histogram > 0 and ta.macd_line and ta.macd_line > 0:
            ta.macd_cross = "골든크로스"
        elif ta.macd_histogram < 0 and ta.macd_line and ta.macd_line < 0:
            ta.macd_cross = "데드크로스"
        else:
            ta.macd_cross = "없음"

    # ── 볼린저밴드 ──
    ta.bb_upper, ta.bb_middle, ta.bb_lower = _bollinger_bands(closes)
    if ta.bb_upper and ta.bb_lower:
        ta.bb_width = (ta.bb_upper - ta.bb_lower) / ta.bb_middle * 100 if ta.bb_middle else None
        if price > ta.bb_upper:
            ta.bb_position = "상단돌파"
        elif price > ta.bb_upper * 0.98:
            ta.bb_position = "상단근접"
        elif price < ta.bb_lower:
            ta.bb_position = "하단돌파"
        elif price < ta.bb_lower * 1.02:
            ta.bb_position = "하단근접"
        else:
            ta.bb_position = "중심"

    # ── 볼륨 분석 ──
    if volumes and len(volumes) >= 20:
        avg_vol_20 = sum(volumes[:20]) / 20
        if avg_vol_20 > 0:
            ta.volume_ratio = volumes[0] / avg_vol_20
            if ta.volume_ratio >= 3.0:
                ta.volume_trend = "급증"
            elif ta.volume_ratio >= 1.5:
                ta.volume_trend = "증가"
            elif ta.volume_ratio >= 0.7:
                ta.volume_trend = "보통"
            else:
                ta.volume_trend = "감소"

    # OBV 추세 (5일)
    if len(closes) >= 6 and len(volumes) >= 6:
        obv_changes = []
        for i in range(5):
            if closes[i] > closes[i + 1]:
                obv_changes.append(volumes[i])
            elif closes[i] < closes[i + 1]:
                obv_changes.append(-volumes[i])
            else:
                obv_changes.append(0)
        obv_sum = sum(obv_changes)
        if obv_sum > 0:
            ta.obv_trend = "상승"
        elif obv_sum < 0:
            ta.obv_trend = "하락"
        else:
            ta.obv_trend = "보합"

    # ── 추세 변화율 ──
    if len(closes) >= 6:
        ta.price_5d_change = (closes[0] - closes[5]) / closes[5] * 100
    if len(closes) >= 21:
        ta.price_20d_change = (closes[0] - closes[20]) / closes[20] * 100
    if len(closes) >= 61:
        ta.price_60d_change = (closes[0] - closes[60]) / closes[60] * 100

    # 변동성
    if len(closes) >= 11:
        returns = [(closes[i] - closes[i + 1]) / closes[i + 1] for i in range(min(20, len(closes) - 1))]
        avg_ret = sum(returns) / len(returns)
        variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
        ta.volatility = math.sqrt(variance) * 100

    # ── 종합 점수 (-100 ~ +100) ──
    score = 0
    signals = []

    # RSI 점수
    if ta.rsi_14 is not None:
        if ta.rsi_14 <= 30:
            score += 20
            signals.append("RSI 과매도 (매수 기회)")
        elif ta.rsi_14 <= 40:
            score += 10
        elif ta.rsi_14 >= 70:
            score -= 20
            signals.append("RSI 과매수 (과열 주의)")
        elif ta.rsi_14 >= 60:
            score -= 5

    # 이동평균 점수
    if ta.ma_alignment == "정배열":
        score += 15
        signals.append("이동평균 정배열 (상승 추세)")
    elif ta.ma_alignment == "역배열":
        score -= 15
        signals.append("이동평균 역배열 (하락 추세)")

    if ta.golden_cross:
        score += 10
    elif ta.death_cross:
        score -= 10

    # 현재가 vs 이동평균
    if ta.sma_20:
        if price > ta.sma_20 * 1.05:
            score += 5
        elif price < ta.sma_20 * 0.95:
            score -= 5

    # MACD 점수
    if ta.macd_cross == "골든크로스":
        score += 15
        signals.append("MACD 골든크로스 (매수 신호)")
    elif ta.macd_cross == "데드크로스":
        score -= 15
        signals.append("MACD 데드크로스 (매도 신호)")

    # 볼린저밴드 점수
    if ta.bb_position == "하단돌파":
        score += 10
        signals.append("볼린저 하단 돌파 (반등 가능)")
    elif ta.bb_position == "하단근접":
        score += 5
    elif ta.bb_position == "상단돌파":
        score -= 10
        signals.append("볼린저 상단 돌파 (조정 가능)")
    elif ta.bb_position == "상단근접":
        score -= 5

    # 거래량 점수
    if ta.volume_trend == "급증" and ta.price_5d_change and ta.price_5d_change > 0:
        score += 10
        signals.append("거래량 급증 + 상승 (강한 매수세)")
    elif ta.volume_trend == "급증" and ta.price_5d_change and ta.price_5d_change < 0:
        score -= 10
        signals.append("거래량 급증 + 하락 (투매 우려)")

    # OBV
    if ta.obv_trend == "상승":
        score += 5
    elif ta.obv_trend == "하락":
        score -= 5

    # 점수 클램핑
    ta.technical_score = max(-100, min(100, score))

    # 종합 요약
    if ta.technical_score >= 30:
        outlook = "강한 매수 신호"
    elif ta.technical_score >= 10:
        outlook = "약한 매수 신호"
    elif ta.technical_score <= -30:
        outlook = "강한 매도 신호"
    elif ta.technical_score <= -10:
        outlook = "약한 매도 신호"
    else:
        outlook = "중립"

    signal_text = " / ".join(signals[:3]) if signals else "특이 신호 없음"
    ta.summary = f"기술적 판단: {outlook} (점수: {ta.technical_score}) | {signal_text}"

    return ta


def format_technical_for_prompt(ta: TechnicalAnalysis, current_price: float | None = None) -> str:
    """AI 프롬프트에 포함할 기술적 지표 텍스트를 생성한다."""
    lines = []
    lines.append("## 기술적 분석")

    # 이동평균
    ma_parts = []
    if ta.sma_5:
        ma_parts.append(f"5일={ta.sma_5:,.0f}")
    if ta.sma_20:
        ma_parts.append(f"20일={ta.sma_20:,.0f}")
    if ta.sma_60:
        ma_parts.append(f"60일={ta.sma_60:,.0f}")
    if ta.sma_120:
        ma_parts.append(f"120일={ta.sma_120:,.0f}")
    if ma_parts:
        lines.append(f"이동평균: {', '.join(ma_parts)}")
        if ta.ma_alignment:
            lines.append(f"배열: {ta.ma_alignment}")

    # RSI
    if ta.rsi_14 is not None:
        lines.append(f"RSI(14): {ta.rsi_14:.1f} ({ta.rsi_signal})")

    # MACD
    if ta.macd_line is not None:
        macd_text = f"MACD: {ta.macd_line:,.0f}"
        if ta.macd_signal is not None:
            macd_text += f", Signal: {ta.macd_signal:,.0f}"
        if ta.macd_histogram is not None:
            macd_text += f", Hist: {ta.macd_histogram:,.0f}"
        if ta.macd_cross != "없음":
            macd_text += f" ({ta.macd_cross})"
        lines.append(macd_text)

    # 볼린저밴드
    if ta.bb_upper is not None:
        lines.append(
            f"볼린저밴드: 상단={ta.bb_upper:,.0f}, 중심={ta.bb_middle:,.0f}, 하단={ta.bb_lower:,.0f} "
            f"(현재 위치: {ta.bb_position})"
        )
        if ta.bb_width is not None:
            lines.append(f"밴드폭: {ta.bb_width:.1f}%")

    # 거래량
    if ta.volume_ratio is not None:
        lines.append(f"거래량비율: {ta.volume_ratio:.2f}x (20일 평균 대비, {ta.volume_trend})")
    if ta.obv_trend:
        lines.append(f"OBV 추세(5일): {ta.obv_trend}")

    # 변동성
    if ta.volatility is not None:
        lines.append(f"변동성: {ta.volatility:.2f}%")

    # 추세
    trends = []
    if ta.price_5d_change is not None:
        trends.append(f"5일: {ta.price_5d_change:+.2f}%")
    if ta.price_20d_change is not None:
        trends.append(f"20일: {ta.price_20d_change:+.2f}%")
    if ta.price_60d_change is not None:
        trends.append(f"60일: {ta.price_60d_change:+.2f}%")
    if trends:
        lines.append(f"수익률: {', '.join(trends)}")

    # 종합
    lines.append(f"\n종합: {ta.summary}")
    lines.append(f"기술적 점수: {ta.technical_score} (-100~+100, 양수=매수신호, 음수=매도신호)")

    return "\n".join(lines)
