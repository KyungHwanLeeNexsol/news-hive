# 동적 목표가/손절가 계산 서비스
# SPEC-AI-005: ATR 기반 변동성 적응형 TP/SL 시스템
"""동적 목표가/손절가 계산 서비스.

ATR(Average True Range) 기반으로 변동성을 반영하여
신뢰도별 TP/SL을 동적으로 계산한다.

폴백 우선순위:
  1. ATR 기반 계산 (정상)
  2. 섹터 기본값 (ATR 데이터 부족 시)
  3. 전체 기본값 (섹터 정보 없을 시)
"""

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ATR 승수 상수
# ---------------------------------------------------------------------------

# @MX:NOTE: 신뢰도별 ATR 승수 — SPEC-AI-005 요구사항
# @MX:SPEC: SPEC-AI-005

# 기본 승수 (신뢰도 0.5~0.79)
TARGET_ATR_DEFAULT: float = 2.0
STOP_ATR_DEFAULT: float = 1.5

# 고신뢰도 승수 (신뢰도 >= 0.8): 목표가 높임, 손절가 좁힘
TARGET_ATR_HIGH_CONF: float = 2.5
STOP_ATR_HIGH_CONF: float = 1.0

# 저신뢰도 승수 (신뢰도 < 0.5): 목표가 낮춤, 손절가 넓힘 (더 보수적)
TARGET_ATR_LOW_CONF: float = 1.5
STOP_ATR_LOW_CONF: float = 2.0

# 트레일링 스탑 승수
TRAILING_STOP_ATR_MULT: float = 1.5

# 트레일링 스탑 활성화 임계값 (+5% 수익)
TRAILING_STOP_ACTIVATION_PCT: float = 0.05

# ATR 캐시 TTL (1시간)
_ATR_CACHE_TTL: int = 3600

# 간단한 인메모리 ATR 캐시: {stock_code: (atr, timestamp)}
_atr_cache: dict[str, tuple[float, float]] = {}


# ---------------------------------------------------------------------------
# 섹터 기본값 매핑
# ---------------------------------------------------------------------------

# 섹터명 패턴 → (target_pct, stop_pct)
# 패턴 매칭 순서가 중요하므로 list of tuples 사용
_SECTOR_DEFAULTS: list[tuple[tuple[str, ...], float, float]] = [
    # 고변동 섹터
    (("바이오", "제약", "게임"), 0.15, 0.08),
    # 중고변동 섹터
    (("IT", "반도체", "2차전지", "배터리"), 0.12, 0.06),
    # 중변동 섹터
    (("제조", "건설", "화학"), 0.10, 0.05),
    # 저변동 섹터
    (("은행", "보험", "전력", "금융"), 0.06, 0.03),
]

# 기본값 (매칭 없음)
_DEFAULT_TARGET_PCT: float = 0.10
_DEFAULT_STOP_PCT: float = 0.05


def get_sector_defaults(sector_id: int | None, db: Session) -> dict[str, float]:
    """섹터별 기본 TP/SL 비율을 반환한다.

    Args:
        sector_id: 섹터 ID (None이면 전체 기본값)
        db: SQLAlchemy Session

    Returns:
        {"target_pct": float, "stop_pct": float}
    """
    if sector_id is None:
        return {"target_pct": _DEFAULT_TARGET_PCT, "stop_pct": _DEFAULT_STOP_PCT}

    try:
        from app.models.sector import Sector
        sector = db.query(Sector).filter(Sector.id == sector_id).first()
        if not sector:
            return {"target_pct": _DEFAULT_TARGET_PCT, "stop_pct": _DEFAULT_STOP_PCT}

        sector_name = sector.name or ""

        # 섹터명 패턴 매칭 (대소문자 무시)
        for keywords, target_pct, stop_pct in _SECTOR_DEFAULTS:
            if any(kw in sector_name for kw in keywords):
                return {"target_pct": target_pct, "stop_pct": stop_pct}

        return {"target_pct": _DEFAULT_TARGET_PCT, "stop_pct": _DEFAULT_STOP_PCT}

    except Exception as e:
        logger.warning("섹터 기본값 조회 실패 (sector_id=%s): %s", sector_id, e)
        return {"target_pct": _DEFAULT_TARGET_PCT, "stop_pct": _DEFAULT_STOP_PCT}


