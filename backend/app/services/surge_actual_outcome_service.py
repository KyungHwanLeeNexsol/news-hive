"""SPEC-AI-041: 장 마감 후 실제 급등주 결과 수집 서비스.

당일 상승률 상위 종목(KOSPI/KOSDAQ 각 100개)을 조회하여
SurgeActualOutcome 테이블에 upsert한다.

SPEC-AI-093: `high_change_rate`(장중 고가 기준 등락률)를 일봉 실측값으로 채운다.
종가 기준 `change_rate`/`was_surge` 산출 경로는 동결(D1/D2)하고, 고가 기반 성공 판정은
저장 컬럼이 아닌 읽기 시점 파생 지표(`evaluate_high_based_outcomes`)로 병렬 제공한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.naver_finance import (
    PriceRecord,
    fetch_current_price_with_change,
    fetch_stock_price_history,
    fetch_top_movers_codes,
)

logger = logging.getLogger(__name__)

# SPEC 요구사항: 상승률 상위 100개씩 수집
_TOP_MOVERS_LIMIT = 100
# 종목별 가격 조회 동시성 제한 (레이트 리미트 방지)
_PRICE_CONCURRENCY = 10

# ---------------------------------------------------------------------------
# SPEC-AI-093: 고가 기준 등락률 수집 설정
# ---------------------------------------------------------------------------

# 고가 조회 시 요청할 일봉 페이지 수 (Naver sise_day는 페이지당 약 10거래일).
# pages=3(≈30거래일)을 기본값으로 잡는 이유는 두 가지다.
#   1) 연휴 직후 T-1이 며칠 전이어도 T/T-1 레코드가 모두 포함된다.
#   2) `_price_cache`는 stock_code만으로 키를 잡으므로, pages=1로 조회하면 약 10거래일짜리
#      짧은 리스트가 공유 캐시에 기록되어 20거래일 이상을 요구하는 탐지기 계산을 굶길 수 있다.
#      코드베이스에서 이미 안전선으로 쓰이는 값(fetch_stock_price_history_sync 기본 pages=3)에 맞춘다.
_HIGH_HISTORY_PAGES: int = int(os.getenv("SURGE_HIGH_HISTORY_PAGES", "3"))

# REQ-AI093-005: 고가 기반 파생 지표의 "부분 수집" 판정 임계값 (기본 0.90).
_HIGH_COVERAGE_THRESHOLD: float = float(os.getenv("SURGE_HIGH_COVERAGE_THRESHOLD", "0.90"))

# REQ-AI093-001 불변식 비교 허용 오차. `change_rate`는 Naver fluctuationsRatio에서,
# `high_change_rate`는 자체 계산에서 나오므로 소수 2자리 반올림 차이를 위반으로 오판하지 않는다.
_HIGH_INVARIANT_TOLERANCE = 0.01

# REQ-AI093-003: fallback 사유 코드 (영문 식별자 고정, 로그 문구만 한국어)
_HIGH_FALLBACK_REASONS = (
    "no_candle_t",
    "no_candle_t1",
    "invalid_high",
    "invalid_prev_close",
    "invariant_violation",
)


def _naver_date_key(d: date) -> str:
    """`date`를 Naver 일봉 날짜 형식(`YYYY.MM.DD`)으로 변환한다."""
    return d.strftime("%Y.%m.%d")


def compute_high_change_rate(
    records: list[PriceRecord],
    trading_date: date,
    prev_business_day: date,
    change_rate: float,
) -> tuple[float | None, str | None]:
    # @MX:NOTE: [AUTO] SPEC-AI-093 — T-1 종가는 인덱스가 아닌 date 매칭으로 특정한다.
    # @MX:REASON: SPEC-AI-072에서 near_limit_up_carry가 인덱스 기반 조회로 T-1 등락률을
    #   오라벨해 "이미 당일 급등한 종목을 뒤늦게 추격"하는 정반대 동작을 한 사례가 있다.
    # @MX:ANCHOR: (T일 high, T-1일 close) 쌍은 반드시 date 값 매칭으로만 결정된다.
    # @MX:SPEC: SPEC-AI-093 REQ-AI093-001 REQ-AI093-002
    """장중 고가 기준 등락률을 계산한다(순수 함수).

    계산식: `(T일 high - T-1일 close) / T-1일 close * 100`

    Args:
        records: `fetch_stock_price_history`가 반환한 일봉 리스트 (순서 무관)
        trading_date: 수집 기준 거래일 (T)
        prev_business_day: 직전 영업일 (T-1)
        change_rate: 같은 행의 종가 기준 등락률 (불변식 검증용)

    Returns:
        `(high_change_rate, None)` 성공, 또는 `(None, fallback_reason)` 실패.
        fallback_reason은 `_HIGH_FALLBACK_REASONS` 중 하나.
    """
    by_date = {r.date.strip(): r for r in records if r.date}

    t_record = by_date.get(_naver_date_key(trading_date))
    if t_record is None:
        return None, "no_candle_t"

    t1_record = by_date.get(_naver_date_key(prev_business_day))
    if t1_record is None:
        return None, "no_candle_t1"

    high = float(t_record.high)
    if high <= 0:
        return None, "invalid_high"

    prev_close = float(t1_record.close)
    if prev_close <= 0:
        return None, "invalid_prev_close"

    value = round((high - prev_close) / prev_close * 100, 2)

    # REQ-AI093-001: 고가 >= 종가이므로 high_change_rate < change_rate는 계산 오류다.
    if value < change_rate - _HIGH_INVARIANT_TOLERANCE:
        return None, "invariant_violation"

    return value, None


def _is_price_history_cached(code: str) -> bool:
    """일봉이 이미 인메모리 캐시에 신선하게 존재하는지 확인한다(REQ-AI093-006 계측용).

    naver_finance의 캐시 상태를 읽기만 하며 수정하지 않는다. Redis 복구 경로로도
    외부 호출이 생략될 수 있으므로 이 값은 "인메모리 적중"의 하한 추정치다.
    """
    try:
        from app.services import naver_finance as _nf

        if code not in _nf._price_cache.data:
            return False
        last = _nf._price_cache.last_updated.get(code, 0)
        return (time.time() - last) < _nf._cache_ttl()
    except Exception:
        return False


async def _fetch_price_history_for_high(code: str) -> list[PriceRecord]:
    """고가 계산용 일봉을 조회한다. 실패 시 빈 리스트(배치 중단 없음)."""
    try:
        return await fetch_stock_price_history(code, pages=_HIGH_HISTORY_PAGES)
    except Exception as e:
        logger.debug("고가용 일봉 조회 실패 — 건너뜀 (%s): %s", code, e)
        return []


def _log_high_change_rate_summary(
    *,
    trading_date: date,
    row_count: int,
    fallback_counts: dict[str, int],
    attempt_count: int,
    cache_hit_count: int,
) -> None:
    """고가 수집 결과 요약(REQ-AI093-003) + 조회 비용 계측(REQ-AI093-006)을 각 1건 로깅한다.

    배치 카운터는 모듈 전역이 아니라 호출자의 지역 상태로 전달받는다 —
    pytest-xdist 병렬 워커 간 상태 공유 레이스를 원천 차단한다(plan.md §C).
    """
    fallback_total = sum(fallback_counts.values())
    measured = row_count - fallback_total
    breakdown = ", ".join(
        f"{reason}={fallback_counts.get(reason, 0)}"
        f"({(fallback_counts.get(reason, 0) / row_count * 100) if row_count else 0.0:.1f}%)"
        for reason in _HIGH_FALLBACK_REASONS
    )
    logger.info(
        "고가 기준 등락률 수집 요약: trading_date=%s, 실측=%d/%d (%.1f%%), fallback=%d [%s]",
        trading_date, measured, row_count,
        (measured / row_count * 100) if row_count else 0.0,
        fallback_total, breakdown,
    )
    # 캐시 적중은 인메모리 기준 하한 추정(Redis 복구 경로도 외부 호출을 생략함).
    logger.info(
        "고가 조회 비용 계측: trading_date=%s, 조회시도=%d건, 캐시적중=%d건, "
        "외부호출(추정)=%d건 (pages=%d)",
        trading_date, attempt_count, cache_hit_count,
        max(attempt_count - cache_hit_count, 0) * _HIGH_HISTORY_PAGES,
        _HIGH_HISTORY_PAGES,
    )


async def _fetch_code_info(code: str) -> dict | None:
    """종목 코드에 대한 가격/등락률 정보를 조회한다.

    실패 시 None 반환 (배치 전체를 중단하지 않음).
    """
    try:
        return await fetch_current_price_with_change(code)
    except Exception as e:
        logger.warning("종목 가격 조회 실패 — 건너뜀 (%s): %s", code, e)
        return None


def _fetch_tracked_stock_codes(db: Session, codes: list[str]) -> set[str] | None:
    # @MX:NOTE: [AUTO] SPEC-AI-074 — 분류 로직을 stock_registry_service.fetch_tracked_stock_codes로
    # 추출(단일 출처, REQ-001 HARD). 이 함수는 SPEC-AI-071 호출부의 기존 import 경로
    # (`_fetch_tracked_stock_codes`)를 깨지 않기 위한 하위 호환 위임 래퍼이며 거동은 불변이다.
    """`stocks` 교집합 조회를 stock_registry_service로 위임한다(SPEC-AI-074, 거동 불변).

    분류 규칙의 실제 구현·불변 계약(@MX:ANCHOR)은 `stock_registry_service.fetch_tracked_stock_codes`
    를 참고. Pool B(SPEC-AI-074)도 동일 헬퍼를 재사용해 규칙이 두 곳에 중복되지 않는다.

    Args:
        db: SQLAlchemy 동기 세션
        codes: 교집합 대상 코드 목록

    Returns:
        stocks에 존재하는 코드 집합. 조회 실패 시 None(fail-open, REQ-AI071-001 EC-1).
    """
    from app.services.stock_registry_service import fetch_tracked_stock_codes

    return fetch_tracked_stock_codes(db, codes)


async def collect_daily_surge_outcomes(db: Session, trading_date: date) -> int:
    # @MX:NOTE: [AUTO] SPEC-AI-041 — 장 마감 후 실제 급등주 수집. change_rate >= 10.0을 was_surge=True로 분류
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-001
    """당일 KOSPI/KOSDAQ 상승률 상위 종목을 수집하여 SurgeActualOutcome에 upsert한다.

    1. KOSPI/KOSDAQ 각 상위 100개 종목 코드 조회
    2. 앱 stocks 테이블 존재 종목으로 교집합 필터 (SPEC-AI-071, ETN·미추적 기업 제외)
    3. 중복 제거 후 종목별 change_rate 조회
    4. change_rate >= 10.0 → was_surge=True
    5. (trading_date, stock_code) composite PK upsert

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 수집 기준 날짜 (당일 장 마감 날짜)

    Returns:
        저장/갱신된 레코드 수
    """
    # 1단계: KOSPI/KOSDAQ 상위 종목 코드 수집 (동시 조회)
    kospi_codes, kosdaq_codes = await asyncio.gather(
        fetch_top_movers_codes("KOSPI", _TOP_MOVERS_LIMIT),
        fetch_top_movers_codes("KOSDAQ", _TOP_MOVERS_LIMIT),
    )

    # 시장 정보 매핑: 코드 → market (먼저 본 시장으로 저장, 중복 시 KOSPI 우선)
    code_to_market: dict[str, str] = {}
    for code in kosdaq_codes:
        code_to_market[code] = "KOSDAQ"
    for code in kospi_codes:
        code_to_market[code] = "KOSPI"  # KOSPI 우선 (덮어쓰기)

    unique_codes = list(code_to_market.keys())

    # 예측 종목 보완: T-1 surge_candidate 예측 종목이 top-100 밖이어도 결과 수집
    # top-100에 없는 예측 종목을 누락하면 평가 시 TP 계산에서 영구 제외됨
    try:
        from app.models.fund_signal import FundSignal
        from app.models.stock import Stock as _StockModel
        from app.services.surge_trading_service import _get_prev_business_day
        from sqlalchemy import func as _sqlfunc

        prev_day = _get_prev_business_day(trading_date)
        predicted_rows = (
            db.query(_StockModel.stock_code, _StockModel.market)
            .join(FundSignal, FundSignal.stock_id == _StockModel.id)
            .filter(
                FundSignal.signal_type == "surge_candidate",
                FundSignal.surge_metadata.isnot(None),
                _sqlfunc.date(FundSignal.created_at) == prev_day,
            )
            .distinct()
            .all()
        )
        supplement_count = 0
        for row in predicted_rows:
            if row.stock_code not in code_to_market:
                code_to_market[row.stock_code] = row.market or "UNKNOWN"
                supplement_count += 1
        if supplement_count:
            unique_codes = list(code_to_market.keys())
            logger.info("예측 종목 보완: top-100 외 %d개 추가 (T-1=%s)", supplement_count, prev_day)
    except Exception as _supp_e:
        logger.warning("예측 종목 보완 실패 — top-100 결과만 사용: %s", _supp_e)

    logger.info(
        "급등 결과 수집 시작: trading_date=%s, KOSPI=%d, KOSDAQ=%d, 중복제거=%d",
        trading_date, len(kospi_codes), len(kosdaq_codes), len(unique_codes),
    )

    # REQ-AI071-001/003: 앱 stocks 테이블 존재 종목으로 정답 모집단을 교집합한다.
    # T-1 예측 보완 종목(:72-101)은 이미 stocks JOIN으로 소싱되므로 이 필터를 통과한다(REQ-AI071-002).
    tracked_codes = _fetch_tracked_stock_codes(db, unique_codes)
    if tracked_codes is not None:
        excluded_codes = [c for c in unique_codes if c not in tracked_codes]
        if excluded_codes:
            # REQ-AI071-004: 제외 종목 수 관측 로깅
            logger.info(
                "stocks 미존재 종목 제외: trading_date=%s, 제외=%d건 (예: %s)",
                trading_date, len(excluded_codes), excluded_codes[:5],
            )
        unique_codes = [c for c in unique_codes if c in tracked_codes]
    # tracked_codes is None → stocks 조회 실패, fail-open으로 unique_codes 미필터 유지(EC-1)

    # 2단계: 종목별 change_rate 조회 (세마포어로 동시성 제한)
    semaphore = asyncio.Semaphore(_PRICE_CONCURRENCY)

    async def _fetch_with_semaphore(code: str) -> tuple[str, dict | None]:
        async with semaphore:
            result = await _fetch_code_info(code)
            return code, result

    tasks = [_fetch_with_semaphore(code) for code in unique_codes]
    results = await asyncio.gather(*tasks)

    # 2-b단계: SPEC-AI-093 — 고가 기준 등락률용 일봉 조회 (동일 세마포어 재사용).
    # 기존 change_rate 경로(fetch_current_price_with_change)는 건드리지 않는 별도 조회다(D1).
    from app.services.surge_trading_service import _get_prev_business_day as _prev_bday

    prev_business_day = _prev_bday(trading_date)

    async def _fetch_history_with_semaphore(
        code: str,
    ) -> tuple[str, list[PriceRecord], bool]:
        was_cached = _is_price_history_cached(code)
        async with semaphore:
            return code, await _fetch_price_history_for_high(code), was_cached

    history_results = await asyncio.gather(
        *[_fetch_history_with_semaphore(code) for code in unique_codes]
    )
    history_map: dict[str, list[PriceRecord]] = {}
    cache_hit_count = 0
    for code, records, was_cached in history_results:
        history_map[code] = records
        if was_cached:
            cache_hit_count += 1

    # 3단계: 유효한 결과만 upsert 준비
    rows_to_upsert: list[dict] = []
    fallback_counts: dict[str, int] = {}
    for code, price_info in results:
        if price_info is None:
            # R1.5: 개별 종목 실패는 건너뜀 (배치 전체 중단 불가)
            logger.warning("가격 조회 실패 — 건너뜀: %s", code)
            continue

        change_rate: float = price_info.get("change_rate", 0.0)
        market = code_to_market.get(code, "UNKNOWN")

        # REQ-AI093-001/003: 실측 실패 시 change_rate로 대체하지 않고 NULL로 남긴다(D4).
        high_change_rate, fallback_reason = compute_high_change_rate(
            history_map.get(code) or [],
            trading_date,
            prev_business_day,
            change_rate,
        )
        if fallback_reason is not None:
            fallback_counts[fallback_reason] = fallback_counts.get(fallback_reason, 0) + 1
            logger.debug(
                "고가 기준 등락률 계산 불가 — NULL 저장: code=%s, reason=%s",
                code, fallback_reason,
            )

        rows_to_upsert.append({
            "trading_date": trading_date,
            "stock_code": code,
            # 종목명은 코드로 대체 (fetch_top_movers_codes는 이름 미반환)
            # 실제 종목명은 DB의 Stock 테이블에서 사후 조회 가능
            "stock_name": code,
            "change_rate": change_rate,
            "was_surge": change_rate >= 10.0,
            "high_change_rate": high_change_rate,
            "market": market,
        })

    # REQ-AI093-003: 사유별 건수 + 비율 요약 (배치 1건).
    # REQ-AI093-006: 고가 조회 비용 실측. upsert 대상이 0건이어도 항상 남긴다.
    _log_high_change_rate_summary(
        trading_date=trading_date,
        row_count=len(rows_to_upsert),
        fallback_counts=fallback_counts,
        attempt_count=len(unique_codes),
        cache_hit_count=cache_hit_count,
    )

    if not rows_to_upsert:
        logger.warning("upsert할 레코드 없음: trading_date=%s", trading_date)
        return 0

    # 종목명을 DB Stock 테이블에서 조회하여 보완
    from app.models.stock import Stock  # 순환 임포트 방지를 위해 지연 임포트

    stock_codes_in_batch = [r["stock_code"] for r in rows_to_upsert]
    stock_name_map: dict[str, str] = {}
    try:
        stock_rows = (
            db.query(Stock.stock_code, Stock.name)
            .filter(Stock.stock_code.in_(stock_codes_in_batch))
            .all()
        )
        stock_name_map = {row.stock_code: row.name for row in stock_rows}
    except Exception as e:
        logger.warning("종목명 조회 실패 — 코드로 대체: %s", e)
        # SSL 연결 끊김(OperationalError) 시 세션이 PendingRollback 상태에 빠짐.
        # 이후 db.execute(upsert)가 PendingRollbackError로 실패하므로 명시적 rollback.
        try:
            db.rollback()
        except Exception:
            pass

    for row in rows_to_upsert:
        code = row["stock_code"]
        if code in stock_name_map:
            row["stock_name"] = stock_name_map[code]

    # REQ-AI061-E01: 종목명 미해결 건수 경고 로깅
    # Stock 테이블에 없는 종목은 코드값 그대로 저장됨 — 수동 backfill 필요
    unresolved = sum(1 for r in rows_to_upsert if r["stock_name"] == r["stock_code"])
    if unresolved:
        logger.warning(
            "종목명 미해결 %d건 — 코드를 종목명으로 저장 (Group E REQ-AI061-E01)",
            unresolved,
        )

    # 4단계: PostgreSQL upsert (composite PK 충돌 시 UPDATE)
    # REQ-AI061-E02: stock_name은 새 값이 실제 이름일 때만 덮어씀.
    # 새 값 == stock_code(즉 fallback 코드값)이면 기존 DB값(이미 실명일 수 있음)을 보존.
    _ins = pg_insert(SurgeActualOutcome)
    stmt = (
        _ins
        .values(rows_to_upsert)
        .on_conflict_do_update(
            index_elements=["trading_date", "stock_code"],
            set_={
                "stock_name": case(
                    (
                        _ins.excluded.stock_name != SurgeActualOutcome.stock_code,
                        _ins.excluded.stock_name,
                    ),
                    else_=SurgeActualOutcome.stock_name,
                ),
                "change_rate": _ins.excluded.change_rate,
                "was_surge": _ins.excluded.was_surge,
                "high_change_rate": _ins.excluded.high_change_rate,
                "market": _ins.excluded.market,
            },
        )
    )
    db.execute(stmt)
    db.commit()

    saved_count = len(rows_to_upsert)
    surge_count = sum(1 for r in rows_to_upsert if r["was_surge"])
    logger.info(
        "SurgeActualOutcome upsert 완료: trading_date=%s, saved=%d, was_surge=%d",
        trading_date, saved_count, surge_count,
    )
    return saved_count


def evaluate_high_based_outcomes(
    db: Session,
    trading_date: date,
    surge_threshold: float = 10.0,
    coverage_threshold: float | None = None,
) -> dict:
    # @MX:NOTE: [AUTO] SPEC-AI-093 — 고가 기반 성공 판정은 저장 컬럼이 아니라 읽기 시점 파생값이다.
    # @MX:SPEC: SPEC-AI-093 REQ-AI093-005
    """거래일별 고가 기반 파생 지표를 기존 `was_surge` 지표와 **병렬로** 반환한다.

    파생 판정은 `COALESCE(high_change_rate, change_rate) >= surge_threshold`다(D4 — 저장은
    정직하게 NULL, 소비 시점에 fallback 적용). 기존 `was_surge` 집계는 그대로 함께 반환하며
    대체하지 않는다(D2 동결).

    커버리지(`high_change_rate IS NOT NULL` 비율)가 임계값 미만이면 `partial_collection=True`를
    부착한다 — 배포 직후처럼 부분 수집된 날의 낮은 고가 기반 recall을 실제 성능 저하로
    오독하지 않게 하기 위함이다(D3 전진 적용의 대가를 표면화).

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 조회 대상 거래일
        surge_threshold: 급등 판정 임계 등락률 (기본 10.0 — 기존 `was_surge`와 동일 기준)
        coverage_threshold: 부분 수집 판정 임계 커버리지. None이면 모듈 기본값(0.90).

    Returns:
        지표 dict. `total_rows == 0`이면 커버리지 0.0 + `partial_collection=True`.
    """
    if coverage_threshold is None:
        coverage_threshold = _HIGH_COVERAGE_THRESHOLD

    effective_rate = func.coalesce(
        SurgeActualOutcome.high_change_rate, SurgeActualOutcome.change_rate
    )
    row = (
        db.query(
            func.count().label("total_rows"),
            # count(col)은 NULL을 제외하므로 곧 실측 건수다.
            func.count(SurgeActualOutcome.high_change_rate).label("high_measured_rows"),
            func.sum(
                case((SurgeActualOutcome.was_surge.is_(True), 1), else_=0)
            ).label("was_surge_count"),
            func.sum(
                case((effective_rate >= surge_threshold, 1), else_=0)
            ).label("high_based_surge_count"),
        )
        .filter(SurgeActualOutcome.trading_date == trading_date)
        .one()
    )

    total_rows = int(row.total_rows or 0)
    high_measured_rows = int(row.high_measured_rows or 0)
    coverage = (high_measured_rows / total_rows) if total_rows else 0.0

    return {
        "trading_date": trading_date,
        "total_rows": total_rows,
        "high_measured_rows": high_measured_rows,
        "coverage": coverage,
        "coverage_threshold": coverage_threshold,
        "partial_collection": coverage < coverage_threshold,
        # 기존 지표 (병렬 유지 — 대체 금지)
        "was_surge_count": int(row.was_surge_count or 0),
        # 고가 기반 파생 지표
        "high_based_surge_count": int(row.high_based_surge_count or 0),
    }


def backfill_stock_names(db: Session) -> int:
    # @MX:NOTE: [AUTO] REQ-AI061-E03 — 수동 복구 도구. 자동 호출 없음.
    # @MX:SPEC: SPEC-AI-061 REQ-AI061-E03
    """stock_name == stock_code 인 행을 Stock 테이블로 일괄 보정한다.

    자동 실행되지 않는 수동 복구 함수.
    운영 중 누락된 종목명을 일괄 수정할 때 직접 호출한다.

    Args:
        db: SQLAlchemy 동기 세션

    Returns:
        실제 업데이트된 행 수
    """
    from app.models.stock import Stock  # 순환 임포트 방지

    # 500건 단위 배치 처리
    _BATCH_SIZE = 500

    total_updated = 0
    offset = 0

    while True:
        # stock_name == stock_code 인 행의 distinct stock_code 조회
        rows = (
            db.query(SurgeActualOutcome.stock_code)
            .filter(SurgeActualOutcome.stock_name == SurgeActualOutcome.stock_code)
            .distinct()
            .limit(_BATCH_SIZE)
            .offset(offset)
            .all()
        )

        if not rows:
            break

        batch_codes = [r.stock_code for r in rows]

        # Stock 테이블에서 실제 종목명 조회
        name_map: dict[str, str] = {
            row.stock_code: row.name
            for row in db.query(Stock.stock_code, Stock.name)
            .filter(Stock.stock_code.in_(batch_codes))
            .all()
        }

        if not name_map:
            # 이 배치에 해당하는 Stock 행이 없음 — 다음 배치 없으므로 종료
            logger.warning(
                "backfill_stock_names: Stock 테이블에서 이름 미발견 (offset=%d, batch=%d)",
                offset, len(rows),
            )
            break

        # 실제 이름이 조회된 행만 UPDATE
        batch_updated = 0
        for row in rows:
            real_name = name_map.get(row.stock_code)
            if real_name:
                db.query(SurgeActualOutcome).filter(
                    SurgeActualOutcome.stock_code == row.stock_code
                ).update({"stock_name": real_name}, synchronize_session=False)
                batch_updated += 1

        if batch_updated:
            db.commit()

        total_updated += batch_updated
        logger.info(
            "backfill_stock_names: offset=%d, batch=%d, updated=%d, total=%d",
            offset, len(rows), batch_updated, total_updated,
        )

        # 업데이트된 행은 다음 쿼리에서 제외되므로 offset 고정 (미해결 행만 남음)
        # 업데이트가 없으면 더 이상 진행 불가 — 종료
        if batch_updated == 0:
            break

        # 이 배치의 미해결 건수 = len(rows) - batch_updated → 다음 루프에서 다시 조회
        # offset은 올리지 않음: 이미 보정된 행은 다음 쿼리 필터에서 자연 제외됨

    logger.info("backfill_stock_names 완료: total_updated=%d", total_updated)
    return total_updated
