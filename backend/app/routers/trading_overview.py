"""모의투자 3개 모델 통합 비교 대시보드 API."""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading", tags=["trading-overview"])


@router.get("/overview")
async def get_trading_overview(db: Session = Depends(get_db)):
    """3개 모의투자 모델 통합 현황 (포트폴리오 요약 + 오픈 포지션 + 최근 거래).

    9번의 개별 API 호출 대신 1회 호출로 비교 대시보드 데이터를 반환한다.
    현재가 조회는 모든 오픈 종목에 대해 배치로 1회만 수행한다.
    """
    from app.models.ks200_trading import KS200Trade
    from app.models.stock import Stock
    from app.models.virtual_portfolio import VirtualTrade
    from app.models.vip_trading import VIPTrade
    from app.services.ks200_trading import get_ks200_portfolio_stats, get_or_create_ks200_portfolio
    from app.services.paper_trading import get_or_create_portfolio, get_portfolio_stats
    from app.services.vip_follow_trading import (
        _fetch_prices_batch,
        get_or_create_vip_portfolio,
        get_vip_portfolio_stats,
    )

    # ─── 포트폴리오 객체 ───
    paper_portfolio = get_or_create_portfolio(db)
    ks200_portfolio = get_or_create_ks200_portfolio(db)
    vip_portfolio = get_or_create_vip_portfolio(db)

    # ─── 통계 (3개 모델 모두 실시간 가격 조회 병렬 실행) ───
    paper_stats, ks200_stats, vip_stats = await asyncio.gather(
        get_portfolio_stats(db),
        get_ks200_portfolio_stats(db),
        get_vip_portfolio_stats(db),
    )

    # ─── 오픈 포지션 DB 조회 ───
    paper_open = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.portfolio_id == paper_portfolio.id, VirtualTrade.is_open.is_(True))
        .order_by(VirtualTrade.entry_date.desc())
        .all()
    )
    ks200_open = (
        db.query(KS200Trade)
        .filter(KS200Trade.portfolio_id == ks200_portfolio.id, KS200Trade.is_open.is_(True))
        .order_by(KS200Trade.entry_date.desc())
        .all()
    )
    vip_open = (
        db.query(VIPTrade)
        .filter(VIPTrade.portfolio_id == vip_portfolio.id, VIPTrade.is_open.is_(True))
        .order_by(VIPTrade.entry_date.desc())
        .all()
    )

    # ─── 최근 청산 거래 (모델당 최대 15건) ───
    paper_closed = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.portfolio_id == paper_portfolio.id, VirtualTrade.is_open.is_(False))
        .order_by(VirtualTrade.exit_date.desc())
        .limit(15)
        .all()
    )
    ks200_closed = (
        db.query(KS200Trade)
        .filter(KS200Trade.portfolio_id == ks200_portfolio.id, KS200Trade.is_open.is_(False))
        .order_by(KS200Trade.exit_date.desc())
        .limit(15)
        .all()
    )
    vip_closed = (
        db.query(VIPTrade)
        .filter(VIPTrade.portfolio_id == vip_portfolio.id, VIPTrade.is_open.is_(False))
        .order_by(VIPTrade.exit_date.desc())
        .limit(15)
        .all()
    )

    # ─── 종목 정보 일괄 조회 (N+1 방지) ───
    paper_ids = {t.stock_id for t in paper_open + paper_closed if t.stock_id}
    ks200_ids = {t.stock_id for t in ks200_open + ks200_closed if t.stock_id}
    vip_ids = {t.stock_id for t in vip_open + vip_closed if t.stock_id}
    all_stock_ids = paper_ids | ks200_ids | vip_ids
    stocks_map: dict[int, Stock] = (
        {s.id: s for s in db.query(Stock).filter(Stock.id.in_(all_stock_ids)).all()}
        if all_stock_ids
        else {}
    )

    # ─── 현재가 배치 조회 (오픈 포지션 전체, 1회) ───
    def _code(trade: VirtualTrade | VIPTrade) -> str | None:
        s = stocks_map.get(trade.stock_id) if trade.stock_id else None
        return s.stock_code if s else None

    all_open_codes: list[str] = (
        [c for t in paper_open if (c := _code(t))]
        + [t.stock_code for t in ks200_open if t.stock_code]
        + [c for t in vip_open if (c := _code(t))]
    )
    prices_map: dict[str, int] = await _fetch_prices_batch(all_open_codes) if all_open_codes else {}

    # ─── 오픈 포지션 통합 ───
    def _build_position(model: str, label: str, entry: int, qty: int, code: str | None, name: str, entry_date) -> dict:
        cp = prices_map.get(code) if code else None
        invest = entry * qty
        cur_val = (cp * qty) if cp else invest
        upct = round((cp - entry) / entry * 100, 2) if cp and entry else None
        return {
            "model": model,
            "model_label": label,
            "stock_name": name,
            "stock_code": code,
            "entry_price": entry,
            "current_price": cp,
            "quantity": qty,
            "invest_amount": invest,
            "current_value": cur_val,
            "unrealized_pct": upct,
            "entry_date": entry_date.isoformat() if entry_date else None,
        }

    positions: list[dict] = []
    for t in paper_open:
        s = stocks_map.get(t.stock_id)
        positions.append(_build_position("paper", "AI펀드", t.entry_price, t.quantity, _code(t), s.name if s else "Unknown", t.entry_date))
    for t in ks200_open:
        s = stocks_map.get(t.stock_id)
        positions.append(_build_position("ks200", "KS200", t.entry_price, t.quantity, t.stock_code, s.name if s else t.stock_code, t.entry_date))
    for t in vip_open:
        s = stocks_map.get(t.stock_id)
        positions.append(_build_position("vip", "VIP추종", t.entry_price, t.quantity, _code(t), s.name if s else "Unknown", t.entry_date))

    # 미실현 수익률 높은 순 정렬
    positions.sort(key=lambda x: (x["unrealized_pct"] or 0), reverse=True)

    # ─── 거래 내역 통합 ───
    def _build_trade(model: str, label: str, name: str, code: str | None, t) -> dict:
        return {
            "model": model,
            "model_label": label,
            "stock_name": name,
            "stock_code": code,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "return_pct": t.return_pct,
            "exit_reason": getattr(t, "exit_reason", None),
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
        }

    trades: list[dict] = []
    for t in paper_closed:
        s = stocks_map.get(t.stock_id)
        trades.append(_build_trade("paper", "AI펀드", s.name if s else "Unknown", s.stock_code if s else None, t))
    for t in ks200_closed:
        s = stocks_map.get(t.stock_id)
        trades.append(_build_trade("ks200", "KS200", s.name if s else t.stock_code, t.stock_code, t))
    for t in vip_closed:
        s = stocks_map.get(t.stock_id)
        trades.append(_build_trade("vip", "VIP추종", s.name if s else "Unknown", s.stock_code if s else None, t))

    # 청산일 최신순 정렬 후 최대 30건
    trades.sort(key=lambda x: x["exit_date"] or "", reverse=True)
    trades = trades[:30]

    # ─── 승률 집계 (전체 청산 거래 대상, 카운트 쿼리로 정확하게) ───
    from sqlalchemy import func as sa_func

    def _win_rate_query(model_cls, portfolio_id) -> tuple[int, float]:
        total = db.query(sa_func.count(model_cls.id)).filter(
            model_cls.portfolio_id == portfolio_id, model_cls.is_open.is_(False),
        ).scalar() or 0
        wins = db.query(sa_func.count(model_cls.id)).filter(
            model_cls.portfolio_id == portfolio_id, model_cls.is_open.is_(False), model_cls.pnl > 0,
        ).scalar() or 0
        rate = round(wins / total * 100, 1) if total else 0.0
        return total, rate

    ks200_closed_count, ks200_win_rate = _win_rate_query(KS200Trade, ks200_portfolio.id)
    vip_closed_count, vip_win_rate = _win_rate_query(VIPTrade, vip_portfolio.id)

    # ─── 모델 요약 ───
    # @MX:NOTE: paper_stats에는 win_rate/closed_trades/total_pnl이 있음.
    #           KS200/VIP stats에는 win_rate가 없어 별도 집계.
    def _stat(d, key, default=0):
        if isinstance(d, dict):
            return d.get(key, default)
        return getattr(d, key, default)

    model_summaries = {
        "paper": {
            "label": "AI 펀드매니저",
            "total_return_pct": _stat(paper_stats, "total_return_pct"),
            "win_rate": _stat(paper_stats, "win_rate"),
            "open_positions": len(paper_open),
            "closed_trades": _stat(paper_stats, "closed_trades"),
            "total_pnl": _stat(paper_stats, "total_pnl"),
            "initial_capital": _stat(paper_stats, "initial_capital"),
        },
        "ks200": {
            "label": "KS200 스윙",
            "total_return_pct": _stat(ks200_stats, "total_return_pct"),
            "win_rate": ks200_win_rate,
            "open_positions": len(ks200_open),
            "closed_trades": ks200_closed_count,
            "total_pnl": _stat(ks200_stats, "total_pnl"),
            "initial_capital": _stat(ks200_stats, "initial_capital"),
        },
        "vip": {
            "label": "VIP 추종",
            "total_return_pct": _stat(vip_stats, "total_return_pct"),
            "win_rate": vip_win_rate,
            "open_positions": len(vip_open),
            "closed_trades": vip_closed_count,
            "total_pnl": _stat(vip_stats, "total_value", 0) - _stat(vip_stats, "initial_capital", 0),
            "initial_capital": _stat(vip_stats, "initial_capital"),
        },
    }

    return {
        "models": model_summaries,
        "positions": positions,
        "trades": trades,
    }


