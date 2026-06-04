"""SPEC-AI-029: 적응형 surge 확률 임계값 산출 서비스.

직전 5거래 승률, 시장 레짐 배율, 최종 클램프를 조합하여
동적으로 임계값을 산출하고 surge_threshold_history 테이블에 저장한다.

임계값 산출은 시그널 생성 시점(15:20 배치)에 1회 실행되며
매수 실행 시점(9:05 배치)에는 저장된 값을 읽는다.
"""

import logging
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.surge_threshold_history import SurgeThresholdHistory
from app.services.market_regime_service import get_or_create_today_regime

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def _get_recent_closed_trades(db: Session, window: int) -> list:
    """최근 window개 종료 거래를 조회한다.

    SurgeTrade 중 is_open=False인 레코드를 entry_date 내림차순으로 window개 반환한다.
    """
    from app.models.surge_portfolio import SurgeTrade

    return (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open == False)  # noqa: E712
        .order_by(SurgeTrade.entry_date.desc())
        .limit(window)
        .all()
    )


def _compute_win_rate(trades: list) -> Optional[float]:
    """종료 거래 목록에서 승률을 계산한다.

    승리 조건: exit_reason == "take_profit" (익절)
    패배 조건: exit_reason in {"stop_loss", "max_holding_period"} (손절/기간 초과)

    Args:
        trades: SurgeTrade 목록 (is_open=False)

    Returns:
        승률 float (0.0~1.0) 또는 None (거래 없음)
    """
    if not trades:
        return None

    wins = sum(1 for t in trades if t.exit_reason == "take_profit")
    return wins / len(trades)


def compute_adaptive_threshold(db: Session, config) -> float:
    """적응형 임계값을 산출한다.

    # @MX:ANCHOR: [AUTO] 적응형 임계값 산출 핵심 함수 — fund_manager, surge_threshold_service에서 호출
    # @MX:REASON: SPEC-AI-029 REQ-AI029-001~004 전체 로직을 구현하는 단일 진입점

    산출 순서:
      1. 기본값: ensemble.min_score_for_signal
      2. 직전 N거래 승률 < win_rate_floor → +win_rate_addition, win_rate_cap 상한
      3. 레짐 배율 적용
      4. 최종 클램프 [final_clamp_min, final_clamp_max]

    enabled=False이면 기본값을 그대로 반환한다.

    Args:
        db: SQLAlchemy 세션
        config: SurgeDetectionConfig 인스턴스

    Returns:
        산출된 임계값 float
    """
    cfg = config.adaptive_threshold
    base = config.ensemble.min_score_for_signal

    # enabled=False이면 정적 임계값 반환
    if not cfg.enabled:
        logger.debug("[임계값] adaptive_threshold disabled — 정적 기본값 %.3f 사용", base)
        return base

    threshold = base
    reasons = []

    # 1단계: 직전 N거래 승률 체크
    trades = _get_recent_closed_trades(db, cfg.win_rate_window)
    win_rate: Optional[float] = None

    if len(trades) < cfg.win_rate_window:
        # 거래 데이터 부족 — 승률 조정 없음
        reasons.append(f"거래_부족({len(trades)}/{cfg.win_rate_window})")
    else:
        win_rate = _compute_win_rate(trades)
        if win_rate is not None and win_rate < cfg.win_rate_floor:
            threshold += cfg.win_rate_addition
            # 승률 상한 클램프
            threshold = min(threshold, cfg.win_rate_cap)
            reasons.append(f"승률낮음({win_rate:.2f}<{cfg.win_rate_floor}) +{cfg.win_rate_addition}")
        else:
            reasons.append(f"승률정상({win_rate:.2f})")

    # 2단계: 시장 레짐 배율 적용
    regime_str: Optional[str] = None
    try:
        regime_obj = get_or_create_today_regime(db)
        if regime_obj is not None:
            regime_str = regime_obj.regime.value
            multiplier = cfg.regime_multipliers.get(regime_str, 1.0)
            threshold *= multiplier
            reasons.append(f"레짐({regime_str}x{multiplier})")
        else:
            reasons.append("레짐_없음(x1.0)")
    except Exception as exc:
        logger.warning("[임계값] 레짐 조회 실패 — 배율 1.0 적용: %s", exc)
        reasons.append("레짐_오류(x1.0)")

    # 3단계: 최종 클램프
    threshold = max(cfg.final_clamp_min, min(cfg.final_clamp_max, threshold))
    _reason_str = ", ".join(reasons)

    logger.info(
        "[임계값] 적응형 산출 완료: %.3f (기본=%.3f, 승률=%s, 레짐=%s)",
        threshold,
        base,
        f"{win_rate:.2f}" if win_rate is not None else "N/A",
        regime_str or "N/A",
    )

    return threshold


