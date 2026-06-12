"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 API 라우터.

/surge prefix 하에 5개 엔드포인트 제공.
POST /surge/execute는 관리자 인증 필요.
"""
import logging
from datetime import date

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
        return [
            {
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
            for row in rows
        ]
    except Exception as e:
        logger.error("급등 예측 평가 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="평가 목록 조회 실패")


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

        row = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == eval_date)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"{date_str} 평가 데이터 없음")

        return {
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
        }
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
    from app.services.surge_trading_service import _get_prev_business_day

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
                    }
                    if fs.signal_type == "surge_candidate":
                        today_surge_signals.append(item)
                    elif fs.signal_type in ("preday_disclosure", "disclosure_impact"):
                        today_disclosure_signals.append(item)
                result.append({
                    "trading_date": str(today),
                    "target_date": None,
                    # surge_candidate 시그널만 카운트 (DB 집계 버그 방어)
                    "predicted_count": len(today_surge_signals),
                    "actual_surge_count": None,
                    "true_positive": None,
                    "false_positive": None,
                    "false_negative": None,
                    "precision": None,
                    "recall": None,
                    "f1_score": None,
                    "avg_alpha_pct": None,
                    "error_breakdown": {},
                    # 하위호환: signals = surge + disclosure 전체
                    "signals": today_surge_signals + today_disclosure_signals,
                    "surge_signals": today_surge_signals,
                    "disclosure_signals": today_disclosure_signals,
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

            # predicted_count: DB 저장값 대신 실시간 재계산 (집계 버그 방어)
            surge_count_live = len(surge_signals)

            result.append({
                # signal_date(T-1)을 행 레이블로 사용: "6/9 행 = 6/9에 생성한 시그널 = 6/10 예측"
                "trading_date": str(signal_date_for_eval[ev.evaluation_date]),
                # target_date(T) = 실제 예측 대상일 (급등이 발생하는 날)
                "target_date": str(ev.evaluation_date),
                # surge_candidate만 실시간 카운트 (DB 저장값 ev.predicted_count 무시)
                "predicted_count": surge_count_live,
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
            })

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
    from app.services.surge_evaluation_service import evaluate_surge_predictions

    try:
        eval_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"날짜 형식 오류: {date_str}")

    try:
        evaluation = evaluate_surge_predictions(db, eval_date)
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
        }
    except Exception as e:
        logger.error("급등 예측 재평가 실패: %s", e)
        raise HTTPException(status_code=500, detail="재평가 실패")
