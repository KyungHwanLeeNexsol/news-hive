"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 API 라우터.

/surge prefix 하에 5개 엔드포인트 제공.
POST /surge/execute는 관리자 인증 필요.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
