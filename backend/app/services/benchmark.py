"""KOSPI 벤치마크 기반 알파 계산 헬퍼.

승률만 보고 전략 품질을 오판하던 문제 교정을 위해 도입 (2026-04).
포트폴리오 스냅샷과 시그널 검증 시 같은 기간 KOSPI 수익률과의 차이(알파)를 산정한다.

# @MX:NOTE: 네이버 KOSPI 일별 시세를 fetch_index_price_history로 가져와 30분 TTL 캐시
# @MX:ANCHOR: paper_trading.take_daily_snapshot, signal_verifier.verify_signals 에서 사용
# @MX:REASON: 절대 수익률은 상승장에서 모든 전략이 잘 맞춘 것처럼 보이는 착시 발생 → 시장중립 알파 필요
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 1800  # 30분
_cache: dict[str, tuple[dict[date, float], float]] = {}


async def _load_kospi_closes(pages: int = 10) -> dict[date, float]:
    """KOSPI 일별 종가를 {date: close} 형식으로 로드. 30분 메모리 캐시.

    pages=10 → 약 100거래일(네이버 페이지당 10일). 포트폴리오 운영 기간이
    길어지면 호출부에서 pages를 늘린다.
    """
    cache_key = f"kospi:{pages}"
    now = time.monotonic()

    cached = _cache.get(cache_key)
    if cached is not None:
        data, cached_at = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return data

    from app.services.naver_finance import fetch_index_price_history

    try:
        rows = await fetch_index_price_history("KOSPI", pages=pages)
    except Exception as exc:  # pragma: no cover - network failure path
        logger.warning("KOSPI 일별 시세 조회 실패: %s", exc)
        return {}

    closes: dict[date, float] = {}
    for row in rows:
        date_text = row.get("date", "")
        close = row.get("close")
        if not date_text or close is None:
            continue
        try:
            d = datetime.strptime(date_text, "%Y.%m.%d").date()
        except ValueError:
            continue
        closes[d] = float(close)

    if closes:
        _cache[cache_key] = (closes, now)
    return closes


def _nearest_on_or_before(closes: dict[date, float], target: date) -> float | None:
    """target 날짜 이하에서 가장 가까운 KOSPI 종가를 반환. 없으면 None."""
    if not closes:
        return None
    candidates = [d for d in closes if d <= target]
    if not candidates:
        return None
    return closes[max(candidates)]


async def get_kospi_close(d: date, pages: int = 10) -> float | None:
    """특정 날짜(또는 직전 영업일)의 KOSPI 종가를 반환한다."""
    closes = await _load_kospi_closes(pages=pages)
    return _nearest_on_or_before(closes, d)


async def get_kospi_cumulative_return(
    start: date,
    end: date,
    pages: int = 10,
) -> float | None:
    """start → end 구간의 KOSPI 누적 수익률(%)을 반환한다.

    기간 내 거래일이 없으면 None. 페이지 수는 필요시 호출부에서 늘린다.
    """
    if end < start:
        return None

    # 기간이 길면 페이지 수를 동적으로 확장 (페이지당 약 10거래일)
    span_days = (end - start).days
    auto_pages = max(pages, (span_days // 14) + 2)

    closes = await _load_kospi_closes(pages=auto_pages)
    start_close = _nearest_on_or_before(closes, start)
    end_close = _nearest_on_or_before(closes, end)
    if not start_close or not end_close or start_close <= 0:
        return None
    return round((end_close - start_close) / start_close * 100, 4)


async def get_kospi_period_return(
    from_dt: datetime,
    to_dt: datetime,
    pages: int = 10,
) -> float | None:
    """datetime 쌍으로 받아 KOSPI 누적 수익률(%)을 반환한다.

    타임존이 없으면 UTC로 가정하여 KST(Asia/Seoul) 날짜로 변환한다.
    """
    from zoneinfo import ZoneInfo

    def _to_kst_date(dt: datetime) -> date:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Seoul")).date()

    return await get_kospi_cumulative_return(
        _to_kst_date(from_dt),
        _to_kst_date(to_dt),
        pages=pages,
    )


def clear_cache() -> None:
    """테스트용 — 메모리 캐시를 초기화."""
    _cache.clear()
