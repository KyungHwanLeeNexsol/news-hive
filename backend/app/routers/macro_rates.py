"""매크로 지표 라우터 — 환율 및 기준금리 데이터 제공."""

import logging
import time
from datetime import date, datetime, timezone

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["macro"])

# 인메모리 캐시: (timestamp, data)
_rates_cache: tuple[float, dict] | None = None
_CACHE_TTL = 600  # 10분

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
    """yfinance로 환율 조회. 실패 시 빈 리스트 반환."""
    try:
        import yfinance as yf

        # USD/KRW, JPY/KRW, EUR/KRW 조회
        symbols = ["USDKRW=X", "JPYKRW=X", "EURKRW=X"]
        tickers = yf.Tickers(" ".join(symbols))

        results = []
        labels = [
            ("USDKRW=X", "USD/KRW", "달러"),
            ("JPYKRW=X", "JPY/KRW", "엔화"),
            ("EURKRW=X", "EUR/KRW", "유로"),
        ]

        for symbol, pair, label in labels:
            try:
                ticker = tickers.tickers[symbol]
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)

                if price is None:
                    # fast_info 실패 시 history 폴백
                    hist = ticker.history(period="2d")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])
                        if len(hist) >= 2:
                            prev_close = float(hist["Close"].iloc[-2])

                if price is None:
                    continue

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
    }


@router.get("/rates")
def get_macro_rates() -> dict:
    """환율 및 기준금리 데이터 반환 (10분 캐시)."""
    global _rates_cache
    now = time.time()

    if _rates_cache is not None:
        cached_at, cached_data = _rates_cache
        if now - cached_at < _CACHE_TTL:
            return cached_data

    data = _build_rates_data()
    _rates_cache = (now, data)
    return data
