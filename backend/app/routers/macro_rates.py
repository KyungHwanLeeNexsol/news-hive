"""매크로 지표 라우터 — 환율 및 기준금리 데이터 제공."""

import logging
import time
from datetime import date, datetime, timezone

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["macro"])

# 인메모리 캐시: (timestamp, data)
_rates_cache: tuple[float, dict] | None = None
# 자동 갱신 캐시: 3분 (yfinance 자체가 ~15분 지연이므로 너무 자주 호출할 필요 없음)
_CACHE_TTL = 180  # 3분

# ---------------------------------------------------------------------------
# 기준금리 및 회의 일정 설정 (수동 업데이트)
# ---------------------------------------------------------------------------

# 각국 기준금리 현황 및 2026년 금리 결정 회의 일정
INTEREST_RATE_CONFIG = {
    "US": {
        "country": "미국",
        "central_bank": "연준(Fed)",
        "rate": 4.25,  # 현재 기준금리 (%)
        "rate_label": "4.25~4.50%",
        "meetings": [
            "2026-01-29",
            "2026-03-19",
            "2026-05-07",
            "2026-06-18",
            "2026-07-30",
            "2026-09-17",
            "2026-10-29",
            "2026-12-11",
        ],
    },
    "JP": {
        "country": "일본",
        "central_bank": "일본은행(BOJ)",
        "rate": 0.5,
        "rate_label": "0.50%",
        "meetings": [
            "2026-01-24",
            "2026-03-19",
            "2026-04-30",
            "2026-06-17",
            "2026-07-31",
            "2026-09-19",
            "2026-10-29",
            "2026-12-19",
        ],
    },
    "KR": {
        "country": "한국",
        "central_bank": "한국은행(BOK)",
        "rate": 2.75,
        "rate_label": "2.75%",
        "meetings": [
            "2026-01-16",
            "2026-02-26",
            "2026-04-17",
            "2026-05-29",
            "2026-07-10",
            "2026-08-28",
            "2026-10-16",
            "2026-11-27",
        ],
    },
}


def _calc_dday(meeting_dates: list[str]) -> tuple[str | None, int | None]:
    """오늘 기준으로 가장 가까운 미래 회의 날짜와 D-DAY를 반환."""
    today = date.today()
    for date_str in sorted(meeting_dates):
        meeting = date.fromisoformat(date_str)
        delta = (meeting - today).days
        if delta >= 0:
            return date_str, delta
    # 모든 일정이 지났으면 마지막 일정 반환
    if meeting_dates:
        last = sorted(meeting_dates)[-1]
        delta = (date.fromisoformat(last) - today).days
        return last, delta
    return None, None


def _fetch_exchange_rates() -> list[dict]:
    """yfinance로 환율 조회 (인트라데이 우선, 일봉 폴백).

    Yahoo Finance 환율 데이터는 약 15분 지연됩니다.
    1차: 당일 1분봉 (가장 최신 장중 데이터)
    2차: 5일 일봉 폴백 (최근 거래일 종가)
    """
    try:
        import yfinance as yf

        labels = [
            ("USDKRW=X", "USD/KRW", "달러"),
            ("JPYKRW=X", "JPY/KRW", "엔화"),
            ("EURKRW=X", "EUR/KRW", "유로"),
        ]

        results = []
        for symbol, pair, label in labels:
            try:
                price: float | None = None
                prev_close: float | None = None

                # 1차: 당일 1분봉 — 장 중 15분 지연 실시간
                data = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
                if not data.empty:
                    close_col = data["Close"]
                    valid = close_col.dropna()
                    if not valid.empty:
                        price = float(valid.iloc[-1])

                # 2차: 5일 일봉 폴백 — 최근 거래일 종가 + 전일 종가
                if price is None:
                    data = yf.download(symbol, period="5d", progress=False, auto_adjust=True)
                    if not data.empty:
                        close_col = data["Close"]
                        valid = close_col.dropna()
                        if len(valid) >= 2:
                            price = float(valid.iloc[-1])
                            prev_close = float(valid.iloc[-2])
                        elif len(valid) == 1:
                            price = float(valid.iloc[-1])

                if price is None:
                    logger.warning(f"환율 조회 실패 — 데이터 없음 ({symbol})")
                    continue

                # 전일 종가로 변동률 계산 (인트라데이 시에는 daily 데이터로 보정)
                if prev_close is None:
                    daily = yf.download(symbol, period="5d", progress=False, auto_adjust=True)
                    if not daily.empty:
                        valid_daily = daily["Close"].dropna()
                        if len(valid_daily) >= 2:
                            prev_close = float(valid_daily.iloc[-2])

                change_pct = None
                if prev_close and prev_close != 0:
                    change_pct = round((price - prev_close) / prev_close * 100, 2)

                results.append(
                    {
                        "pair": pair,
                        "label": label,
                        "rate": round(price, 2),
                        "change_pct": change_pct,
                    }
                )
            except Exception as e:
                logger.warning(f"환율 조회 실패 ({symbol}): {e}")

        return results
    except Exception as e:
        logger.warning(f"yfinance 환율 조회 전체 실패: {e}")
        return []


def _build_rates_data() -> dict:
    """환율 + 기준금리 데이터 빌드."""
    exchange_rates = _fetch_exchange_rates()

    interest_rates = []
    for code, cfg in INTEREST_RATE_CONFIG.items():
        next_meeting, dday = _calc_dday(cfg["meetings"])
        interest_rates.append(
            {
                "country": cfg["country"],
                "code": code,
                "central_bank": cfg["central_bank"],
                "rate": cfg["rate"],
                "rate_label": cfg["rate_label"],
                "next_meeting": next_meeting,
                "dday": dday,
            }
        )

    return {
        "exchange_rates": exchange_rates,
        "interest_rates": interest_rates,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        # Yahoo Finance 환율은 약 15분 지연 제공
        "data_delay_minutes": 15,
    }


@router.get("/rates")
def get_macro_rates(force: bool = Query(default=False, description="캐시 무시 후 강제 갱신")) -> dict:
    """환율 및 기준금리 데이터 반환.

    - 자동 갱신: 3분 캐시
    - force=true: 캐시 무시 후 즉시 조회 (사용자 새로고침 버튼)
    """
    global _rates_cache
    now = time.time()

    # force=False이고 캐시가 유효한 경우 캐시 반환
    if not force and _rates_cache is not None:
        cached_at, cached_data = _rates_cache
        if now - cached_at < _CACHE_TTL:
            return cached_data

    data = _build_rates_data()
    _rates_cache = (now, data)
    return data
