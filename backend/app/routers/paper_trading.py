"""페이퍼 트레이딩 API 라우터."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import Stock
from app.models.virtual_portfolio import PortfolioSnapshot, VirtualPortfolio, VirtualTrade
from app.services.paper_trading import get_or_create_portfolio, get_portfolio_stats

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """포트폴리오 종합 성과 통계."""
    return get_portfolio_stats(db)


@router.get("/positions")
async def get_positions(db: Session = Depends(get_db)):
    """오픈 포지션 목록 (현재가 및 미실현 수익률 포함)."""
    from app.services.vip_follow_trading import _fetch_prices_batch

    portfolio = get_or_create_portfolio(db)
    trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(True),
        )
        .all()
    )

    # 종목 정보 로드 — N+1 쿼리 방지: IN 쿼리로 일괄 조회
    trade_stock_ids = [t.stock_id for t in trades]
    stocks_map = {s.id: s for s in db.query(Stock).filter(Stock.id.in_(trade_stock_ids)).all()} if trade_stock_ids else {}
    trade_stocks = [(t, stocks_map.get(t.stock_id)) for t in trades]

    # 현재가 배치 조회 (1회 API 호출)
    batch_codes = [s.stock_code for _, s in trade_stocks if s and s.stock_code]
    prices_map = await _fetch_prices_batch(batch_codes)
    prices = [prices_map.get(s.stock_code) if s and s.stock_code else None for _, s in trade_stocks]

    result = []
    for (t, stock), current_price in zip(trade_stocks, prices):
        invest_amount = t.entry_price * t.quantity
        unrealized_pct = round(
            (current_price - t.entry_price) / t.entry_price * 100, 2
        ) if current_price and t.entry_price else None
        result.append({
            "id": t.id,
            "stock_name": stock.name if stock else "Unknown",
            "stock_code": stock.stock_code if stock else "",
            "direction": t.direction,
            "entry_price": t.entry_price,
            "current_price": current_price,
            "quantity": t.quantity,
            "target_price": t.target_price,
            "stop_loss": t.stop_loss,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "invest_amount": invest_amount,
            "unrealized_pct": unrealized_pct,
        })
    return result


@router.get("/trades")
def get_trade_history(limit: int = 50, db: Session = Depends(get_db)):
    """전체 매매 이력 (보유 중 포함). 오픈 포지션은 상단에, 청산 거래는 최신순으로 표시."""
    portfolio = get_or_create_portfolio(db)
    # 오픈 포지션: 진입일 최신순
    open_trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(True),
        )
        .order_by(VirtualTrade.entry_date.desc())
        .all()
    )
    # 청산된 거래: 청산일 최신순
    closed_trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(False),
        )
        .order_by(VirtualTrade.exit_date.desc())
        .limit(limit)
        .all()
    )
    trades = open_trades + closed_trades

    # 종목 정보 일괄 조회
    stock_ids = list({t.stock_id for t in trades})
    stocks_map = {s.id: s for s in db.query(Stock).filter(Stock.id.in_(stock_ids)).all()} if stock_ids else {}

    result = []
    for t in trades:
        stock = stocks_map.get(t.stock_id)
        result.append({
            "id": t.id,
            "stock_name": stock.name if stock else "Unknown",
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "return_pct": t.return_pct,
            "exit_reason": t.exit_reason,
            "is_open": t.is_open,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
        })
    return result


@router.get("/snapshots")
def get_snapshots(days: int = 30, db: Session = Depends(get_db)):
    """일일 포트폴리오 스냅샷 (차트용)."""
    portfolio = get_or_create_portfolio(db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.snapshot_date >= cutoff,
        )
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
    kst = timezone(timedelta(hours=9))
    return [
        {
            "date": s.snapshot_date.astimezone(kst).strftime("%Y-%m-%d"),
            "total_value": s.total_value,
            "cash": s.cash,
            "positions_value": s.positions_value,
            "daily_return_pct": s.daily_return_pct,
            "cumulative_return_pct": s.cumulative_return_pct,
            "open_positions": s.open_positions,
        }
        for s in snapshots
    ]


@router.get("/paper-performance")
def get_disclosure_paper_performance(db: Session = Depends(get_db)):
    """공시 기반 시그널 페이퍼 트레이딩 성과 집계 (TASK-004).

    signal_type이 공시 관련인 FundSignal과 연결된 VirtualTrade를 조회하여
    총 매매 건수, 승률, 평균 수익률 등을 집계해 반환한다.
    """
    from app.models.fund_signal import FundSignal

    # 공시 기반 시그널 유형 목록
    disclosure_types = ["disclosure_impact", "sector_ripple", "gap_pullback_candidate"]

    # 공시 관련 FundSignal ID 조회
    signal_ids = [
        row[0]
        for row in db.query(FundSignal.id)
        .filter(FundSignal.signal_type.in_(disclosure_types))
        .all()
    ]

    if not signal_ids:
        return {
            "total_trades": 0,
            "closed_trades": 0,
            "open_trades": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "total_pnl": 0,
            "by_signal_type": {},
        }

    # 해당 시그널에 연결된 VirtualTrade 조회
    trades = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.signal_id.in_(signal_ids))
        .all()
    )

    closed = [t for t in trades if not t.is_open and t.pnl is not None]
    open_trades = [t for t in trades if t.is_open]

    winning = [t for t in closed if (t.pnl or 0) > 0]
    returns = [t.return_pct for t in closed if t.return_pct is not None]
    total_pnl = sum(t.pnl or 0 for t in closed)

    # 공시 유형별 세분화
    # FundSignal.signal_type을 signal_id로 매핑
    signal_type_map: dict[int, str] = {
        row[0]: row[1]
        for row in db.query(FundSignal.id, FundSignal.signal_type)
        .filter(FundSignal.id.in_(signal_ids))
        .all()
    }

    by_type: dict[str, dict] = {stype: {"trades": 0, "closed": 0, "wins": 0, "returns": []} for stype in disclosure_types}
    for t in trades:
        stype = signal_type_map.get(t.signal_id)
        if stype and stype in by_type:
            by_type[stype]["trades"] += 1
            if not t.is_open and t.pnl is not None:
                by_type[stype]["closed"] += 1
                if (t.pnl or 0) > 0:
                    by_type[stype]["wins"] += 1
                if t.return_pct is not None:
                    by_type[stype]["returns"].append(t.return_pct)

    by_signal_type: dict[str, dict] = {}
    for stype, data in by_type.items():
        closed_count = data["closed"]
        wins = data["wins"]
        rets = data["returns"]
        by_signal_type[stype] = {
            "total_trades": data["trades"],
            "closed_trades": closed_count,
            "win_rate": round(wins / closed_count, 4) if closed_count > 0 else 0.0,
            "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else 0.0,
        }

    return {
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
        "win_rate": round(len(winning) / len(closed), 4) if closed else 0.0,
        "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
        "total_pnl": total_pnl,
        "by_signal_type": by_signal_type,
    }


@router.get("/tp-sl-stats")
def get_tp_sl_stats(db: Session = Depends(get_db)):
    """TP/SL 방식별 성과 통계 (SPEC-AI-005).

    ai_provided / atr_dynamic / sector_default / legacy_fixed 방식별로
    승률과 평균 수익률을 집계하여 반환한다.
    needs_review=true이면 동적 방식의 성과가 고정 방식보다 낮음을 의미한다.
    """
    from app.models.fund_signal import FundSignal

    portfolio = get_or_create_portfolio(db)

    # tp_sl_method별 성과 조회
    methods = ["ai_provided", "atr_dynamic", "sector_default", "legacy_fixed"]
    by_method: dict[str, dict] = {}

    for method in methods:
        # 해당 방식의 시그널과 연결된 청산된 거래 조회
        signal_ids_query = (
            db.query(FundSignal.id)
            .filter(FundSignal.tp_sl_method == method)
        )
        signal_ids = [row[0] for row in signal_ids_query.all()]

        if not signal_ids:
            by_method[method] = {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_return_pct": 0.0,
            }
            continue

        trades = (
            db.query(VirtualTrade)
            .filter(
                VirtualTrade.signal_id.in_(signal_ids),
                VirtualTrade.portfolio_id == portfolio.id,
                VirtualTrade.is_open.is_(False),
                VirtualTrade.pnl.isnot(None),
            )
            .all()
        )

        wins = [t for t in trades if (t.pnl or 0) > 0]
        returns = [t.return_pct for t in trades if t.return_pct is not None]

        by_method[method] = {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
        }

    # 동적 방식 vs 고정 방식 비교
    dynamic_win_rate = by_method.get("atr_dynamic", {}).get("win_rate", 0.0)
    fixed_win_rate = by_method.get("legacy_fixed", {}).get("win_rate", 0.0)
    needs_review = (
        by_method["atr_dynamic"]["total_trades"] >= 5
        and dynamic_win_rate < fixed_win_rate
    )

    return {
        "by_method": by_method,
        "needs_review": needs_review,
        "review_reason": (
            f"동적 방식 승률({dynamic_win_rate:.1%}) < 고정 방식 승률({fixed_win_rate:.1%})"
            if needs_review else None
        ),
    }


@router.get("/tp-sl-backtest")
def get_tp_sl_backtest(db: Session = Depends(get_db)):
    """고정 vs 동적 TP/SL 백테스트 비교 (SPEC-AI-005).

    기존 시그널 데이터를 바탕으로 고정 방식과 동적 방식의
    가상 성과를 비교하여 반환한다.
    """
    from app.models.fund_signal import FundSignal

    portfolio = get_or_create_portfolio(db)

    # 청산된 모든 거래 조회
    all_trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(False),
            VirtualTrade.pnl.isnot(None),
        )
        .all()
    )

    if not all_trades:
        return {
            "fixed_method": {"total": 0, "win_rate": 0.0, "avg_return_pct": 0.0},
            "dynamic_method": {"total": 0, "win_rate": 0.0, "avg_return_pct": 0.0},
            "comparison": "데이터 없음",
        }

    # 시그널에서 tp_sl_method 매핑
    signal_ids = [t.signal_id for t in all_trades]
    method_map = {
        row[0]: row[1]
        for row in db.query(FundSignal.id, FundSignal.tp_sl_method)
        .filter(FundSignal.id.in_(signal_ids))
        .all()
    }

    fixed_trades = [t for t in all_trades if method_map.get(t.signal_id) in ("legacy_fixed", None)]
    dynamic_trades = [t for t in all_trades if method_map.get(t.signal_id) in ("atr_dynamic", "sector_default", "ai_provided")]

    def _stats(trades: list) -> dict:
        if not trades:
            return {"total": 0, "win_rate": 0.0, "avg_return_pct": 0.0}
        wins = [t for t in trades if (t.pnl or 0) > 0]
        returns = [t.return_pct for t in trades if t.return_pct is not None]
        return {
            "total": len(trades),
            "win_rate": round(len(wins) / len(trades), 4),
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
        }

    fixed_stats = _stats(fixed_trades)
    dynamic_stats = _stats(dynamic_trades)

    # 비교 판정
    if dynamic_stats["total"] < 5:
        comparison = "동적 방식 데이터 부족 (5건 미만)"
    elif dynamic_stats["win_rate"] > fixed_stats["win_rate"]:
        comparison = f"동적 방식 우수 (+{(dynamic_stats['win_rate'] - fixed_stats['win_rate']):.1%})"
    elif dynamic_stats["win_rate"] < fixed_stats["win_rate"]:
        comparison = f"고정 방식 우수 (+{(fixed_stats['win_rate'] - dynamic_stats['win_rate']):.1%})"
    else:
        comparison = "동등"

    return {
        "fixed_method": fixed_stats,
        "dynamic_method": dynamic_stats,
        "comparison": comparison,
    }


@router.post("/migrate-tp-sl")
async def migrate_legacy_tp_sl(db: Session = Depends(get_db)):
    """레거시 포지션의 TP/SL을 ATR 기반으로 재계산 (일회성, SPEC-AI-005)."""
    from app.services.dynamic_tp_sl import recalculate_legacy_positions

    result = await recalculate_legacy_positions(db)
    return result


@router.post("/reset")
def reset_portfolio(db: Session = Depends(get_db)):
    """포트폴리오 초기화 (모든 매매 기록 삭제, 자본금 리셋)."""
    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    if portfolio:
        db.query(PortfolioSnapshot).filter(PortfolioSnapshot.portfolio_id == portfolio.id).delete()
        db.query(VirtualTrade).filter(VirtualTrade.portfolio_id == portfolio.id).delete()
        portfolio.current_cash = portfolio.initial_capital
        db.commit()
        return {"message": "포트폴리오 초기화 완료", "capital": portfolio.initial_capital}
    return {"message": "활성 포트폴리오 없음"}
