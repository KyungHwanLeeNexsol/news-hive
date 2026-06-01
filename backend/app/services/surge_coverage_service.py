"""SPEC-AI-022: 시그널 커버리지 대시보드 서비스.

오늘 생성된 시그널의 커버리지 지표를 계산하고,
미커버 상위 종목(market_cap >= 1000억, change_pct >= 15%)을 반환한다.
60초 인메모리 캐시 포함.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone as _timezone_cls

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 60초 인메모리 캐시
_coverage_cache: dict | None = None
_coverage_cache_at: float = 0.0
_CACHE_TTL_SECONDS: int = 60


def compute_coverage_dashboard(
    db: Session,
    cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    top_missed_min_market_cap: int = 1000,
    top_missed_min_change_pct: float = 15.0,
    top_missed_timeout_seconds: float = 15.0,
) -> dict:
    """커버리지 대시보드 지표를 계산하여 dict로 반환한다.

    CoverageDashboardResponse.model_validate() 호환 구조.

    Args:
        db: SQLAlchemy 세션
        cache_ttl_seconds: 캐시 유효 시간 (초)
        top_missed_min_market_cap: top_missed 시총 최소값 (억원)
        top_missed_min_change_pct: top_missed 등락률 최소값 (%)
        top_missed_timeout_seconds: top_missed 조회 타임아웃 (초)

    Returns:
        CoverageDashboardResponse 호환 dict
    """
    global _coverage_cache, _coverage_cache_at

    # 캐시 히트 확인
    now = time.monotonic()
    if _coverage_cache is not None and (now - _coverage_cache_at) < cache_ttl_seconds:
        logger.debug("[커버리지] 캐시 히트")
        return _coverage_cache

    result = _build_coverage_data(
        db,
        top_missed_min_market_cap=top_missed_min_market_cap,
        top_missed_min_change_pct=top_missed_min_change_pct,
        top_missed_timeout_seconds=top_missed_timeout_seconds,
    )

    _coverage_cache = result
    _coverage_cache_at = now
    return result


def _build_coverage_data(
    db: Session,
    top_missed_min_market_cap: int,
    top_missed_min_change_pct: float,
    top_missed_timeout_seconds: float,
) -> dict:
    """커버리지 데이터를 실제로 계산한다."""
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock

    # KST 기준 오늘 시작 (UTC)
    _KST = _timezone_cls(timedelta(hours=9))
    try:
        from app.services.fund_manager import _KST as _fund_kst  # type: ignore[attr-defined]
        _KST = _fund_kst
    except Exception:
        pass
    now_kst = datetime.now(_KST)

    today_kst = now_kst.date()
    today_start_utc = datetime.combine(
        today_kst,
        datetime.min.time(),
        tzinfo=_KST,
    ).astimezone(_timezone_cls.utc)

    # 전체 추적 종목 수 (total_stocks_tracked)
    total_stocks = db.query(sqlfunc.count(Stock.id)).scalar() or 0

    # 오늘 시그널 수 (signal_type별 집계)
    today_signal_rows = (
        db.query(FundSignal.signal_type, sqlfunc.count(FundSignal.id))
        .filter(FundSignal.created_at >= today_start_utc)
        .group_by(FundSignal.signal_type)
        .all()
    )

    by_signal_type: dict[str, int] = {}
    for sig_type, cnt in today_signal_rows:
        key = sig_type or "unknown"
        by_signal_type[key] = cnt

    signals_generated_today = sum(by_signal_type.values())
    theme_propagation_triggered = by_signal_type.get("theme_propagation", 0)
    volume_anomaly_triggered = by_signal_type.get("volume_anomaly", 0)

    coverage_pct = 0.0
    if total_stocks > 0:
        coverage_pct = round(signals_generated_today / total_stocks * 100, 2)

    # top_missed 조회 (타임아웃 포함)
    top_missed: list[dict] = []
    top_missed_partial = False

    try:

        # Windows에서는 SIGALRM 미지원 — threading.Timer 방식으로 타임아웃 구현
        import threading

        _result_holder: list = []
        _exception_holder: list = []

        def _fetch_top_missed_worker():
            try:
                res = _fetch_top_missed_candidates(
                    db,
                    today_start_utc=today_start_utc,
                    min_market_cap=top_missed_min_market_cap,
                    min_change_pct=top_missed_min_change_pct,
                )
                _result_holder.append(res)
            except Exception as e:
                _exception_holder.append(e)

        thread = threading.Thread(target=_fetch_top_missed_worker, daemon=True)
        thread.start()
        thread.join(timeout=top_missed_timeout_seconds)

        if thread.is_alive():
            logger.warning("[커버리지] top_missed 조회 타임아웃 (%.1fs)", top_missed_timeout_seconds)
            top_missed_partial = True
        elif _exception_holder:
            logger.warning("[커버리지] top_missed 조회 예외: %s", _exception_holder[0])
            top_missed_partial = True
        elif _result_holder:
            top_missed = _result_holder[0]

    except Exception as e:
        logger.warning("[커버리지] top_missed 조회 실패: %s", e)
        top_missed_partial = True

    return {
        "as_of": now_kst.isoformat(),
        "total_stocks_tracked": total_stocks,
        "signals_generated_today": signals_generated_today,
        "coverage_pct": coverage_pct,
        "by_signal_type": by_signal_type,
        "theme_propagation_triggered": theme_propagation_triggered,
        "volume_anomaly_triggered": volume_anomaly_triggered,
        "top_missed": top_missed,
        "top_missed_partial": top_missed_partial,
    }


def _fetch_top_missed_candidates(
    db: Session,
    today_start_utc: datetime,
    min_market_cap: int,
    min_change_pct: float,
) -> list[dict]:
    """오늘 시그널 없는 대형주 중 상승률 >= 15% 종목 조회.

    외부 호출 가능 (테스트 모킹 용이).
    """
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock

    # 오늘 시그널이 있는 stock_id 집합
    today_signal_ids: set[int] = set()
    rows = (
        db.query(FundSignal.stock_id)
        .filter(FundSignal.created_at >= today_start_utc)
        .distinct()
        .all()
    )
    for row in rows:
        today_signal_ids.add(row[0])

    # 시총 >= min_market_cap이고 오늘 시그널 없는 종목
    candidates = (
        db.query(Stock)
        .filter(
            Stock.market_cap >= min_market_cap,
            ~Stock.id.in_(today_signal_ids) if today_signal_ids else Stock.id.isnot(None),
        )
        .order_by(Stock.market_cap.desc())
        .limit(100)
        .all()
    )

    result = []
    for stock in candidates:
        # 실시간 등락률 조회 (동기 버전 사용)
        try:
            from app.services.naver_finance import fetch_current_price_with_change_sync
            price_data = fetch_current_price_with_change_sync(stock.stock_code)
            if price_data is None:
                continue
            change_rate = price_data.get("change_rate", 0.0)
            if change_rate >= min_change_pct:
                result.append({
                    "stock_code": stock.stock_code,
                    "name": stock.name,
                    "change_pct": change_rate,
                    "market_cap": stock.market_cap,
                })
        except Exception as e:
            logger.debug("[커버리지] %s 등락률 조회 실패: %s", stock.stock_code, e)
            continue

    # 등락률 내림차순 정렬
    result.sort(key=lambda x: x["change_pct"], reverse=True)
    return result


def reset_coverage_cache() -> None:
    """테스트용 캐시 초기화."""
    global _coverage_cache, _coverage_cache_at
    _coverage_cache = None
    _coverage_cache_at = 0.0