def persist_threshold(
    db: Session,
    threshold_date: date,
    threshold: float,
    win_rate: Optional[float],
    regime: Optional[str],
    reason: Optional[str],
) -> SurgeThresholdHistory:
    """임계값을 surge_threshold_history 테이블에 upsert한다.

    date 컬럼의 UNIQUE 제약 덕분에 동일 날짜 재실행 시 기존 레코드를 갱신한다
    (idempotent 보장).

    Args:
        db: SQLAlchemy 세션
        threshold_date: 임계값 날짜 (KST)
        threshold: 산출된 임계값
        win_rate: 직전 5거래 승률 (없으면 None)
        regime: 시장 레짐 문자열 (없으면 None)
        reason: 산출 사유 문자열

    Returns:
        저장된 SurgeThresholdHistory 인스턴스
    """
    stmt = (
        pg_insert(SurgeThresholdHistory)
        .values(
            date=threshold_date,
            threshold=threshold,
            win_rate_5d=win_rate,
            regime=regime,
            reason=reason,
            created_at=datetime.now(_KST),
        )
        .on_conflict_do_update(
            index_elements=["date"],
            set_={
                "threshold": threshold,
                "win_rate_5d": win_rate,
                "regime": regime,
                "reason": reason,
                "created_at": datetime.now(_KST),
            },
        )
        .returning(SurgeThresholdHistory)
    )
    result = db.execute(stmt)
    _row = result.fetchone()
    db.flush()
    logger.info(
        "[임계값] surge_threshold_history upsert 완료 — date=%s, threshold=%.3f",
        threshold_date,
        threshold,
    )
    # returning으로 가져온 row를 ORM 객체로 변환
    return db.query(SurgeThresholdHistory).filter(
        SurgeThresholdHistory.date == threshold_date
    ).first()


def get_today_threshold(db: Session, config) -> float:
    """오늘 날짜의 저장된 임계값을 반환한다.

    # @MX:ANCHOR: [AUTO] execute_buy_orders에서 호출하는 임계값 조회 함수
    # @MX:REASON: SPEC-AI-029 REQ-AI029-006 — 매수 실행 시 재산출 없이 저장 값 사용

    DB에 오늘 레코드가 없으면 기본값(ensemble.min_score_for_signal)을 반환한다.

    Args:
        db: SQLAlchemy 세션
        config: SurgeDetectionConfig 인스턴스

    Returns:
        임계값 float
    """
    today = datetime.now(_KST).date()
    row = db.query(SurgeThresholdHistory).filter(
        SurgeThresholdHistory.date == today
    ).first()

    if row is not None and isinstance(row, SurgeThresholdHistory):
        try:
            val = float(row.threshold)
            logger.debug("[임계값] DB에서 오늘 임계값 로드: %.3f", val)
            return val
        except (TypeError, ValueError):
            logger.debug("[임계값] row.threshold float 변환 실패 — fallback 사용")
            pass

    # 오늘 레코드 없음 — 기본값 사용
    fallback = config.ensemble.min_score_for_signal
    logger.info(
        "[임계값] 오늘 임계값 레코드 없음 — 기본값 %.3f 사용 (시그널 생성 미실행?)",
        fallback,
    )
    return fallback