# ─── 모델 조회 헬퍼 ───────────────────────────────────────────────────────────

def _get_model_portfolio_and_class(model: str, db: Session):
    """model 파라미터에 따라 (portfolio, TradeClass, stock_code_fn) 반환."""
    from app.models.ks200_trading import KS200Trade
    from app.models.virtual_portfolio import VirtualTrade
    from app.models.vip_trading import VIPTrade
    from app.services.ks200_trading import get_or_create_ks200_portfolio
    from app.services.paper_trading import get_or_create_portfolio
    from app.services.vip_follow_trading import get_or_create_vip_portfolio

    if model == "paper":
        portfolio = get_or_create_portfolio(db)
        return portfolio, VirtualTrade, None
    elif model == "ks200":
        portfolio = get_or_create_ks200_portfolio(db)
        return portfolio, KS200Trade, None
    elif model == "vip":
        portfolio = get_or_create_vip_portfolio(db)
        return portfolio, VIPTrade, None
    else:
        raise HTTPException(status_code=400, detail="model은 paper, ks200, vip 중 하나여야 합니다.")


@router.get("/trades")
def get_model_trades(
    model: str = Query(..., description="paper, ks200, vip"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """모델별 전체 매매 기록 조회 (청산 완료 거래).

    매입단가, 매입날짜, 매입금액, 매도날짜, 수익률, 손익 등을 반환한다.
    """
    from app.models.stock import Stock

    portfolio, TradeClass, _ = _get_model_portfolio_and_class(model, db)

    trades = (
        db.query(TradeClass)
        .filter(
            TradeClass.portfolio_id == portfolio.id,
            TradeClass.is_open.is_(False),
        )
        .order_by(TradeClass.exit_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # 종목명/코드 조회
    stock_ids = [t.stock_id for t in trades if t.stock_id]
    stocks_map = {s.id: s for s in db.query(Stock).filter(Stock.id.in_(stock_ids)).all()} if stock_ids else {}

    result = []
    for t in trades:
        s = stocks_map.get(t.stock_id) if t.stock_id else None
        # KS200Trade는 stock_code 직접 보유, 나머지는 Stock에서 조회
        stock_code = getattr(t, "stock_code", None) or (s.stock_code if s else None)
        stock_name = (s.name if s else None) or stock_code or "Unknown"
        invest_amount = t.entry_price * t.quantity
        result.append({
            "stock_code": stock_code,
            "stock_name": stock_name,
            "entry_price": t.entry_price,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "invest_amount": invest_amount,
            "quantity": t.quantity,
            "exit_price": t.exit_price,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "exit_reason": getattr(t, "exit_reason", None),
            "pnl": t.pnl,
            "return_pct": t.return_pct,
            "is_profit": (t.pnl or 0) > 0,
        })
    return result


@router.get("/performance/weekly")
def get_model_weekly_performance(
    model: str = Query(..., description="paper, ks200, vip"),
    weeks: int = Query(12, ge=1, le=52),
    db: Session = Depends(get_db),
):
    """모델별 주간 성과 기록 (최근 N주).

    각 주차별 실현 손익, 거래 수, 승률을 반환한다.
    """
    portfolio, TradeClass, _ = _get_model_portfolio_and_class(model, db)

    # 조회 기간: 최근 N주
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(weeks=weeks)

    closed_trades = (
        db.query(TradeClass)
        .filter(
            TradeClass.portfolio_id == portfolio.id,
            TradeClass.is_open.is_(False),
            TradeClass.exit_date >= since,
        )
        .order_by(TradeClass.exit_date.asc())
        .all()
    )

    # 주차별 집계 (ISO 주차: YYYY-WW)
    weekly: dict[str, dict] = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0})
    for t in closed_trades:
        if not t.exit_date:
            continue
        exit_dt = t.exit_date if t.exit_date.tzinfo else t.exit_date.replace(tzinfo=timezone.utc)
        # ISO 주차 레이블 (예: "2026-W15")
        iso = exit_dt.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        weekly[key]["pnl"] += t.pnl or 0
        weekly[key]["trades"] += 1
        if (t.pnl or 0) > 0:
            weekly[key]["wins"] += 1

    # 빈 주차 채우기 (최근 N주 전체 포함)
    result = []
    for i in range(weeks - 1, -1, -1):
        week_start = now - timedelta(weeks=i)
        iso = week_start.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        data = weekly.get(key, {"pnl": 0, "trades": 0, "wins": 0})
        trades_cnt = data["trades"]
        wins_cnt = data["wins"]
        result.append({
            "week": key,
            "pnl": data["pnl"],
            "trade_count": trades_cnt,
            "win_count": wins_cnt,
            "win_rate": round(wins_cnt / trades_cnt * 100, 1) if trades_cnt else 0.0,
        })
    return result


@router.get("/performance/monthly")
def get_model_monthly_performance(
    model: str = Query(..., description="paper, ks200, vip"),
    months: int = Query(12, ge=1, le=24),
    db: Session = Depends(get_db),
):
    """모델별 월간 성과 기록 (최근 N개월).

    각 월별 실현 손익, 거래 수, 승률을 반환한다.
    """
    portfolio, TradeClass, _ = _get_model_portfolio_and_class(model, db)

    now = datetime.now(tz=timezone.utc)
    # 조회 시작: 현재 월 기준 N개월 전 1일
    start_year = now.year
    start_month = now.month - months
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    since = datetime(start_year, start_month, 1, tzinfo=timezone.utc)

    closed_trades = (
        db.query(TradeClass)
        .filter(
            TradeClass.portfolio_id == portfolio.id,
            TradeClass.is_open.is_(False),
            TradeClass.exit_date >= since,
        )
        .order_by(TradeClass.exit_date.asc())
        .all()
    )

    # 월별 집계 (YYYY-MM)
    monthly: dict[str, dict] = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0})
    for t in closed_trades:
        if not t.exit_date:
            continue
        exit_dt = t.exit_date if t.exit_date.tzinfo else t.exit_date.replace(tzinfo=timezone.utc)
        key = exit_dt.strftime("%Y-%m")
        monthly[key]["pnl"] += t.pnl or 0
        monthly[key]["trades"] += 1
        if (t.pnl or 0) > 0:
            monthly[key]["wins"] += 1

    # 빈 월 채우기 (최근 N개월 전체 포함)
    result = []
    for i in range(months - 1, -1, -1):
        # i개월 전
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        key = f"{y}-{m:02d}"
        data = monthly.get(key, {"pnl": 0, "trades": 0, "wins": 0})
        trades_cnt = data["trades"]
        wins_cnt = data["wins"]
        result.append({
            "month": key,
            "pnl": data["pnl"],
            "trade_count": trades_cnt,
            "win_count": wins_cnt,
            "win_rate": round(wins_cnt / trades_cnt * 100, 1) if trades_cnt else 0.0,
        })
    return result