def calculate_trailing_stop(high_water_mark: int, atr: float) -> int:
    """트레일링 스탑 가격 계산.

    Args:
        high_water_mark: 포지션 보유 중 최고가
        atr: 현재 ATR 값

    Returns:
        트레일링 스탑 가격 (정수, 원화)
    """
    return high_water_mark - int(atr * TRAILING_STOP_ATR_MULT)


def should_activate_trailing_stop(entry_price: int, current_price: int) -> bool:
    """트레일링 스탑 활성화 여부 판단.

    진입가 대비 +5% 이상 수익 시 활성화한다.

    Args:
        entry_price: 진입가
        current_price: 현재가

    Returns:
        활성화 여부
    """
    if entry_price <= 0:
        return False
    profit_pct = (current_price - entry_price) / entry_price
    return profit_pct >= TRAILING_STOP_ACTIVATION_PCT


def should_recalculate_tp_sl(tp_sl_method: str | None) -> bool:
    """TP/SL 재계산 대상 여부 판단.

    ai_provided 방식은 AI가 직접 제공한 값이므로 재계산하지 않는다.

    Args:
        tp_sl_method: 현재 TP/SL 방식 ('ai_provided', 'legacy_fixed', None 등)

    Returns:
        True면 재계산 대상
    """
    # @MX:ANCHOR: AI 제공 TP/SL 보호 — 재계산 절대 금지
    # @MX:REASON: AI가 제공한 목표가/손절가는 맥락 정보를 담고 있어 임의 덮어쓰기 금지
    return tp_sl_method != "ai_provided"


def _get_atr_cache(stock_code: str) -> float | None:
    """ATR 캐시에서 값을 가져온다 (TTL 1시간)."""
    if stock_code in _atr_cache:
        cached_atr, cached_at = _atr_cache[stock_code]
        if time.time() - cached_at < _ATR_CACHE_TTL:
            return cached_atr
    return None


def _set_atr_cache(stock_code: str, atr: float) -> None:
    """ATR 캐시에 값을 저장한다."""
    _atr_cache[stock_code] = (atr, time.time())


async def calculate_dynamic_tp_sl(
    stock_code: str,
    entry_price: int,
    confidence: float,
    sector_id: int | None,
    db: Session,
) -> dict[str, Any]:
    """동적 TP/SL 계산 메인 함수.

    Args:
        stock_code: 종목코드 (예: '005930')
        entry_price: 진입가 (원)
        confidence: AI 신뢰도 (0.0~1.0)
        sector_id: 섹터 ID (섹터 기본값 폴백용)
        db: SQLAlchemy Session

    Returns:
        {
            "target_price": int,   # 목표가
            "stop_loss": int,      # 손절가
            "method": str,         # "atr_dynamic" | "sector_default"
        }

    Notes:
        - ATR 계산 실패 시 섹터 기본값으로 폴백
        - 결과 캐시: ATR 값은 1시간 인메모리 캐시
    """
    # 신뢰도별 ATR 승수 선택
    if confidence >= 0.8:
        target_mult = TARGET_ATR_HIGH_CONF
        stop_mult = STOP_ATR_HIGH_CONF
    elif confidence < 0.5:
        target_mult = TARGET_ATR_LOW_CONF
        stop_mult = STOP_ATR_LOW_CONF
    else:
        target_mult = TARGET_ATR_DEFAULT
        stop_mult = STOP_ATR_DEFAULT

    # ATR 계산 시도
    try:
        atr = await _fetch_atr(stock_code)
    except Exception as e:
        logger.warning("ATR 계산 실패 (%s): %s", stock_code, e)
        atr = None

    if atr is not None and atr > 0:
        # ATR 기반 동적 계산
        target_price = entry_price + int(atr * target_mult)
        stop_loss = entry_price - int(atr * stop_mult)
        logger.info(
            "ATR 동적 TP/SL 계산: %s, ATR=%.1f, target=%d, stop=%d",
            stock_code, atr, target_price, stop_loss,
        )
        return {
            "target_price": target_price,
            "stop_loss": stop_loss,
            "method": "atr_dynamic",
        }

    # ATR 실패 → 섹터 기본값 폴백
    sector_defaults = get_sector_defaults(sector_id, db)
    target_price = int(entry_price * (1 + sector_defaults["target_pct"]))
    stop_loss = int(entry_price * (1 - sector_defaults["stop_pct"]))
    logger.info(
        "섹터 기본값 폴백: %s, target=%d (%.0f%%), stop=%d (%.0f%%)",
        stock_code, target_price,
        sector_defaults["target_pct"] * 100,
        stop_loss,
        sector_defaults["stop_pct"] * 100,
    )
    return {
        "target_price": target_price,
        "stop_loss": stop_loss,
        "method": "sector_default",
    }


