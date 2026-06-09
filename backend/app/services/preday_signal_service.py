"""SPEC-AI-042: 야간·장전 공시 기반 갭업 조기 포착 서비스.

장 마감(15:30) ~ 장 시작(09:00) 사이 접수되는 공시를 포착,
signal_type="preday_disclosure" FundSignal로 저장하고
익일 09:05 갭업 초기(0% ≤ gap < gap_entry_threshold)에
기존 execute_buy_orders로 조기 진입한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

# 모듈 레벨 임포트 — unittest.mock.patch의 대상이 되려면 모듈 네임스페이스에 존재해야 함
from app.services.naver_finance import fetch_current_price_with_change_sync
from app.services.surge_detector import (
    detect_disclosure_surge_pattern,
    detect_immediate_disclosure_signal,
)
from app.services.surge_trading_service import execute_buy_orders

logger = logging.getLogger(__name__)

# KST 타임존 (UTC+9)
KST = timezone(timedelta(hours=9))

# 시그널 타입 상수
PREDAY_SIGNAL_TYPE = "preday_disclosure"


def _compute_gap_rate(stock_code: str) -> float | None:
    """종목의 갭 비율을 동기적으로 조회한다 (전일 종가 대비 change_rate 사용).

    # @MX:NOTE: [AUTO] SPEC-AI-042 — fetch_current_price_with_change_sync로 갭 조회
    #   asyncio.run() 없이 동기 컨텍스트에서 안전하게 호출 가능.
    #   REQ-042-012: 조회 실패 시 None 반환 — 절대 예외 미전파

    Args:
        stock_code: 종목 코드

    Returns:
        change_rate(float) 또는 None (조회 실패 시)
    """
    try:
        data = fetch_current_price_with_change_sync(stock_code)
        if data is None:
            return None
        rate = data.get("change_rate")
        if rate is None:
            return None
        return float(rate)
    except Exception as exc:
        logger.debug("[preday] %s 갭 조회 실패: %s", stock_code, exc)
        return None


def _save_preday_signal(
    db: Session,
    stock_id: int,
    stock_code: str,
    disclosure_id: int | None,
    score: float,
    detector: str,
) -> bool:
    """preday_disclosure 시그널을 저장한다. 중복 시 False 반환.

    # @MX:NOTE: [AUTO] SPEC-AI-042 REQ-042-002 — 중복 판정 우선순위:
    #   1) disclosure_id 컬럼 직접 매칭 (가장 신뢰성 높음)
    #   2) surge_metadata JSON의 disclosure_id 필드 fallback

    Args:
        db: SQLAlchemy 세션
        stock_id: 종목 DB id
        stock_code: 종목 코드 (로그용)
        disclosure_id: 공시 DB id (None 허용)
        score: 탐지기가 부여한 시그널 점수
        detector: 탐지기 이름 ("immediate_disclosure" | "disclosure_pattern")

    Returns:
        True: 저장 성공, False: 중복으로 스킵
    """
    from app.models.fund_signal import FundSignal

    # 중복 체크 1: disclosure_id 컬럼 기반
    if disclosure_id is not None:
        dup = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_id,
                FundSignal.signal_type == PREDAY_SIGNAL_TYPE,
                FundSignal.disclosure_id == disclosure_id,
            )
            .first()
        )
        if dup is not None:
            logger.debug(
                "[preday] 중복 스킵(disclosure_id=%d) stock=%s",
                disclosure_id,
                stock_code,
            )
            return False

    # 중복 체크 2: surge_metadata JSON fallback (disclosure_id=None인 경우)
    if disclosure_id is None:
        existing = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_id,
                FundSignal.signal_type == PREDAY_SIGNAL_TYPE,
            )
            .all()
        )
        for sig in existing:
            try:
                meta = json.loads(sig.surge_metadata or "{}")
                if meta.get("source") == detector:
                    logger.debug(
                        "[preday] 중복 스킵(metadata fallback) stock=%s detector=%s",
                        stock_code,
                        detector,
                    )
                    return False
            except (json.JSONDecodeError, TypeError):
                pass

    # 시그널 저장
    metadata = {
        "detector": detector,
        "source": detector,
        "surge_probability_score": round(score, 4),
        "surge_basis": [detector],
    }
    if disclosure_id is not None:
        metadata["disclosure_id"] = disclosure_id

    new_signal = FundSignal(
        stock_id=stock_id,
        signal=("buy"),
        confidence=round(score, 4),
        reasoning=f"preday_disclosure 탐지기({detector}) score={score:.4f}",
        signal_type=PREDAY_SIGNAL_TYPE,
        disclosure_id=disclosure_id,
        surge_metadata=json.dumps(metadata, ensure_ascii=False),
    )
    db.add(new_signal)
    db.commit()
    logger.info(
        "[preday] 시그널 저장: stock=%s detector=%s score=%.4f disclosure_id=%s",
        stock_code,
        detector,
        score,
        disclosure_id,
    )
    return True


def _run_disclosure_scan(
    db: Session,
    scan_from_dt: datetime,
) -> int:
    """지정 시각 이후 접수된 공시를 스캔하여 preday_disclosure 시그널을 저장한다.

    # @MX:NOTE: [AUTO] SPEC-AI-042 REQ-042-001/003
    #   두 탐지기(immediate_disclosure, disclosure_pattern)를 순차 실행.
    #   detect_immediate_disclosure_signal: 공시 키워드 기반 이벤트 탐지
    #   detect_disclosure_surge_pattern: 공시 유형별 과거 급등 패턴 기반 탐지
    #   두 함수 모두 disclosure_window_hours로 창을 제어하므로, scan_from_dt를
    #   현재 시각 기준 disclosure_window_hours 범위 내로 변환하여 파라미터를 조정한다.

    Args:
        db: SQLAlchemy 세션
        scan_from_dt: 이 시각 이후 접수된 공시만 대상

    Returns:
        새로 저장된 시그널 개수
    """
    from app.surge_config.surge_settings import get_surge_config
    from app.models.disclosure import Disclosure
    from app.models.stock import Stock

    config = get_surge_config()
    now_utc = datetime.now(timezone.utc)

    # scan_from_dt 이후의 공시 id 집합 미리 조회 (탐지기 결과 필터링용)
    scan_from_str = scan_from_dt.astimezone(timezone.utc).strftime("%Y%m%d")
    recent_disclosure_ids: set[int] = set(
        row[0]
        for row in db.query(Disclosure.id)
        .filter(Disclosure.rcept_dt >= scan_from_str)
        .all()
        if row[0] is not None
    )

    if not recent_disclosure_ids:
        logger.info("[preday] %s 이후 공시 없음 — 스킵", scan_from_dt.isoformat())
        return 0

    # disclosure_window_hours를 현재 ~ scan_from_dt 차이로 동적 조정
    hours_since_scan = (now_utc - scan_from_dt.astimezone(timezone.utc)).total_seconds() / 3600
    # 최소 1시간, 최대 48시간
    window_hours = max(1.0, min(48.0, hours_since_scan + 0.5))

    # 임시 config 오버라이드 (window_hours 조정)
    import copy
    adjusted_config = copy.deepcopy(config)
    adjusted_config.disclosure_pattern.disclosure_window_hours = window_hours

    saved = 0

    # 탐지기 1: 즉각 공시 이벤트 시그널
    try:
        immediate_candidates = detect_immediate_disclosure_signal(db, adjusted_config)
        for cand in immediate_candidates:
            # 종목 조회
            stock = (
                db.query(Stock)
                .filter(Stock.stock_code == cand.stock_code)
                .first()
            )
            if stock is None:
                continue

            # 해당 종목의 공시 중 scan_from_dt 이후 것 찾기
            disc = (
                db.query(Disclosure)
                .filter(
                    Disclosure.stock_id == stock.id,
                    Disclosure.id.in_(recent_disclosure_ids),
                )
                .order_by(Disclosure.id.desc())
                .first()
            )
            disc_id = disc.id if disc else None
            score = cand.immediate_disclosure_score or cand.pattern_score or 0.5

            if _save_preday_signal(
                db,
                stock_id=stock.id,
                stock_code=cand.stock_code,
                disclosure_id=disc_id,
                score=score,
                detector="immediate_disclosure",
            ):
                saved += 1
    except Exception as exc:
        logger.exception("[preday] immediate_disclosure 탐지 실패: %s", exc)

    # 탐지기 2: 공시 유형 급등 패턴
    try:
        pattern_candidates = detect_disclosure_surge_pattern(db, adjusted_config)
        for cand in pattern_candidates:
            stock = (
                db.query(Stock)
                .filter(Stock.stock_code == cand.stock_code)
                .first()
            )
            if stock is None:
                continue

            disc = (
                db.query(Disclosure)
                .filter(
                    Disclosure.stock_id == stock.id,
                    Disclosure.id.in_(recent_disclosure_ids),
                )
                .order_by(Disclosure.id.desc())
                .first()
            )
            disc_id = disc.id if disc else None
            score = cand.pattern_score or 0.5

            if _save_preday_signal(
                db,
                stock_id=stock.id,
                stock_code=cand.stock_code,
                disclosure_id=disc_id,
                score=score,
                detector="disclosure_pattern",
            ):
                saved += 1
    except Exception as exc:
        logger.exception("[preday] disclosure_pattern 탐지 실패: %s", exc)

    logger.info("[preday] 스캔 완료: %d개 신규 시그널 저장", saved)
    return saved


def post_market_scan(db: Session, scan_from_dt: datetime) -> int:
    """장 마감 후 공시 스캔 (REQ-042-001).

    # @MX:ANCHOR: [AUTO] SPEC-AI-042 REQ-042-001 — 17:00 KST 잡에서 호출
    # @MX:REASON: scheduler._run_surge_preday_scan, 테스트, 수동 호출 등 복수 콜러

    Args:
        db: SQLAlchemy 세션
        scan_from_dt: 스캔 시작 시각 (보통 당일 15:30 KST)

    Returns:
        저장된 시그널 수
    """
    logger.info("[preday] 장 마감 후 공시 스캔 시작: from=%s", scan_from_dt.isoformat())
    return _run_disclosure_scan(db, scan_from_dt)


def preopen_watchlist_refresh(db: Session) -> int:
    """장전 워치리스트 갱신 (REQ-042-003).

    전날 17:00 KST 이후 ~ 지금까지 공시를 재스캔한다.
    기존 dedup 로직(REQ-042-002)이 동일하게 적용되어 중복 저장 방지.

    # @MX:ANCHOR: [AUTO] SPEC-AI-042 REQ-042-003 — 08:00 KST 잡에서 호출
    # @MX:REASON: scheduler._run_surge_preopen_refresh, 테스트, 수동 호출 등 복수 콜러

    Returns:
        새로 저장된 시그널 수
    """
    # 전날 17:00 KST를 스캔 시작점으로 설정
    now_kst = datetime.now(KST)
    yesterday_kst = now_kst.date() - timedelta(days=1)
    scan_from_dt = datetime.combine(yesterday_kst, time(17, 0)).replace(tzinfo=KST)

    logger.info("[preday] 장전 워치리스트 갱신 시작: from=%s", scan_from_dt.isoformat())
    return _run_disclosure_scan(db, scan_from_dt)


def early_entry_check(db: Session) -> dict:
    """09:05 KST 조기 진입 체크 (REQ-042-005~007).

    preday_disclosure 시그널 보유 종목별 갭 비율을 조회하여
    갭 필터를 통과한 종목에 대해 execute_buy_orders를 호출한다.

    # @MX:ANCHOR: [AUTO] SPEC-AI-042 REQ-042-005 — 09:05 KST 잡에서 호출
    # @MX:REASON: scheduler._run_surge_preday_early_entry, 테스트, 수동 호출 등 복수 콜러

    갭 필터 (REQ-042-006):
    - gap_rate >= gap_entry_threshold(기본 0.05): skip — 갭풀백 위임
    - gap_rate < 0: skip — 갭다운
    - 0 <= gap_rate < gap_entry_threshold: 채택

    Returns:
        {
            "candidates": int,      # 조기 진입 후보 수
            "entered": int,         # 실제 진입 시도 수
            "skipped_gapup": int,   # 갭 ≥ threshold 스킵
            "skipped_gapdown": int, # 갭 < 0% 스킵
            "execute_result": dict, # execute_buy_orders 결과
        }
    """
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.surge_config.surge_settings import get_surge_config

    config = get_surge_config()
    gap_threshold = getattr(config, "gap_entry_threshold", 0.05)

    # 당일 08:00 KST 이후 생성된 preday_disclosure 시그널 조회 (REQ-042-009)
    today_kst = datetime.now(KST).date()
    preday_cutoff = datetime.combine(today_kst, time(8, 0)).replace(tzinfo=KST)

    preday_signals_with_stocks = (
        db.query(FundSignal, Stock)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.signal_type == PREDAY_SIGNAL_TYPE,
            FundSignal.created_at >= preday_cutoff,
        )
        .all()
    )

    if not preday_signals_with_stocks:
        logger.info("[preday] 당일 08:00 이후 preday 시그널 없음 — 조기 진입 스킵")
        return {
            "candidates": 0,
            "entered": 0,
            "skipped_gapup": 0,
            "skipped_gapdown": 0,
            "execute_result": {},
        }

    candidates = len(preday_signals_with_stocks)
    skipped_gapup = 0
    skipped_gapdown = 0
    entered = 0

    for signal, stock in preday_signals_with_stocks:
        stock_code = stock.stock_code

        # REQ-042-012: 갭 조회 실패 시 해당 종목 건너뛰기 (전체 실패 금지)
        gap_rate = _compute_gap_rate(stock_code)
        if gap_rate is None:
            logger.warning("[preday] %s 갭 조회 실패 — 건너뜀", stock_code)
            continue

        # REQ-042-006: 갭 필터 적용
        if gap_rate >= gap_threshold:
            logger.info(
                "[preday] %s 갭 ≥ threshold(%.1f%% >= %.1f%%) — 갭풀백 위임",
                stock_code,
                gap_rate * 100,
                gap_threshold * 100,
            )
            skipped_gapup += 1
            continue

        if gap_rate < 0.0:
            logger.info(
                "[preday] %s 갭다운(%.1f%%) — 스킵",
                stock_code,
                gap_rate * 100,
            )
            skipped_gapdown += 1
            continue

        # 0 <= gap_rate < gap_threshold: 채택
        logger.info(
            "[preday] %s 조기 진입 채택 (gap=%.2f%%)",
            stock_code,
            gap_rate * 100,
        )
        entered += 1

    # REQ-042-007: 기존 execute_buy_orders 재사용 (BUY_CUTOFF, 한도/섹터/BEAR 게이트 포함)
    execute_result: dict = {}
    if entered > 0:
        try:
            execute_result = execute_buy_orders(db)
            logger.info("[preday] execute_buy_orders 완료: %s", execute_result)
        except Exception as exc:
            logger.exception("[preday] execute_buy_orders 실패: %s", exc)
            execute_result = {"error": str(exc)}

    return {
        "candidates": candidates,
        "entered": entered,
        "skipped_gapup": skipped_gapup,
        "skipped_gapdown": skipped_gapdown,
        "execute_result": execute_result,
    }