def is_combo_theme_gate_passed(surge_metadata: Optional[dict], config) -> bool:
    """combo_score=0.0 AND theme_cluster_score < floor 조합 게이트 검사.

    # @MX:NOTE: [AUTO] SPEC-AI-029 REQ-AI029-003 — combo/theme 조합 불량 종목 필터
    # @MX:NOTE: [AUTO] SPEC-AI-037 REQ-037-002/005 — 과열 시 원래 floor 적용, 비테마 fast path 추가
    # @MX:SPEC: SPEC-AI-029, SPEC-AI-037
    # @MX:WARN: [AUTO] 조건부 분기가 복수 SPEC에 걸쳐 있음 — floor 값 변경 시 과열 기준(0.7)도 함께 검토
    # @MX:REASON: combo_zero_theme_floor 완화(0.7→0.55) 시 과열 종목이 통과되지 않도록 원래 0.7 적용

    combo_score가 0.0이고 theme_cluster_score가 effective_floor 미만이면
    False를 반환하여 해당 종목을 매수 대상에서 제외한다.

    SPEC-AI-037 변경사항:
    - 과열(volume_z_score >= 3.0) 시 원래 floor 0.7 적용 (완화 적용 안 함)
    - 비테마(combo_score=0.0, theme_cluster_score=0.0) + 강한 공시/거래량 신호 시 fast path 통과

    Args:
        surge_metadata: FundSignal.surge_metadata 딕셔너리 (None 허용)
        config: SurgeDetectionConfig 인스턴스

    Returns:
        True이면 게이트 통과 (매수 허용), False이면 게이트 불통과 (제외)
    """
    # --- 메타데이터 전처리 ---
    if surge_metadata is None:
        # 메타데이터 없음 — 레거시 시그널로 간주, 게이트 통과
        return True

    # combo_score 키가 없는 경우: 레거시 시그널(SPEC-AI-029 이전 생성) → 게이트 미적용
    if "combo_score" not in surge_metadata:
        return True

    try:
        combo_score = float(surge_metadata.get("combo_score", 0.0))
    except Exception:
        combo_score = 0.0
    try:
        theme_score = float(surge_metadata.get("theme_cluster_score", 0.0))
    except Exception:
        theme_score = 0.0

    # combo_score > 0이면 게이트 적용 안 함
    if combo_score > 0.0:
        return True

    # --- SPEC-AI-037 REQ-037-002b: 과열 여부 판단 ---
    # volume_z_score >= 3.0 이면 완화된 floor 대신 원래 0.7 적용
    _OVERHEAT_Z_THRESHOLD = 3.0
    _ORIGINAL_FLOOR = 0.7
    try:
        volume_z = float(surge_metadata.get("volume_z_score", 0.0))
        is_overheat = volume_z >= _OVERHEAT_Z_THRESHOLD
    except Exception:
        is_overheat = False

    effective_floor = _ORIGINAL_FLOOR if is_overheat else config.adaptive_threshold.combo_zero_theme_floor

    # --- SPEC-AI-037 REQ-037-005: 비테마 fast path ---
    # combo=0.0, theme=0.0인 순수 비테마 종목에 대해 강한 공시/거래량 신호가 있으면 통과
    if combo_score == 0.0 and theme_score == 0.0:
        try:
            disclosure_score = float(surge_metadata.get("disclosure_pattern_score", 0.0))
            volume_news_score = float(surge_metadata.get("volume_news_combo_score", 0.0))
            # 강한 공시 신호: disclosure_pattern_score >= 0.70
            if disclosure_score >= 0.70:
                return True
            # 강한 거래량+뉴스 신호: volume_news_combo_score >= 0.80 AND 비과열
            if volume_news_score >= 0.80 and not is_overheat:
                return True
        except Exception:
            # 예외 발생 시 fast path 생략, 기존 로직으로 계속
            pass

    # combo_score == 0.0 인 경우: theme_score가 effective_floor 이상이어야 통과
    return theme_score >= effective_floor