async def recalculate_legacy_positions(db: Session) -> dict:
    """레거시 포지션의 TP/SL을 동적 계산으로 재계산한다.

    조건:
    - tp_sl_method IS NULL OR tp_sl_method = 'legacy_fixed'
    - is_open = True (활성 포지션만)
    - tp_sl_method = 'ai_provided'는 절대 덮어쓰지 않음

    Returns:
        {"updated": int, "skipped": int, "errors": int}
    """
    from app.models.virtual_portfolio import VirtualTrade
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock

    stats = {"updated": 0, "skipped": 0, "errors": 0}

    # 레거시 오픈 포지션 조회
    open_trades = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.is_open.is_(True))
        .all()
    )

    for trade in open_trades:
        try:
            # 연결된 시그널의 tp_sl_method 확인
            signal = db.query(FundSignal).filter(FundSignal.id == trade.signal_id).first()
            signal_method = getattr(signal, "tp_sl_method", None) if signal else None

            # @MX:ANCHOR: ai_provided 보호 — 절대 덮어쓰지 않음
            # @MX:REASON: AI가 제공한 TP/SL은 맥락 정보가 있어 임의 재계산 금지
            if not should_recalculate_tp_sl(signal_method):
                stats["skipped"] += 1
                continue

            # 종목 정보 조회
            stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
            if not stock:
                stats["errors"] += 1
                continue

            confidence = float(signal.confidence) if signal and signal.confidence else 0.7

            # 동적 TP/SL 계산
            result = await calculate_dynamic_tp_sl(
                stock_code=stock.stock_code,
                entry_price=trade.entry_price,
                confidence=confidence,
                sector_id=stock.sector_id,
                db=db,
            )

            trade.target_price = result["target_price"]
            trade.stop_loss = result["stop_loss"]

            # 시그널의 tp_sl_method 업데이트
            if signal:
                try:
                    signal.tp_sl_method = result["method"]
                except Exception:
                    pass

            stats["updated"] += 1
            logger.info(
                "레거시 포지션 재계산: trade_id=%d, method=%s, target=%d, stop=%d",
                trade.id, result["method"], result["target_price"], result["stop_loss"],
            )

        except Exception as e:
            logger.warning("포지션 재계산 실패 (trade_id=%s): %s", trade.id, e)
            stats["errors"] += 1

    if stats["updated"] > 0:
        db.commit()

    logger.info("레거시 포지션 재계산 완료: %s", stats)
    return stats


async def _fetch_atr(stock_code: str) -> float | None:
    """종목의 ATR을 계산하여 반환한다 (캐시 우선).

    20일 가격 히스토리를 가져와 ATR을 계산한다.
    """
    # 캐시 확인
    cached = _get_atr_cache(stock_code)
    if cached is not None:
        return cached

    try:
        from app.services.naver_finance import fetch_stock_price_history
        from app.services.technical_indicators import calculate_atr

        # 20일 가격 히스토리 조회 (2페이지)
        price_records = await fetch_stock_price_history(stock_code, pages=2)
        if not price_records:
            return None

        # PriceRecord → dict 변환
        prices = [
            {"high": rec.high, "low": rec.low, "close": rec.close}
            for rec in price_records
            if rec.high > 0 and rec.low > 0 and rec.close > 0
        ]

        atr = calculate_atr(prices, period=14)
        if atr is not None and atr > 0:
            _set_atr_cache(stock_code, atr)
        return atr

    except Exception as e:
        logger.warning("ATR 조회 실패 (%s): %s", stock_code, e)
        return None
