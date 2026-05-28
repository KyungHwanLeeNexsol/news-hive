"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 서비스.

FundSignal(signal_type="surge_candidate") 시그널 기반 자동 매매 로직.
정규장(KST 평일 09:00~15:30) 시간대에만 매수/매도 실행.
"""
import asyncio
import json
import logging
import os as _os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import floor
from typing import Optional

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_portfolio import SurgePortfolio, SurgeTrade
from app.services.naver_finance import fetch_current_price as _fetch_current_price_async
from app.services.naver_finance import fetch_current_price_with_change as _fetch_price_with_change_async
from app.services.naver_finance import fetch_current_prices_batch as _fetch_prices_batch_async
from app.services.naver_finance import fetch_stock_price_history as _fetch_price_history_async

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)
BUY_CUTOFF = time(11, 0)        # 신규 진입 마감: 테마주 1차 파동 이후 추격 매수 차단
INTRADAY_CRASH_LIMIT = -3.0     # 전일비 -3% 이하: 테마 thesis 붕괴, 매수 제외
INTRADAY_OVERHEAT_LIMIT = 15.0  # 전일비 +15% 초과: 당일 이미 과열, 상단 매수 제외


def _get_current_price_sync(stock_code: str) -> Optional[int]:
    """async fetch_current_price를 sync 컨텍스트에서 실행하는 wrapper.

    # @MX:NOTE: [AUTO] asyncio.run()으로 async 가격 조회를 sync 서비스에서 사용하기 위한 어댑터
    # @MX:SPEC: SPEC-AI-013
    테스트에서는 이 함수를 직접 패치하여 async 복잡성 없이 모킹 가능.
    """
    try:
        return asyncio.run(_fetch_current_price_async(stock_code))
    except RuntimeError:
        # 이미 이벤트 루프가 실행 중인 경우 (비정상 컨텍스트)
        return None


def _get_price_with_change_sync(stock_code: str) -> tuple[Optional[int], float]:
    """현재가 + 전일비 등락률 반환. 조회 실패 시 (None, 0.0) 반환.

    # @MX:NOTE: [AUTO] 인트라데이 필터(급락/과열 감지)에 사용; check_exit_conditions는 _get_current_price_sync 유지
    # @MX:SPEC: SPEC-AI-014
    테스트에서는 이 함수를 직접 패치하여 모킹 가능.
    """
    try:
        result = asyncio.run(_fetch_price_with_change_async(stock_code))
        if result:
            return result["current_price"], result["change_rate"]
        return None, 0.0
    except RuntimeError:
        return None, 0.0
    except Exception:
        return None, 0.0


def _get_price_history_sync(stock_code: str) -> list:
    """async fetch_stock_price_history를 sync 컨텍스트에서 실행하는 wrapper.

    # @MX:NOTE: [AUTO] REQ-AI014-005 가격 모멘텀 사전 필터를 위한 가격 이력 조회 어댑터
    # @MX:SPEC: SPEC-AI-014
    테스트에서는 이 함수를 직접 패치하여 모킹 가능.
    """
    try:
        return asyncio.run(_fetch_price_history_async(stock_code, pages=1))
    except RuntimeError:
        return []
    except Exception:
        return []


def is_market_hours(now: Optional[datetime] = None) -> bool:
    # @MX:ANCHOR: [AUTO] 정규장 시간 가드 — 모든 매수/매도 실행의 전제 조건
    # @MX:REASON: [AUTO] execute_buy_orders, check_exit_conditions, 스케줄러 잡 등 3개 이상 컴포넌트에서 참조
    """KST 평일 09:00~15:30 여부 확인.

    매수/매도 주문은 정규장 시간 외에는 실행하지 않음 (큐잉 X, 단순 스킵).
    """
    now = now or datetime.now(KST)
    # 토요일(5), 일요일(6)은 휴장
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_buy_eligible_hours(now: Optional[datetime] = None, db: Optional[Session] = None) -> bool:
    """급등예측 신규 매수 가능 시간: KST 평일 09:00~11:00.

    테마주 급등 1차 파동은 09:00~10:30에 완성되므로 11:00 이후 신규 진입 차단.
    손절 복구: db가 제공되고 당일 손절이 발생한 경우 11:00~15:30 구간에서도 재진입 허용.
    종료 조건 체크(check_exit_conditions)는 MARKET_CLOSE(15:30)까지 계속 실행.
    """
    now = now or datetime.now(KST)
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    if MARKET_OPEN <= current_time <= BUY_CUTOFF:
        return True
    # 손절 복구: 당일 손절 발생 시 장 마감까지 재진입 허용
    if BUY_CUTOFF < current_time <= MARKET_CLOSE and db is not None:
        if _has_stop_loss_today(db):
            return True
    return False


def get_or_create_portfolio(db: Session) -> SurgePortfolio:
    """단일 SurgePortfolio 인스턴스 조회 또는 생성 (id=1)."""
    portfolio = db.query(SurgePortfolio).filter(SurgePortfolio.id == 1).first()
    if portfolio is None:
        portfolio = SurgePortfolio(
            initial_capital=Decimal("50000000"),
            current_cash=Decimal("50000000"),
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        logger.info("SurgePortfolio 인스턴스 생성 완료 (id=1)")
    return portfolio


def _get_prev_business_day(ref: date) -> date:
    """직전 영업일 반환. 토/일이면 금요일로 후퇴한다."""
    prev = ref - timedelta(days=1)
    while prev.weekday() >= 5:  # 5=토, 6=일
        prev -= timedelta(days=1)
    return prev


def get_today_signals(
    db: Session,
    min_probability: Decimal = Decimal("0.30"),
) -> list:
    """오늘 또는 직전 영업일 15:00 이후 생성된 surge_candidate 시그널 중 확률 임계값 이상 반환.

    FundSignal에는 stock_code 컬럼이 없으므로 Stock 테이블과 조인.
    surge_metadata JSON에서 surge_probability_score를 파싱하여 필터링.
    단일 탐지기만 발동(확률 < 0.40)한 저품질 신호는 매수 대상에서 제외.

    날짜 기준: 직전 영업일 15:00 KST 이후 생성된 시그널 포함.
    전일 15:20 스케줄러가 생성한 시그널을 익일 09:00 매수에 사용할 수 있도록
    단순 "당일" 필터에서 확장한다. 주말 처리: 월요일은 금요일 15:00 이후 포함.
    """
    now_kst = datetime.now(KST)
    today_kst = now_kst.date()

    # 직전 영업일 15:00 KST를 시그널 유효 기간 시작점으로 산정
    prev_bday = _get_prev_business_day(today_kst)
    signal_cutoff = datetime.combine(prev_bday, time(15, 0)).replace(tzinfo=KST)

    # surge_candidate 시그널 전체 조회 후 Python 레벨에서 날짜/확률 필터링
    # (created_at timezone 변환을 DB 레벨에서 하지 않아 안정성 확보)
    signals_with_stocks = (
        db.query(FundSignal, Stock)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(FundSignal.signal_type == "surge_candidate")
        .all()
    )

    # Python 레벨에서 날짜 필터 및 확률 필터 적용
    result = []
    for signal, stock in signals_with_stocks:
        # created_at 날짜(KST 변환) 체크
        if signal.created_at is not None:
            signal_date = signal.created_at
            # timezone-aware 처리
            if hasattr(signal_date, 'tzinfo') and signal_date.tzinfo is not None:
                signal_date_kst = signal_date.astimezone(KST)
            else:
                # naive datetime — UTC로 가정
                from datetime import timezone
                signal_date_kst = signal_date.replace(tzinfo=timezone.utc).astimezone(KST)
            # 직전 영업일 15:00 이전 시그널은 제외
            if signal_date_kst < signal_cutoff:
                continue
        else:
            continue

        # surge_metadata에서 확률 및 탐지기 목록 파싱
        probability, active_detectors = _parse_surge_metadata(signal.surge_metadata)
        if probability is None or probability < float(min_probability):
            continue

        # 단일 탐지기 필터: 하나만 발동 AND 확률 0.30 미만 → 저품질 신호 제외
        # REQ-AI014-004 컨센서스 보너스로 단일 탐지기 시그널도 0.30까지 허용 (기존 0.40에서 완화)
        if len(active_detectors) < 2 and probability < 0.30:
            logger.info(
                "surge signal 스킵(단일 탐지기): stock=%s 탐지기=%s probability=%.4f",
                stock.stock_code,
                active_detectors,
                probability,
            )
            continue

        # REQ-AI014-005: 가격 모멘텀 사전 필터
        # @MX:NOTE: [AUTO] 가격 모멘텀 사전 필터: 5일 +15% 초과(과열) 및 1일 -5% 미만(폭락) 종목 제외
        # @MX:SPEC: SPEC-AI-014 REQ-005
        stock_code_val = stock.stock_code
        try:
            price_history = _get_price_history_sync(stock_code_val)
            if price_history and len(price_history) >= 6:
                # Naver API는 내림차순(최신→과거) 반환: prices[0]이 최신가
                latest_price = float(price_history[0].close)
                price_5d_ago = float(price_history[5].close)
                price_1d_ago = float(price_history[1].close) if len(price_history) >= 2 else None

                if price_5d_ago and price_5d_ago > 0:
                    change_5d = (latest_price - price_5d_ago) / price_5d_ago
                    if change_5d > 0.15:
                        logger.info(
                            "surge signal 스킵(과열종목): stock=%s 5d_change=%.2f%%",
                            stock_code_val,
                            change_5d * 100,
                        )
                        continue

                if price_1d_ago and price_1d_ago > 0:
                    change_1d = (latest_price - price_1d_ago) / price_1d_ago
                    if change_1d < -0.05:
                        logger.info(
                            "surge signal 스킵(낙폭과대): stock=%s 1d_change=%.2f%%",
                            stock_code_val,
                            change_1d * 100,
                        )
                        continue
        except Exception:
            # 가격 데이터 조회 실패 시 필터 적용하지 않음 (통과)
            pass

        result.append((signal, stock, probability))

    # 확률 높은 순으로 정렬 — max_daily_entries 한도 내에서 최고 품질 종목 우선 매수
    result.sort(key=lambda x: x[2], reverse=True)
    return result


def _parse_surge_probability(surge_metadata: Optional[str]) -> Optional[float]:
    """surge_metadata JSON 문자열에서 surge_probability_score 파싱."""
    if not surge_metadata:
        return None
    try:
        data = json.loads(surge_metadata)
        score = data.get("surge_probability_score")
        if score is not None:
            return float(score)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def _parse_surge_metadata(surge_metadata: Optional[str]) -> tuple[Optional[float], list[str]]:
    """surge_metadata에서 (probability, active_detectors) 반환."""
    if not surge_metadata:
        return None, []
    try:
        data = json.loads(surge_metadata)
        score = data.get("surge_probability_score")
        basis = data.get("surge_basis") or []
        probability = float(score) if score is not None else None
        detectors = list(basis) if isinstance(basis, list) else []
        return probability, detectors
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, []


def _extract_detector_scores(surge_metadata: Optional[str]) -> dict[str, float]:
    """surge_metadata에서 탐지기별 점수 분해 반환 (SPEC-AI-016 REQ-002).

    # @MX:NOTE: [AUTO] SPEC-AI-016 탐지기별 분해 로그 — surge_metadata JSON에서 6개 점수 파싱
    # @MX:SPEC: SPEC-AI-016 REQ-002
    파싱 실패 또는 결측 시 모든 값 0.0으로 반환 (예외 전파 없음).

    Returns:
        {
            "theme": float,
            "volume": float,
            "disclosure": float,
            "immediate": float,
            "legacy": float,
            "total": float,
        }
    """
    default = {
        "theme": 0.0,
        "volume": 0.0,
        "disclosure": 0.0,
        "immediate": 0.0,
        "legacy": 0.0,
        "total": 0.0,
    }
    if not surge_metadata:
        return default
    try:
        data = json.loads(surge_metadata)
        return {
            "theme": float(data.get("theme_cluster_score", 0.0) or 0.0),
            "volume": float(data.get("combo_score", 0.0) or 0.0),
            "disclosure": float(data.get("pattern_score", 0.0) or 0.0),
            "immediate": float(data.get("immediate_disclosure_score", 0.0) or 0.0),
            "legacy": float(data.get("legacy_score", 0.0) or 0.0),
            "total": float(data.get("surge_probability_score", 0.0) or 0.0),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return default


def get_open_position(db: Session, stock_code: str) -> Optional[SurgeTrade]:
    """해당 종목의 오픈 포지션 조회 (중복 진입 차단용).

    Option B: SurgeTrade.is_open + stock_code 조합으로 중복 판단.
    FundSignal.paper_executed 미사용.
    """
    return (
        db.query(SurgeTrade)
        .filter(
            SurgeTrade.stock_code == stock_code,
            SurgeTrade.is_open.is_(True),
        )
        .first()
    )


def count_today_entries(db: Session, exclude_stop_loss: bool = False) -> int:
    """오늘(KST 기준) 진입한 포지션 수 (열린 포지션 + 당일 청산 포지션 모두 포함).

    exclude_stop_loss=True이면 당일 손절로 종료된 포지션은 카운트에서 제외하여
    손절 후 재진입 기회를 허용한다.
    """
    today_kst = datetime.now(KST).date()
    query = db.query(SurgeTrade).filter(SurgeTrade.entry_date == today_kst)
    if exclude_stop_loss:
        from sqlalchemy import or_
        query = query.filter(
            or_(
                SurgeTrade.is_open.is_(True),
                SurgeTrade.exit_reason != "stop_loss",
            )
        )
    return query.count()


def _has_stop_loss_today(db: Session) -> bool:
    """오늘(KST) 손절(stop_loss)로 종료된 포지션이 있으면 True 반환.

    손절 후 재진입 허용 여부 판단에 사용. is_buy_eligible_hours에서 참조.
    """
    today_kst = datetime.now(KST).date()
    return (
        db.query(SurgeTrade)
        .filter(
            SurgeTrade.exit_date == today_kst,
            SurgeTrade.exit_reason == "stop_loss",
        )
        .first()
    ) is not None


def count_open_positions(db: Session) -> int:
    """현재 오픈 포지션 수."""
    return (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(True))
        .count()
    )


def _get_open_sector_counts(db: Session) -> dict[str, int]:
    """현재 오픈 포지션의 섹터별 보유 수 반환.

    동일 섹터 집중 방지 필터(max_same_sector)에 사용.
    SurgeTrade(is_open=True) → Stock(stock_code) → Sector(sector_id) 순으로 조인.
    """
    from app.models.sector import Sector
    open_trades = db.query(SurgeTrade).filter(SurgeTrade.is_open.is_(True)).all()
    sector_counts: dict[str, int] = {}
    for trade in open_trades:
        stock = db.query(Stock).filter(Stock.stock_code == trade.stock_code).first()
        if stock and stock.sector_id:
            sector = db.query(Sector).filter(Sector.id == stock.sector_id).first()
            if sector:
                sector_counts[sector.name] = sector_counts.get(sector.name, 0) + 1
    return sector_counts


def _get_price_with_change_batch_sync(
    stock_codes: list[str],
    batch_size: int = 10,
    delay_sec: float = 0.5,
    retry_count: int = 1,
) -> dict[str, dict | None]:
    """배치 가격 조회 (sync wrapper for fetch_current_prices_batch).

    # @MX:NOTE: [AUTO] REQ-AI016-004 배치 가격 조회 sync 어댑터 — execute_buy_orders에서 사용
    # @MX:SPEC: SPEC-AI-016 REQ-004
    RuntimeError(이미 실행 중인 이벤트 루프) 발생 시 빈 dict 반환.
    """
    try:
        return asyncio.run(
            _fetch_prices_batch_async(stock_codes, batch_size=batch_size, delay_sec=delay_sec, retry_count=retry_count)
        )
    except RuntimeError:
        return {}


def _compute_sector_portfolio_pct(
    db: Session,
    sector_name: str,
    proposed_buy_amount: Decimal,
    price_cache: Optional[dict] = None,
) -> Decimal:
    """섹터 포트폴리오 비중 계산 (SPEC-AI-016 REQ-003).

    # @MX:NOTE: [AUTO] 섹터 비중 가드 핵심 계산. 폴백: 현재가 조회 실패 시 entry_price 사용
    # @MX:SPEC: SPEC-AI-016 REQ-003
    계산식:
        sector_value = Σ(해당 섹터 오픈 포지션) × 현재가(실패시 entry_price 폴백)
        total_value = portfolio.current_cash + Σ(전체 오픈 포지션 평가액)
        sector_portfolio_pct = (sector_value + proposed_buy_amount) / total_value

    Args:
        db: DB 세션
        sector_name: 검사할 섹터 이름
        proposed_buy_amount: 예상 매수 금액
        price_cache: 사전 조회된 가격 캐시 {stock_code: {"current_price": int, ...} | None}

    Returns:
        제안 매수 포함 섹터 비중 (0.0~1.0+)
    """
    from app.models.sector import Sector
    portfolio = get_or_create_portfolio(db)
    open_trades = db.query(SurgeTrade).filter(SurgeTrade.is_open.is_(True)).all()

    if not open_trades:
        # 포지션 없으면 비중 = proposed_buy_amount / (cash + proposed)
        total = portfolio.current_cash + proposed_buy_amount
        if total <= 0:
            return Decimal("0")
        return proposed_buy_amount / total

    # 전체 오픈 포지션 평가액 및 섹터별 평가액 계산
    total_positions_value = Decimal("0")
    sector_positions_value = Decimal("0")

    for trade in open_trades:
        # 현재가 조회 (캐시 우선)
        current_price: Optional[int] = None
        if price_cache is not None:
            cached = price_cache.get(trade.stock_code)
            if cached is not None:
                current_price = cached.get("current_price")

        if current_price is None:
            # 캐시 미스: 진입가 폴백
            trade_value = trade.entry_price * trade.quantity
        else:
            trade_value = Decimal(str(current_price)) * trade.quantity

        total_positions_value += trade_value

        # 해당 섹터 여부 확인
        stock_obj = db.query(Stock).filter(Stock.stock_code == trade.stock_code).first()
        if stock_obj and stock_obj.sector_id:
            sector_obj = db.query(Sector).filter(Sector.id == stock_obj.sector_id).first()
            if sector_obj and sector_obj.name == sector_name:
                sector_positions_value += trade_value

    total_value = portfolio.current_cash + total_positions_value
    if total_value <= 0:
        return Decimal("0")

    return (sector_positions_value + proposed_buy_amount) / total_value


# 섹터 포트폴리오 비중 최대값 (환경변수로 오버라이드 가능)
# @MX:NOTE: [AUTO] MAX_SECTOR_PORTFOLIO_PCT — 환경변수 SURGE_MAX_SECTOR_PORTFOLIO_PCT로 오버라이드 가능
_MAX_SECTOR_PCT_ENV = _os.environ.get("SURGE_MAX_SECTOR_PORTFOLIO_PCT")
MAX_SECTOR_PORTFOLIO_PCT = Decimal(_MAX_SECTOR_PCT_ENV) if _MAX_SECTOR_PCT_ENV else Decimal("0.40")


def execute_buy_orders(
    db: Session,
    max_daily_entries: int = 5,
    max_open_positions: int = 7,
    position_pct: Decimal = Decimal("0.14"),
    min_probability: Decimal = Decimal("0.30"),
    max_same_sector: int = 2,
) -> dict:
    # @MX:ANCHOR: [AUTO] 매수 실행 메인 함수 — 시그널 필터링부터 트랜잭션까지 전체 흐름 담당
    # @MX:REASON: [AUTO] 라우터(POST /surge/execute), 스케줄러(surge_execute_buys) 등 3개 이상 컴포넌트에서 참조
    """매수 실행 메인 함수.

    1. 정규장 시간 체크 (아닐 시 즉시 반환)
    2. 오늘 시그널 조회
    3. 임계값/중복/한도 필터링
    4. 각 시그널에 대해 매수 시도 (가격 조회 → 수량 계산 → 트랜잭션)
    5. 결과 요약 반환

    Returns: {"executed": int, "skipped": int, "failed": int, "details": list}
    """
    if not is_buy_eligible_hours(db=db):
        logger.debug("surge_execute_buys: 매수 가능 시간 외 — 스킵")
        return {"executed": 0, "skipped": 0, "failed": 0, "details": [], "reason": "market_closed"}

    portfolio = get_or_create_portfolio(db)
    today_signals = get_today_signals(db, min_probability=min_probability)

    today_count = count_today_entries(db, exclude_stop_loss=True)
    open_count = count_open_positions(db)
    sector_counts = _get_open_sector_counts(db)
    logger.info(
        "surge_execute_buys 시작 — 시그널=%d, 오픈포지션=%d/%d, 오늘진입=%d/%d",
        len(today_signals),
        open_count,
        max_open_positions,
        today_count,
        max_daily_entries,
    )

    # REQ-AI016-004: 전체 후보 가격 일괄 사전 조회 (배치 + 지연)
    all_stock_codes = [stock.stock_code for _, stock, _ in today_signals]
    price_cache: dict[str, dict | None] = {}
    if all_stock_codes:
        from app.surge_config.surge_settings import get_surge_config as _get_surge_config
        _cfg = _get_surge_config()
        _pq = _cfg.price_query
        price_cache = _get_price_with_change_batch_sync(
            all_stock_codes,
            batch_size=_pq.batch_size,
            delay_sec=_pq.batch_delay_sec,
            retry_count=_pq.retry_count,
        )
        logger.info(
            "surge_execute_buys 가격 사전 조회 완료 — 총 %d종목, 성공 %d종목",
            len(all_stock_codes),
            sum(1 for v in price_cache.values() if v is not None),
        )

    executed = 0
    skipped = 0
    failed = 0
    details = []

    for signal, stock, probability in today_signals:
        stock_code = stock.stock_code
        stock_name = stock.name

        # REQ-AI016-002: 탐지기별 점수 추출 (매 평가 시작 시점에 파싱)
        # @MX:NOTE: [AUTO] SPEC-AI-016 탐지기별 분해 로그 — 매 평가 종목마다 점수 파싱
        det = _extract_detector_scores(signal.surge_metadata)

        # 일일 최대 진입 한도 체크
        if today_count + executed >= max_daily_entries:
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=daily_limit",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "daily_limit"})
            continue

        # 동시 보유 한도 체크 (자본 보전: 항상 일부 현금 유지)
        if open_count + executed >= max_open_positions:
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=max_open_positions",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "max_open_positions"})
            continue

        # 동일 종목 오픈 포지션 중복 체크
        if get_open_position(db, stock_code):
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=duplicate_position",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "duplicate_position"})
            continue

        # 섹터 집중 필터: 동일 섹터 최대 max_same_sector개
        stock_obj = db.query(Stock).filter(Stock.stock_code == stock_code).first()
        sector_name: Optional[str] = None
        if stock_obj:
            from app.models.sector import Sector
            sector_obj = db.query(Sector).filter(Sector.id == stock_obj.sector_id).first()
            if sector_obj:
                sector_name = sector_obj.name
                current_sector_count = sector_counts.get(sector_name, 0)
                if current_sector_count >= max_same_sector:
                    logger.info(
                        "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=sector_concentration",
                        stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
                    )
                    skipped += 1
                    details.append({"stock_code": stock_code, "action": "skipped", "reason": "sector_concentration"})
                    continue

        # 투자금액 계산
        investment_amount = portfolio.initial_capital * position_pct

        # REQ-AI016-003: 섹터 포트폴리오 비중 가드
        if sector_name is not None:
            sector_pct = _compute_sector_portfolio_pct(
                db, sector_name, investment_amount, price_cache=price_cache
            )
            if sector_pct > MAX_SECTOR_PORTFOLIO_PCT:
                logger.info(
                    "[SURGE] %s skipped reason=sector_overweight sector_pct=%.2f limit=%.2f",
                    stock_code, float(sector_pct), float(MAX_SECTOR_PORTFOLIO_PCT),
                )
                logger.info(
                    "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=sector_overweight",
                    stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
                )
                skipped += 1
                details.append({"stock_code": stock_code, "action": "skipped", "reason": "sector_overweight"})
                continue

        # 섹터 카운터 증가 (루프 내 중복 방지) — 섹터 가드 통과 후 증가
        if sector_name is not None:
            sector_counts[sector_name] = sector_counts.get(sector_name, 0) + 1

        # 현금 부족 체크
        if portfolio.current_cash < investment_amount:
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=insufficient_cash",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "insufficient_cash"})
            continue

        # REQ-AI016-004: 가격 캐시에서 조회, 미존재/None 시 1회 재시도
        cached_price_data = price_cache.get(stock_code)
        if cached_price_data is not None:
            current_price = cached_price_data.get("current_price")
            change_rate = float(cached_price_data.get("change_rate", 0.0))
        else:
            # 캐시 미스: 1회 재시도 (REQ-004 retry_count)
            current_price, change_rate = _get_price_with_change_sync(stock_code)

        if current_price is None:
            logger.info(
                "[SURGE] %s failed score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=price_unavailable",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            failed += 1
            details.append({"stock_code": stock_code, "action": "failed", "reason": "price_unavailable"})
            continue

        # 당일 급락 중인 종목 제외 (테마 thesis 붕괴 방지)
        if change_rate < INTRADAY_CRASH_LIMIT:
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=intraday_crash",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "intraday_crash"})
            continue

        # 당일 과열 급등 종목 제외 (상단 매수 방지)
        if change_rate > INTRADAY_OVERHEAT_LIMIT:
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=intraday_overheat",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "intraday_overheat"})
            continue

        # 수량 계산 (floor 처리)
        quantity = floor(float(investment_amount) / float(current_price))
        if quantity <= 0:
            logger.info(
                "[SURGE] %s skipped score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=quantity_zero",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "quantity_zero"})
            continue

        actual_amount = Decimal(str(current_price)) * quantity

        # 원자적 트랜잭션: current_cash 차감 + SurgeTrade 생성
        try:
            portfolio.current_cash = portfolio.current_cash - actual_amount
            trade = SurgeTrade(
                portfolio_id=portfolio.id,
                stock_code=stock_code,
                stock_name=stock_name,
                signal_id=signal.id,
                entry_price=Decimal(str(current_price)),
                quantity=quantity,
                entry_date=datetime.now(KST).date(),
                is_open=True,
                surge_probability_score=Decimal(str(probability)),
            )
            db.add(trade)
            db.commit()
            db.refresh(portfolio)
            executed += 1
            _, trade_detectors = _parse_surge_metadata(signal.surge_metadata)
            # REQ-AI016-002: 매수 완료 분해 로그
            logger.info(
                "[SURGE] %s executed score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=ok",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"],
            )
            logger.info(
                "surge_execute_buys: %s(%s) 매수 완료 — 수량=%d, 단가=%s, 금액=%s, 확률=%.2f, 탐지기=%s",
                stock_name,
                stock_code,
                quantity,
                current_price,
                actual_amount,
                probability,
                trade_detectors,
            )
            details.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "action": "executed",
                "quantity": quantity,
                "entry_price": float(current_price),
                "amount": float(actual_amount),
                "probability": probability,
                "detectors": trade_detectors,
            })
        except Exception as e:
            db.rollback()
            logger.error("surge_execute_buys: %s 매수 트랜잭션 실패 — %s", stock_code, e)
            logger.info(
                "[SURGE] %s failed score=%.3f | theme=%.3f volume=%.3f disclosure=%.3f immediate=%.3f legacy=%.3f | reason=%s",
                stock_code, det["total"], det["theme"], det["volume"], det["disclosure"], det["immediate"], det["legacy"], str(e),
            )
            failed += 1
            details.append({"stock_code": stock_code, "action": "failed", "reason": str(e)})

    return {
        "executed": executed,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }


def calculate_trading_days_elapsed(
    entry_date: date,
    today: Optional[date] = None,
) -> int:
    """평일 카운팅 (단순화: 주말 제외, 공휴일 무시).

    entry_date 이후 today까지의 거래일(평일) 수를 반환.
    today <= entry_date 이면 0 반환.
    """
    today = today or datetime.now(KST).date()
    if today <= entry_date:
        return 0
    days = 0
    current = entry_date
    while current < today:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=월, 4=금
            days += 1
    return days


def execute_sell(
    db: Session,
    trade: SurgeTrade,
    exit_price: Decimal,
    exit_reason: str,
) -> SurgeTrade:
    """매도 실행 (원자적 트랜잭션: is_open=False + current_cash 가산).

    Args:
        db: DB 세션
        trade: 매도할 SurgeTrade 인스턴스
        exit_price: 매도가
        exit_reason: 종료 사유 ("stop_loss"|"take_profit"|"max_holding_period"|"manual")

    Returns:
        업데이트된 SurgeTrade 인스턴스
    """
    portfolio = db.query(SurgePortfolio).filter(SurgePortfolio.id == trade.portfolio_id).first()
    if portfolio is None:
        raise ValueError(f"SurgePortfolio(id={trade.portfolio_id}) not found")

    proceeds = exit_price * trade.quantity
    portfolio.current_cash = portfolio.current_cash + proceeds

    trade.is_open = False
    trade.exit_date = datetime.now(KST).date()
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason

    db.commit()
    db.refresh(trade)

    pnl_pct = (float(exit_price) - float(trade.entry_price)) / float(trade.entry_price) * 100
    logger.info(
        "surge 매도 완료: %s(%s) exit_reason=%s, 단가=%s, 수익률=%.2f%%",
        trade.stock_name,
        trade.stock_code,
        exit_reason,
        exit_price,
        pnl_pct,
    )
    return trade


def check_exit_conditions(
    db: Session,
    stop_loss_pct: Decimal = Decimal("-0.05"),
    take_profit_pct: Decimal = Decimal("0.09"),
    max_holding_days: int = 3,
) -> dict:
    # @MX:ANCHOR: [AUTO] 종료 조건 체크 메인 함수 — 손절/익절/만기 모든 종료 로직 담당
    # @MX:REASON: [AUTO] 라우터, 스케줄러(surge_check_exits) 등 3개 이상 컴포넌트에서 참조
    """종료 조건 체크 메인 함수.

    1. 정규장 시간 체크 (아닐 시 즉시 반환)
    2. 모든 is_open=True 포지션 순회
    3. 현재가 조회 → PnL 계산
    4. 손절/익절/만기 조건 체크 → 매도 실행
    5. 결과 요약 반환

    Returns: {"closed": int, "still_open": int, "errors": int, "details": list}
    """
    if not is_market_hours():
        logger.debug("surge_check_exits: 정규장 시간 외 — 스킵")
        return {"closed": 0, "still_open": 0, "errors": 0, "details": [], "reason": "market_closed"}

    open_trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(True))
        .all()
    )

    closed = 0
    errors = 0
    still_open = 0
    details = []
    today = datetime.now(KST).date()

    for trade in open_trades:
        # 현재가 조회
        current_price = _get_current_price_sync(trade.stock_code)
        if current_price is None:
            logger.warning(
                "surge_check_exits: %s 현재가 조회 실패 — 다음 사이클로 연기",
                trade.stock_code,
            )
            errors += 1
            details.append({
                "stock_code": trade.stock_code,
                "action": "deferred",
                "reason": "price_fetch_failed",
            })
            continue

        entry_price = float(trade.entry_price)
        curr_price = float(current_price)
        pnl_pct = (curr_price - entry_price) / entry_price

        exit_reason = None

        # 손절 조건
        if Decimal(str(pnl_pct)) <= stop_loss_pct:
            exit_reason = "stop_loss"
        # 익절 조건
        elif Decimal(str(pnl_pct)) >= take_profit_pct:
            exit_reason = "take_profit"
        # 최대 보유 기간 초과
        elif calculate_trading_days_elapsed(trade.entry_date, today) >= max_holding_days:
            exit_reason = "max_holding_period"

        if exit_reason:
            try:
                execute_sell(db, trade, Decimal(str(current_price)), exit_reason)
                closed += 1
                details.append({
                    "stock_code": trade.stock_code,
                    "action": "closed",
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "exit_price": curr_price,
                })
            except Exception as e:
                db.rollback()
                logger.error(
                    "surge_check_exits: %s 매도 실패 — %s", trade.stock_code, e
                )
                errors += 1
                details.append({
                    "stock_code": trade.stock_code,
                    "action": "error",
                    "reason": str(e),
                })
        else:
            still_open += 1

    return {
        "closed": closed,
        "still_open": still_open,
        "errors": errors,
        "details": details,
    }


def get_portfolio_stats(db: Session) -> dict:
    """포트폴리오 통계 계산.

    현재가 조회를 통해 오픈 포지션 평가액을 계산한다.
    현재가 조회 실패 시 진입가 기준으로 fallback.
    """
    portfolio = get_or_create_portfolio(db)

    open_trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.portfolio_id == portfolio.id, SurgeTrade.is_open.is_(True))
        .all()
    )
    closed_count = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.portfolio_id == portfolio.id, SurgeTrade.is_open.is_(False))
        .count()
    )

    open_positions_value = Decimal("0")
    for trade in open_trades:
        current_price = _get_current_price_sync(trade.stock_code)
        if current_price is not None:
            open_positions_value += Decimal(str(current_price)) * trade.quantity
        else:
            # 현재가 조회 실패 시 진입가 기준
            open_positions_value += trade.entry_price * trade.quantity

    current_value = portfolio.current_cash + open_positions_value
    return_pct = (
        float(current_value - portfolio.initial_capital)
        / float(portfolio.initial_capital)
        * 100
        if float(portfolio.initial_capital) > 0
        else 0.0
    )

    return {
        "initial_capital": portfolio.initial_capital,
        "current_cash": portfolio.current_cash,
        "open_positions_value": open_positions_value,
        "current_value": current_value,
        "return_pct": round(return_pct, 4),
        "total_trades_count": len(open_trades) + closed_count,
        "open_positions_count": len(open_trades),
        "closed_trades_count": closed_count,
    }


def get_open_positions_detail(db: Session) -> list:
    """보유 포지션 상세 (현재가, PnL% 포함).

    현재가 조회 실패 시 current_price=None으로 반환.
    """
    open_trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(True))
        .order_by(SurgeTrade.entry_date.desc())
        .all()
    )

    result = []
    today = datetime.now(KST).date()
    for trade in open_trades:
        current_price = _get_current_price_sync(trade.stock_code)
        pnl_pct = None
        if current_price is not None:
            pnl_pct = (
                (float(current_price) - float(trade.entry_price))
                / float(trade.entry_price)
                * 100
            )
        days_held = calculate_trading_days_elapsed(trade.entry_date, today)
        total_investment = trade.entry_price * trade.quantity
        current_price_dec = Decimal(str(current_price)) if current_price else None
        current_value = current_price_dec * trade.quantity if current_price_dec is not None else None
        result.append({
            "id": trade.id,
            "stock_code": trade.stock_code,
            "stock_name": trade.stock_name,
            "entry_price": trade.entry_price,
            "current_price": current_price_dec,
            "quantity": trade.quantity,
            "total_investment": total_investment,
            "current_value": current_value,
            "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
            "entry_date": trade.entry_date,
            "days_held": days_held,
            "surge_probability_score": trade.surge_probability_score,
        })
    return result


def get_closed_trades(db: Session, limit: int = 20, offset: int = 0) -> dict:
    """종료 거래 이력 (페이징)."""
    total = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(False))
        .count()
    )
    trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(False))
        .order_by(SurgeTrade.exit_date.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    items = []
    for trade in trades:
        pnl_pct = None
        holding_days = None
        if trade.exit_price is not None:
            pnl_pct = round(
                (float(trade.exit_price) - float(trade.entry_price))
                / float(trade.entry_price)
                * 100,
                4,
            )
        if trade.exit_date is not None:
            holding_days = calculate_trading_days_elapsed(trade.entry_date, trade.exit_date)

        items.append({
            "id": trade.id,
            "stock_code": trade.stock_code,
            "stock_name": trade.stock_name,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "quantity": trade.quantity,
            "entry_date": trade.entry_date,
            "exit_date": trade.exit_date,
            "exit_reason": trade.exit_reason,
            "pnl_pct": pnl_pct,
            "holding_days": holding_days,
            "surge_probability_score": trade.surge_probability_score,
        })

    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_performance_timeseries(db: Session, days: int = 30) -> list:
    """누적 수익률 시계열 (days일 단위).

    각 날짜의 누적 수익률(%)을 계산하여 반환한다.
    종료 거래의 entry/exit를 기준으로 일별 손익을 계산한다.
    """
    portfolio = get_or_create_portfolio(db)
    today = datetime.now(KST).date()
    start_date = today - timedelta(days=days)

    # 시작일 이후 종료된 거래만 조회
    closed_trades = (
        db.query(SurgeTrade)
        .filter(
            SurgeTrade.portfolio_id == portfolio.id,
            SurgeTrade.is_open.is_(False),
            SurgeTrade.exit_date >= start_date,
        )
        .order_by(SurgeTrade.exit_date)
        .all()
    )

    # 날짜별 손익 집계
    daily_pnl: dict[date, float] = {}
    for trade in closed_trades:
        if trade.exit_date and trade.exit_price:
            pnl = (float(trade.exit_price) - float(trade.entry_price)) * trade.quantity
            daily_pnl[trade.exit_date] = daily_pnl.get(trade.exit_date, 0.0) + pnl

    # 시계열 생성
    result = []
    cumulative_pnl = 0.0
    initial_capital = float(portfolio.initial_capital)

    current = start_date
    while current <= today:
        pnl = daily_pnl.get(current, 0.0)
        cumulative_pnl += pnl
        cumulative_return_pct = (
            cumulative_pnl / initial_capital * 100 if initial_capital > 0 else 0.0
        )
        result.append({
            "date": current.isoformat(),
            "daily_pnl": round(pnl, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "cumulative_return_pct": round(cumulative_return_pct, 4),
        })
        current += timedelta(days=1)

    return result
