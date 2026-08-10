"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 API 라우터.

/surge prefix 하에 5개 엔드포인트 제공.
POST /surge/execute는 관리자 인증 필요.
"""
import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/surge-trading", tags=["Surge Trading"])


def _require_admin(request: Request) -> None:
    """관리자 인증 의존성.

    ks200_trading 라우터와 동일한 인메모리 토큰 방식 사용.
    Authorization: Bearer <token> 헤더를 검증한다.
    """
    from app.routers.auth import _verify_admin_token

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    token = auth[7:]
    if not _verify_admin_token(token):
        raise HTTPException(status_code=401, detail="인증 토큰이 만료되었거나 유효하지 않습니다.")


@router.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    """포트폴리오 통계 조회.

    현재 자산 평가액, 현금, 수익률, 총 거래수 등을 반환한다.
    """
    try:
        from app.services.surge_trading_service import get_portfolio_stats
        return get_portfolio_stats(db)
    except Exception as e:
        logger.error("Surge 포트폴리오 통계 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="포트폴리오 조회 실패")


@router.get("/positions")
def get_positions(db: Session = Depends(get_db)):
    """보유 포지션 목록 조회 (현재가, PnL% 포함)."""
    try:
        from app.services.surge_trading_service import get_open_positions_detail
        return get_open_positions_detail(db)
    except Exception as e:
        logger.error("Surge 포지션 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="포지션 조회 실패")


@router.get("/trades")
def get_trades(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """종료 거래 이력 조회 (페이징)."""
    try:
        from app.services.surge_trading_service import get_closed_trades
        return get_closed_trades(db, limit=limit, offset=offset)
    except Exception as e:
        logger.error("Surge 거래 이력 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="거래 이력 조회 실패")


@router.get("/performance")
def get_performance(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """누적 수익률 시계열 조회."""
    try:
        from app.services.surge_trading_service import get_performance_timeseries
        return get_performance_timeseries(db, days=days)
    except Exception as e:
        logger.error("Surge 성과 시계열 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="성과 시계열 조회 실패")


# SPEC-AI-022: 커버리지 대시보드 엔드포인트 (인증 불필요)
@router.get("/coverage")
def get_coverage_dashboard(db: Session = Depends(get_db)):
    """시그널 커버리지 대시보드 조회.

    오늘 생성된 시그널 수, 커버리지 비율, signal_type별 집계,
    미커버 상위 종목(시총 >= 1000억, 등락률 >= 15%)을 반환한다.
    60초 인메모리 캐시 적용.
    """
    try:
        from app.services.surge_coverage_service import compute_coverage_dashboard
        from app.schemas.surge_trading_coverage import CoverageDashboardResponse

        data = compute_coverage_dashboard(db)
        return CoverageDashboardResponse.model_validate(data)
    except Exception as e:
        logger.error("커버리지 대시보드 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="커버리지 대시보드 조회 실패")


@router.get("/threshold-status")
def get_threshold_status(db: Session = Depends(get_db)):
    """SPEC-AI-029: 오늘 적응형 임계값 상태 조회.

    오늘 날짜의 surge_threshold_history 레코드를 반환한다.
    레코드가 없으면 computed_today=false로 응답한다.

    Returns:
        {
            "date": "2026-06-02",
            "threshold": 0.495,
            "win_rate_5d": 0.6,
            "regime": "BULL",
            "reason": "...",
            "computed_today": true,
            "fallback_threshold": 0.45
        }
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZoneInfo

    _kst = _ZoneInfo("Asia/Seoul")
    today = _dt.now(_kst).date()

    try:
        from app.models.surge_threshold_history import SurgeThresholdHistory
        from app.surge_config.surge_settings import get_surge_config as _get_cfg
        from app.services.surge_threshold_service import compute_adaptive_threshold as _compute

        _cfg = _get_cfg()
        fallback = _cfg.ensemble.min_score_for_signal

        row = db.query(SurgeThresholdHistory).filter(
            SurgeThresholdHistory.date == today
        ).first()

        if row:
            return {
                "date": str(row.date),
                "threshold": row.threshold,
                "win_rate_5d": row.win_rate_5d,
                "regime": row.regime,
                "reason": row.reason,
                "computed_today": True,
                "fallback_threshold": fallback,
            }
        else:
            # 오늘 레코드 없음 — 실시간 산출값 포함하여 응답
            computed = _compute(db, _cfg)
            return {
                "date": str(today),
                "threshold": None,
                "win_rate_5d": None,
                "regime": None,
                "reason": None,
                "computed_today": False,
                "fallback_threshold": fallback,
                "computed_if_run_now": computed,
            }
    except Exception as e:
        logger.error("임계값 상태 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="임계값 상태 조회 실패")


@router.post("/execute")
def trigger_execute(
    request: Request,
    db: Session = Depends(get_db),
):
    """관리자 수동 매수 트리거.

    유효한 관리자 토큰이 없으면 401 반환.
    """
    _require_admin(request)
    try:
        from app.services.surge_trading_service import execute_buy_orders
        result = execute_buy_orders(db)
        logger.info(
            "Surge 수동 매수 트리거: executed=%d, skipped=%d, failed=%d",
            result["executed"],
            result["skipped"],
            result["failed"],
        )
        return result
    except Exception as e:
        logger.error("Surge 수동 매수 트리거 실패: %s", e)
        raise HTTPException(status_code=500, detail="매수 실행 실패")


# ---------------------------------------------------------------------------
# SPEC-AI-041: 급등 예측 평가 및 자동 개선 이력 조회 엔드포인트
# ---------------------------------------------------------------------------

@router.get("/evaluation")
def get_evaluations(
    days: int = Query(10, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """최근 N일 급등 예측 평가 결과 목록을 반환한다.

    Returns:
        SurgePredictionEvaluation 레코드 목록 (evaluation_date 내림차순)
    """
    try:
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        rows = (
            db.query(SurgePredictionEvaluation)
            .order_by(SurgePredictionEvaluation.evaluation_date.desc())
            .limit(days)
            .all()
        )
        return [_evaluation_list_item(row, db=db) for row in rows]
    except Exception as e:
        logger.error("급등 예측 평가 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="평가 목록 조회 실패")


# @MX:NOTE: [AUTO] SPEC-AI-088 REQ-AI088-004 — surge_metadata에서 pre_signal_change_pct를
#   안전하게 추출하는 순수 함수. surge_evaluation_service._is_same_day_event_horizon_signal과
#   동일한 fail-safe JSON 파싱 패턴(파싱 실패/비-dict/키 부재 → None)을 따르며, 기존 판별
#   함수(_is_same_day_event_horizon_signal/_is_near_limit_up_carry_signal)를 호출하거나
#   변경하지 않는다(부가 전용, Option A — 측정만).
# @MX:SPEC: SPEC-AI-088 REQ-AI088-004
def _extract_pre_signal_change_pct(surge_metadata_json: str | None) -> float | None:
    """surge_metadata JSON에서 pre_signal_change_pct 값을 안전하게 추출한다.

    파싱 실패/비-dict/키 부재/비수치 값이면 예외 없이 None을 반환한다.
    """
    if not surge_metadata_json:
        return None
    try:
        metadata = json.loads(surge_metadata_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("pre_signal_change_pct")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _compute_market_recall(row) -> float | None:
    """TP/전체 actual_surge_count 기준 시장 전체 recall을 계산한다."""
    actual_count = int(row.actual_surge_count or 0)
    if actual_count <= 0:
        return None
    return int(row.true_positive or 0) / actual_count


def _compute_market_f1(row, market_recall: float | None) -> float | None:
    """기존 precision과 시장 recall 기준 F1을 계산한다."""
    precision = row.precision
    if precision is None or market_recall is None:
        return None
    denom = precision + market_recall
    if denom <= 0:
        return 0.0
    return 2 * precision * market_recall / denom


def _evaluation_metric_fields(row) -> dict:
    # @MX:NOTE: [AUTO] SPEC-AI-110 — 기존 recall 컬럼은 scannable recall로 저장될 수
    # 있어 API 소비자가 시장 전체 recall로 오독하기 쉽다. 하위호환을 위해 recall 필드는
    # 유지하고, count 기반 market_recall과 basis 필드를 병렬 노출한다.
    # @MX:SPEC: SPEC-AI-110 REQ-AI110-001
    market_recall = _compute_market_recall(row)
    recall_basis = "scannable" if row.scannable_recall is not None else "market"
    return {
        "market_recall": market_recall,
        "market_f1_score": _compute_market_f1(row, market_recall),
        "recall_basis": recall_basis,
        "scannable_recall": row.scannable_recall,
        "coverage": row.coverage,
        "scannable_actual_count": row.scannable_actual_count,
        "total_actual_count": row.total_actual_count,
        "high_based_recall": row.high_based_recall,
        "high_based_precision": row.high_based_precision,
        "high_based_coverage": row.high_based_coverage,
    }


def _bridge_candidate_count_fields(db: Session | None, signal_date) -> dict:
    default = {
        "bridge_candidate_count": 0,
        "bridge_pool_a_candidate_count": 0,
        "bridge_candidate_count_by_pool": {
            "pool_a": 0,
            "pool_b": 0,
            "pool_c": 0,
            "pool_d": 0,
        },
    }
    if db is None or signal_date is None:
        return default

    from app.models.fund_signal import FundSignal

    try:
        rows = (
            db.query(FundSignal.surge_metadata)
            .filter(
                FundSignal.signal_type == "surge_candidate",
                FundSignal.surge_metadata.isnot(None),
                func.date(FundSignal.created_at) == signal_date,
            )
            .all()
        )
    except Exception:
        return default

    by_pool = dict(default["bridge_candidate_count_by_pool"])
    total = 0
    for row in rows:
        try:
            metadata = json.loads(row.surge_metadata or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        basis = metadata.get("surge_basis")
        if not isinstance(basis, list) or "scan_universe_bridge" not in basis:
            continue
        total += 1
        for pool in by_pool:
            if pool in basis:
                by_pool[pool] += 1

    return {
        "bridge_candidate_count": total,
        "bridge_pool_a_candidate_count": by_pool["pool_a"],
        "bridge_candidate_count_by_pool": by_pool,
    }


def _evaluation_list_item(row, db: Session | None = None) -> dict:
    item = {
        "evaluation_date": str(row.evaluation_date),
        "predicted_count": row.predicted_count,
        "actual_surge_count": row.actual_surge_count,
        "true_positive": row.true_positive,
        "false_positive": row.false_positive,
        "false_negative": row.false_negative,
        "precision": row.precision,
        "recall": row.recall,
        "f1_score": row.f1_score,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    item.update(_evaluation_metric_fields(row))
    if db is not None:
        from app.services.surge_trading_service import _get_prev_business_day
        from app.services.surge_lane_metrics_service import build_surge_lane_metrics

        item["lanes"] = build_surge_lane_metrics(db, row)
        item.update(
            _bridge_candidate_count_fields(
                db, _get_prev_business_day(row.evaluation_date)
            )
        )
    else:
        item["lanes"] = {}
        item.update(_bridge_candidate_count_fields(None, None))
    return item


def _get_signal_details_for_date(db: Session, eval_date) -> list:
    """특정 날짜의 surge 시그널 목록을 반환하는 내부 헬퍼."""
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.models.disclosure import Disclosure  # noqa: F401 — FundSignal.disclosure 관계 해소용

    try:
        rows = (
            db.query(FundSignal, Stock)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(
                FundSignal.signal_type.in_(["surge_candidate", "preday_disclosure", "disclosure_impact"]),
                FundSignal.signal == "buy",
                func.date(FundSignal.created_at) == eval_date,
            )
            .order_by(FundSignal.confidence.desc())
            .all()
        )
        return [
            {
                "stock_code": st.stock_code,
                "stock_name": st.name,
                "signal_type": fs.signal_type,
                "confidence": fs.confidence,
                "composite_score": fs.composite_score,
                "price_at_signal": fs.price_at_signal,
                "price_after_1d": fs.price_after_1d,
                "return_pct": fs.return_pct,
                "alpha_pct": fs.alpha_pct,
                "is_correct": fs.is_correct,
                "error_category": fs.error_category,
                "pre_signal_change_pct": _extract_pre_signal_change_pct(fs.surge_metadata),
            }
            for fs, st in rows
        ]
    except Exception:
        return []


@router.get("/evaluation/{date_str}")
def get_evaluation_by_date(
    date_str: str,
    db: Session = Depends(get_db),
):
    """특정 날짜의 급등 예측 평가 결과를 상세 조회한다.

    Args:
        date_str: 날짜 문자열 (YYYY-MM-DD)

    Returns:
        SurgePredictionEvaluation 전체 필드 (miss_analysis_json 포함)

    Raises:
        HTTPException(404): 해당 날짜 평가 데이터 없음
        HTTPException(400): 날짜 형식 오류
    """
    try:
        eval_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"날짜 형식 오류: {date_str} (YYYY-MM-DD 필요)")

    try:
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
        from app.services.surge_evaluation_service import restore_predicted_codes

        row = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == eval_date)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"{date_str} 평가 데이터 없음")

        response = {
            "evaluation_date": str(row.evaluation_date),
            "predicted_count": row.predicted_count,
            "actual_surge_count": row.actual_surge_count,
            "true_positive": row.true_positive,
            "false_positive": row.false_positive,
            "false_negative": row.false_negative,
            "precision": row.precision,
            "recall": row.recall,
            "f1_score": row.f1_score,
            "miss_analysis_json": row.miss_analysis_json,
            "improvements_applied_json": row.improvements_applied_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "signal_details": _get_signal_details_for_date(db, eval_date),
            # SPEC-AI-092 REQ-AI092-002: 평가 당시 공식 predicted set 스냅샷(있으면 우선
            # 신뢰). 스냅샷 도입 이전 row는 None — signal_details/predicted_count로 fail-open.
            "predicted_codes": restore_predicted_codes(row),
        }
        response.update(_evaluation_metric_fields(row))
        from app.services.surge_trading_service import _get_prev_business_day
        from app.services.surge_lane_metrics_service import build_surge_lane_metrics

        response["lanes"] = build_surge_lane_metrics(db, row)
        response.update(
            _bridge_candidate_count_fields(db, _get_prev_business_day(eval_date))
        )
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error("급등 예측 평가 상세 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="평가 상세 조회 실패")


@router.get("/improvements")
def get_improvements(
    days: int = Query(10, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """최근 N일 자동 파라미터 개선 이력 목록을 반환한다.

    각 날짜에 여러 파라미터가 변경될 수 있으므로 days*20개를 상한으로 조회한다.

    Returns:
        SurgeAutoImprovementLog 레코드 목록 (applied_at 내림차순)
    """
    try:
        from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog

        rows = (
            db.query(SurgeAutoImprovementLog)
            .order_by(SurgeAutoImprovementLog.applied_at.desc())
            .limit(days * 20)
            .all()
        )
        return [
            {
                "id": row.id,
                "applied_at": row.applied_at.isoformat() if row.applied_at else None,
                "evaluation_date": str(row.evaluation_date),
                "parameter_path": row.parameter_path,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "rationale": row.rationale,
                "rolling_window_days": row.rolling_window_days,
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("자동 개선 이력 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="개선 이력 조회 실패")


@router.get("/prediction-history")
def get_prediction_history(
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """최근 N거래일의 날짜별 예측 기록을 시그널 목록 포함하여 반환한다.

    Returns:
        날짜별 예측 평가 + 개별 시그널 목록 (evaluation_date 내림차순)
    """
    from collections import Counter, defaultdict
    from datetime import date as date_cls, datetime, timedelta
    from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.models.disclosure import Disclosure  # noqa: F401 — FundSignal.disclosure 관계 해소용
    from app.services.surge_evaluation_service import restore_predicted_codes
    from app.services.surge_trading_service import _get_prev_business_day, _get_next_business_day

    try:
        evals = (
            db.query(SurgePredictionEvaluation)
            .order_by(SurgePredictionEvaluation.evaluation_date.desc())
            .limit(days)
            .all()
        )

        today = date_cls.today()

        # evaluation_date(T) → signal_date(T-1) 매핑: 평가 레코드는 전일 시그널을 평가한다.
        # 예) evaluation_date=6/10 → signal_date=6/9 (6/9 시그널이 6/10에 급등했는지 평가)
        signal_date_for_eval: dict[date_cls, date_cls] = {
            ev.evaluation_date: _get_prev_business_day(ev.evaluation_date) for ev in evals
        }

        # 오늘 시그널이 이미 어떤 평가 레코드의 T-1에 해당하지 않으면 미평가 행으로 포함.
        # eval_dates(T) 기준이 아닌 already_covered_signal_dates(T-1) 기준으로 판정:
        # eval_dates에 오늘(T)이 있어도 그건 어제 시그널을 평가한 것이므로 오늘 시그널은 별도 표시 필요.
        already_covered_signal_dates = set(signal_date_for_eval.values())
        include_today = today not in already_covered_signal_dates

        # N+1 방지: 모든 날짜 시그널을 단일 쿼리로 조회 (범위 비교로 인덱스 사용)
        # 범위는 T-1 시그널 날짜 기준 (eval 날짜가 아님)
        signal_dates = list(signal_date_for_eval.values())
        if include_today:
            signal_dates.append(today)  # 오늘 생성 시그널(미평가)도 포함

        if signal_dates:
            date_min = min(signal_dates)
            date_max = max(signal_dates)
        else:
            date_min = date_max = today
        start_dt = datetime.combine(date_min, datetime.min.time())
        end_dt = datetime.combine(date_max + timedelta(days=1), datetime.min.time())

        all_signals = (
            db.query(FundSignal, Stock)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(
                FundSignal.signal_type.in_(["surge_candidate", "preday_disclosure", "disclosure_impact"]),
                FundSignal.signal == "buy",
                FundSignal.created_at >= start_dt,
                FundSignal.created_at < end_dt,
            )
            .order_by(FundSignal.created_at.desc(), FundSignal.confidence.desc())
            .all()
        )

        # 날짜별 그룹핑 (Python, DB 왕복 없음)
        signals_by_date: dict = defaultdict(list)
        for fs, st in all_signals:
            signals_by_date[fs.created_at.date()].append((fs, st))

        result = []

        # 오늘 평가 레코드 없이 시그널만 있으면 상단에 미평가 항목 추가
        if include_today:
            today_signals = signals_by_date.get(today, [])
            if today_signals:
                from app.services.surge_lane_metrics_service import (
                    compute_same_day_lane_metrics,
                )

                today_surge_signals = []
                today_disclosure_signals = []
                for fs, st in today_signals:
                    item = {
                        "stock_code": st.stock_code,
                        "stock_name": st.name,
                        "signal_type": fs.signal_type,
                        "confidence": fs.confidence,
                        "composite_score": fs.composite_score,
                        "price_at_signal": fs.price_at_signal,
                        "price_after_1d": None,
                        "return_pct": None,
                        "alpha_pct": None,
                        "is_correct": None,
                        "error_category": None,
                        "pre_signal_change_pct": _extract_pre_signal_change_pct(fs.surge_metadata),
                    }
                    if fs.signal_type == "surge_candidate":
                        today_surge_signals.append(item)
                    elif fs.signal_type in ("preday_disclosure", "disclosure_impact"):
                        today_disclosure_signals.append(item)
                result.append({
                    "trading_date": str(today),
                    "target_date": str(_get_next_business_day(today)),
                    # surge_candidate 시그널만 카운트 (DB 집계 버그 방어)
                    "predicted_count": len(today_surge_signals),
                    "actual_surge_count": None,
                    "true_positive": None,
                    "false_positive": None,
                    "false_negative": None,
                    "precision": None,
                    "recall": None,
                    "f1_score": None,
                    "market_recall": None,
                    "market_f1_score": None,
                    "recall_basis": None,
                    "scannable_recall": None,
                    "coverage": None,
                    "scannable_actual_count": None,
                    "total_actual_count": None,
                    "high_based_recall": None,
                    "high_based_precision": None,
                    "high_based_coverage": None,
                    "avg_alpha_pct": None,
                    "error_breakdown": {},
                    # 하위호환: signals = surge + disclosure 전체
                    "signals": today_surge_signals + today_disclosure_signals,
                    "surge_signals": today_surge_signals,
                    "disclosure_signals": today_disclosure_signals,
                    "lanes": {
                        "next_day": {
                            "lane": "next_day",
                            "predicted_count": len(today_surge_signals),
                            "true_positive": None,
                            "false_positive": None,
                            "false_negative": None,
                            "precision": None,
                            "recall": None,
                            "recall_basis": None,
                        },
                        "same_day": compute_same_day_lane_metrics(db, today),
                    },
                    **_bridge_candidate_count_fields(db, today),
                })

        for ev in evals:
            # T-1 시그널 조회: 평가 레코드(T)에는 전일(T-1) 시그널이 대응됨
            day_signals = signals_by_date.get(signal_date_for_eval[ev.evaluation_date], [])
            surge_signals = []
            disclosure_signals = []
            error_counts: Counter = Counter()
            for fs, st in day_signals:
                item = {
                    "stock_code": st.stock_code,
                    "stock_name": st.name,
                    "signal_type": fs.signal_type,
                    "confidence": fs.confidence,
                    "composite_score": fs.composite_score,
                    "price_at_signal": fs.price_at_signal,
                    "price_after_1d": fs.price_after_1d,
                    "return_pct": fs.return_pct,
                    "alpha_pct": fs.alpha_pct,
                    "is_correct": fs.is_correct,
                    "error_category": fs.error_category,
                    "pre_signal_change_pct": _extract_pre_signal_change_pct(fs.surge_metadata),
                }
                if fs.signal_type == "surge_candidate":
                    surge_signals.append(item)
                    # error_breakdown: surge_candidate 기준으로만 집계
                    if fs.error_category:
                        error_counts[fs.error_category] += 1
                elif fs.signal_type in ("preday_disclosure", "disclosure_impact"):
                    disclosure_signals.append(item)

            # avg_alpha_pct: surge_candidate 검증 완료 시그널만 평균
            verified = [s["alpha_pct"] for s in surge_signals if s["alpha_pct"] is not None]
            avg_alpha = sum(verified) / len(verified) if verified else None

            row_item = {
                # signal_date(T-1)을 행 레이블로 사용: "6/9 행 = 6/9에 생성한 시그널 = 6/10 예측"
                "trading_date": str(signal_date_for_eval[ev.evaluation_date]),
                # target_date(T) = 실제 예측 대상일 (급등이 발생하는 날)
                "target_date": str(ev.evaluation_date),
                # 평가 완료 행의 카운트는 평가 당시의 공식 predicted_set 결과가 정본이다.
                # FundSignal.created_at은 carry-over/update 경로에서 후일 이동할 수 있으므로
                # 여기서 재조회한 상세 목록 길이로 과거 평가 카운트를 덮어쓰지 않는다.
                "predicted_count": ev.predicted_count,
                "actual_surge_count": ev.actual_surge_count,
                "true_positive": ev.true_positive,
                "false_positive": ev.false_positive,
                "false_negative": ev.false_negative,
                "precision": ev.precision,
                "recall": ev.recall,
                "f1_score": ev.f1_score,
                "avg_alpha_pct": avg_alpha,
                "error_breakdown": dict(error_counts),
                # 하위호환: signals = surge + disclosure 전체
                "signals": surge_signals + disclosure_signals,
                "surge_signals": surge_signals,
                "disclosure_signals": disclosure_signals,
                # SPEC-AI-092 REQ-AI092-002: 평가 당시 공식 predicted set 스냅샷(있으면
                # signal_date drift에 영향받지 않는 정본). 스냅샷 도입 이전 행은 None.
                "predicted_codes": restore_predicted_codes(ev),
            }
            row_item.update(_evaluation_metric_fields(ev))
            from app.services.surge_lane_metrics_service import build_surge_lane_metrics

            row_item["lanes"] = build_surge_lane_metrics(db, ev)
            row_item.update(
                _bridge_candidate_count_fields(
                    db, signal_date_for_eval[ev.evaluation_date]
                )
            )
            result.append(row_item)

        return result

    except Exception as e:
        logger.error("예측 기록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="예측 기록 조회 실패")


@router.post("/re-evaluate/{date_str}")
def re_evaluate_surge_predictions(
    date_str: str,
    db: Session = Depends(get_db),
):
    """특정 날짜의 급등 예측 평가 결과를 재계산한다.

    평가 버그 수정 후 과거 데이터 재처리에 사용한다.
    DB에 저장된 기존 평가 레코드를 올바른 값으로 덮어쓴다.

    Args:
        date_str: 재평가할 날짜 (YYYY-MM-DD 형식, T 당일 기준)
    """
    from app.services.surge_evaluation_service import (
        evaluate_surge_predictions,
        diagnose_non_scannable_causes,
    )

    try:
        eval_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"날짜 형식 오류: {date_str}")

    try:
        # SPEC-AI-086 REQ-AI086-006: 직전 평가 레코드 기준 scannable_denominator_expanded
        # 판정용 지표 조회(fail-open, 없으면 None).
        prior_scannable_metrics = None
        try:
            from app.models.surge_prediction_evaluation import (
                SurgePredictionEvaluation as _SPE,
            )

            _prior_eval = (
                db.query(_SPE)
                .filter(_SPE.evaluation_date < eval_date)
                .order_by(_SPE.evaluation_date.desc())
                .first()
            )
            if _prior_eval is not None:
                prior_scannable_metrics = {
                    "scannable_actual_count": _prior_eval.scannable_actual_count or 0,
                    "scan_universe_size": _prior_eval.scan_universe_size or 0,
                }
        except Exception as _pme:
            logger.warning("[급등재평가] prior_scannable_metrics 조회 실패 (무시): %s", _pme)

        evaluation = evaluate_surge_predictions(
            db, eval_date, prior_scannable_metrics=prior_scannable_metrics
        )

        # SPEC-AI-086 REQ-AI086-002: non_scannable 원인 진단(truncated/absent) 실행.
        # 실패해도 위 핵심 평가 결과는 이미 evaluate_surge_predictions 내부에서 커밋되어 보존됨.
        non_scannable_diagnosis: dict[str, str] = {}
        try:
            non_scannable_diagnosis = diagnose_non_scannable_causes(db, eval_date)
        except Exception as _dge:
            logger.warning("[급등재평가] non_scannable 원인 진단 실패 (무시): %s", _dge)

        return {
            "evaluation_date": str(evaluation.evaluation_date),
            "predicted_count": evaluation.predicted_count,
            "actual_surge_count": evaluation.actual_surge_count,
            "true_positive": evaluation.true_positive,
            "false_positive": evaluation.false_positive,
            "false_negative": evaluation.false_negative,
            "precision": evaluation.precision,
            "recall": evaluation.recall,
            "f1_score": evaluation.f1_score,
            "scannable_denominator_expanded": getattr(
                evaluation, "scannable_denominator_expanded", None
            ),
            "non_scannable_diagnosis": non_scannable_diagnosis,
        }
    except Exception as e:
        logger.error("급등 예측 재평가 실패: %s", e)
        raise HTTPException(status_code=500, detail="재평가 실패")


def _is_surge_backfill_business_day(day: date) -> bool:
    """급등평가 백필 대상 거래일 여부를 판정한다."""
    try:
        from app.services.surge_trading_service import KRX_EXTRA_HOLIDAYS

        return day.weekday() < 5 and day not in KRX_EXTRA_HOLIDAYS
    except Exception:
        return day.weekday() < 5


@router.post("/evaluation-backfill")
def backfill_surge_evaluations(
    request: Request,
    start_date: str = Query(..., description="백필 시작일 (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="백필 종료일 (YYYY-MM-DD, 생략 시 시작일만)"),
    force_recollect_actual: bool = Query(False),
    force_re_evaluate: bool = Query(False),
    db: Session = Depends(get_db),
):
    # @MX:NOTE: [AUTO] SPEC-AI-109 — 운영 SSH 없이 특정 날짜/범위의
    # surge_actual_outcome + surge_prediction_evaluation 누락을 복구하는 관리자 API.
    # @MX:SPEC: SPEC-AI-109 REQ-AI109-003
    """급등 actual/evaluation 누락을 날짜 범위로 백필한다."""
    _require_admin(request)

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date) if end_date else start
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식 오류: YYYY-MM-DD 필요")

    if end < start:
        raise HTTPException(status_code=400, detail="end_date는 start_date보다 빠를 수 없습니다.")

    if (end - start).days > 31:
        raise HTTPException(status_code=400, detail="한 번에 최대 32일 범위까지만 백필할 수 있습니다.")

    from app.services.surge_evaluation_service import repair_missing_surge_evaluation

    results = []
    current = start
    while current <= end:
        if not _is_surge_backfill_business_day(current):
            results.append({
                "trading_date": str(current),
                "status": "skipped_non_trading_day",
            })
            current += timedelta(days=1)
            continue

        try:
            results.append(
                repair_missing_surge_evaluation(
                    db,
                    current,
                    force_recollect_actual=force_recollect_actual,
                    force_re_evaluate=force_re_evaluate,
                )
            )
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception("[급등평가백필] 날짜별 백필 실패: trading_date=%s", current)
            results.append({
                "trading_date": str(current),
                "status": "failed",
                "error": str(exc),
            })
        current += timedelta(days=1)

    return {
        "start_date": str(start),
        "end_date": str(end),
        "count": len(results),
        "failed_count": sum(1 for row in results if row.get("status") == "failed"),
        "results": results,
    }
