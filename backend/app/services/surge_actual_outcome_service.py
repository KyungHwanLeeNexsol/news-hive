"""SPEC-AI-041: 장 마감 후 실제 급등주 결과 수집 서비스.

당일 상승률 상위 종목(KOSPI/KOSDAQ 각 100개)을 조회하여
SurgeActualOutcome 테이블에 upsert한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.naver_finance import fetch_current_price_with_change, fetch_top_movers_codes

logger = logging.getLogger(__name__)

# SPEC 요구사항: 상승률 상위 100개씩 수집
_TOP_MOVERS_LIMIT = 100
# 종목별 가격 조회 동시성 제한 (레이트 리미트 방지)
_PRICE_CONCURRENCY = 10


async def _fetch_code_info(code: str) -> dict | None:
    """종목 코드에 대한 가격/등락률 정보를 조회한다.

    실패 시 None 반환 (배치 전체를 중단하지 않음).
    """
    try:
        return await fetch_current_price_with_change(code)
    except Exception as e:
        logger.warning("종목 가격 조회 실패 — 건너뜀 (%s): %s", code, e)
        return None


async def collect_daily_surge_outcomes(db: Session, trading_date: date) -> int:
    # @MX:NOTE: [AUTO] SPEC-AI-041 — 장 마감 후 실제 급등주 수집. change_rate >= 10.0을 was_surge=True로 분류
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-001
    """당일 KOSPI/KOSDAQ 상승률 상위 종목을 수집하여 SurgeActualOutcome에 upsert한다.

    1. KOSPI/KOSDAQ 각 상위 100개 종목 코드 조회
    2. 중복 제거 후 종목별 change_rate 조회
    3. change_rate >= 10.0 → was_surge=True
    4. (trading_date, stock_code) composite PK upsert

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

    # 2단계: 종목별 change_rate 조회 (세마포어로 동시성 제한)
    semaphore = asyncio.Semaphore(_PRICE_CONCURRENCY)

    async def _fetch_with_semaphore(code: str) -> tuple[str, dict | None]:
        async with semaphore:
            result = await _fetch_code_info(code)
            return code, result

    tasks = [_fetch_with_semaphore(code) for code in unique_codes]
    results = await asyncio.gather(*tasks)

    # 3단계: 유효한 결과만 upsert 준비
    rows_to_upsert: list[dict] = []
    for code, price_info in results:
        if price_info is None:
            # R1.5: 개별 종목 실패는 건너뜀 (배치 전체 중단 불가)
            logger.warning("가격 조회 실패 — 건너뜀: %s", code)
            continue

        change_rate: float = price_info.get("change_rate", 0.0)
        market = code_to_market.get(code, "UNKNOWN")

        rows_to_upsert.append({
            "trading_date": trading_date,
            "stock_code": code,
            # 종목명은 코드로 대체 (fetch_top_movers_codes는 이름 미반환)
            # 실제 종목명은 DB의 Stock 테이블에서 사후 조회 가능
            "stock_name": code,
            "change_rate": change_rate,
            "was_surge": change_rate >= 10.0,
            "high_change_rate": None,  # 고가 기준 등락률은 현재 API에서 미지원
            "market": market,
        })

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

    # 4단계: PostgreSQL upsert (composite PK 충돌 시 UPDATE)
    stmt = (
        pg_insert(SurgeActualOutcome)
        .values(rows_to_upsert)
        .on_conflict_do_update(
            index_elements=["trading_date", "stock_code"],
            set_={
                "stock_name": pg_insert(SurgeActualOutcome).excluded.stock_name,
                "change_rate": pg_insert(SurgeActualOutcome).excluded.change_rate,
                "was_surge": pg_insert(SurgeActualOutcome).excluded.was_surge,
                "high_change_rate": pg_insert(SurgeActualOutcome).excluded.high_change_rate,
                "market": pg_insert(SurgeActualOutcome).excluded.market,
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
