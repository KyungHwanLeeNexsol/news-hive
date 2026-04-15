"""기존 매매 기록에 수수료/거래세 소급 적용 스크립트.

삼성증권 MTS 기준:
- 수수료: 0.014% (매수/매도 각각)
- 거래세: 0.18% (매도 시에만)

적용 대상:
1. virtual_trades (AI 펀드매니저) — 청산 완료 거래 pnl/return_pct 재계산
2. ks200_trades (KS200 스윙) — 청산 완료 거래 pnl/return_pct 재계산
3. vip_trades (VIP 추종) — 청산 완료 거래 pnl/return_pct 재계산
4. 포트폴리오 현금 잔고 — 오픈 포지션 매수 수수료 미차감분 보정

사용법 (서버):
    cd ~/news-hive/backend
    source venv/bin/activate
    python scripts/backfill_trading_fees.py [--dry-run]

옵션:
    --dry-run  변경 내용만 출력하고 DB에 저장하지 않음
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.main import app  # noqa: E402, F401 — 모델 매퍼 초기화
from app.database import SessionLocal  # noqa: E402
from app.models.virtual_portfolio import VirtualPortfolio, VirtualTrade  # noqa: E402
from app.models.ks200_trading import KS200Portfolio, KS200Trade  # noqa: E402
from app.models.vip_trading import VIPPortfolio, VIPTrade  # noqa: E402

COMMISSION_RATE = 0.00014
TRANSACTION_TAX_RATE = 0.0018


def calc_new_pnl(
    entry_price: int,
    exit_price: int,
    quantity: int,
) -> tuple[int, float]:
    """수수료/거래세 반영 PnL, return_pct 반환."""
    cost_basis = entry_price * quantity
    buy_comm = round(cost_basis * COMMISSION_RATE)
    total_cost = cost_basis + buy_comm

    sell_proceeds = exit_price * quantity
    sell_comm = round(sell_proceeds * COMMISSION_RATE)
    tax = round(sell_proceeds * TRANSACTION_TAX_RATE)
    net_proceeds = sell_proceeds - sell_comm - tax

    pnl = net_proceeds - total_cost
    return_pct = round(pnl / total_cost * 100, 2) if total_cost > 0 else 0.0
    return round(pnl), return_pct


def backfill_virtual_trades(db, dry_run: bool) -> dict:
    """AI 펀드매니저 청산 거래 소급 적용."""
    trades = db.query(VirtualTrade).filter(
        VirtualTrade.is_open.is_(False),
        VirtualTrade.exit_price.isnot(None),
        VirtualTrade.pnl.isnot(None),
    ).all()

    updated = 0
    pnl_delta_total = 0

    for t in trades:
        new_pnl, new_ret = calc_new_pnl(t.entry_price, t.exit_price, t.quantity)
        old_pnl = t.pnl
        if old_pnl == new_pnl:
            continue
        pnl_delta_total += (new_pnl - old_pnl)
        if not dry_run:
            t.pnl = new_pnl
            t.return_pct = new_ret
        else:
            print(
                f"  [virtual_trades] id={t.id} pnl: {old_pnl:+,} → {new_pnl:+,} "
                f"(Δ{new_pnl - old_pnl:+,}) return: {t.return_pct:.2f}% → {new_ret:.2f}%"
            )
        updated += 1

    # 오픈 포지션 매수 수수료 미차감분 → current_cash 보정
    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    cash_adj = 0
    if portfolio:
        open_trades = db.query(VirtualTrade).filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(True),
        ).all()
        for t in open_trades:
            missed_comm = round(t.entry_price * t.quantity * COMMISSION_RATE)
            cash_adj += missed_comm
        if cash_adj > 0:
            if not dry_run:
                portfolio.current_cash -= cash_adj
            else:
                print(f"  [virtual_portfolio] current_cash 보정: -{cash_adj:,}원 (오픈 포지션 {len(open_trades)}개 매수 수수료)")

    return {"table": "virtual_trades", "updated": updated, "pnl_delta": pnl_delta_total, "cash_adj": cash_adj}


def backfill_ks200_trades(db, dry_run: bool) -> dict:
    """KS200 스윙 청산 거래 소급 적용."""
    trades = db.query(KS200Trade).filter(
        KS200Trade.is_open.is_(False),
        KS200Trade.exit_price.isnot(None),
        KS200Trade.pnl.isnot(None),
    ).all()

    updated = 0
    pnl_delta_total = 0

    for t in trades:
        new_pnl, new_ret = calc_new_pnl(t.entry_price, t.exit_price, t.quantity)
        old_pnl = t.pnl
        if old_pnl == new_pnl:
            continue
        pnl_delta_total += (new_pnl - old_pnl)
        if not dry_run:
            t.pnl = new_pnl
            t.return_pct = new_ret
        else:
            print(
                f"  [ks200_trades] id={t.id} {t.stock_code} pnl: {old_pnl:+,} → {new_pnl:+,} "
                f"(Δ{new_pnl - old_pnl:+,}) return: {t.return_pct:.2f}% → {new_ret:.2f}%"
            )
        updated += 1

    # 오픈 포지션 매수 수수료 미차감분 → current_cash 보정
    portfolio = db.query(KS200Portfolio).filter(KS200Portfolio.is_active.is_(True)).first()
    cash_adj = 0
    if portfolio:
        open_trades = db.query(KS200Trade).filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.is_open.is_(True),
        ).all()
        for t in open_trades:
            missed_comm = round(t.entry_price * t.quantity * COMMISSION_RATE)
            cash_adj += missed_comm
        if cash_adj > 0:
            if not dry_run:
                portfolio.current_cash -= cash_adj
            else:
                print(f"  [ks200_portfolio] current_cash 보정: -{cash_adj:,}원 (오픈 포지션 {len(open_trades)}개 매수 수수료)")

    return {"table": "ks200_trades", "updated": updated, "pnl_delta": pnl_delta_total, "cash_adj": cash_adj}


def backfill_vip_trades(db, dry_run: bool) -> dict:
    """VIP 추종 청산 거래 소급 적용."""
    trades = db.query(VIPTrade).filter(
        VIPTrade.is_open.is_(False),
        VIPTrade.exit_price.isnot(None),
        VIPTrade.pnl.isnot(None),
    ).all()

    updated = 0
    pnl_delta_total = 0

    for t in trades:
        new_pnl, new_ret = calc_new_pnl(t.entry_price, t.exit_price, t.quantity)
        old_pnl = t.pnl
        if old_pnl == new_pnl:
            continue
        pnl_delta_total += (new_pnl - old_pnl)
        if not dry_run:
            t.pnl = new_pnl
            t.return_pct = new_ret
        else:
            print(
                f"  [vip_trades] id={t.id} pnl: {old_pnl:+,} → {new_pnl:+,} "
                f"(Δ{new_pnl - old_pnl:+,}) return: {t.return_pct:.2f}% → {new_ret:.2f}%"
            )
        updated += 1

    # 오픈 포지션 매수 수수료 미차감분 → current_cash 보정
    portfolio = db.query(VIPPortfolio).filter(VIPPortfolio.is_active.is_(True)).first()
    cash_adj = 0
    if portfolio:
        open_trades = db.query(VIPTrade).filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(True),
        ).all()
        for t in open_trades:
            missed_comm = round(t.entry_price * t.quantity * COMMISSION_RATE)
            cash_adj += missed_comm
        if cash_adj > 0:
            if not dry_run:
                portfolio.current_cash -= cash_adj
            else:
                print(f"  [vip_portfolio] current_cash 보정: -{cash_adj:,}원 (오픈 포지션 {len(open_trades)}개 매수 수수료)")

    return {"table": "vip_trades", "updated": updated, "pnl_delta": pnl_delta_total, "cash_adj": cash_adj}


def main() -> None:
    parser = argparse.ArgumentParser(description="매매 수수료/거래세 소급 적용")
    parser.add_argument("--dry-run", action="store_true", help="변경 내용 출력만, DB 저장 안 함")
    args = parser.parse_args()

    dry_run = args.dry_run
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n{'='*60}")
    print(f"  매매 수수료/거래세 소급 적용 [{mode}]")
    print(f"  수수료: {COMMISSION_RATE*100:.3f}%  거래세: {TRANSACTION_TAX_RATE*100:.2f}%")
    print(f"{'='*60}\n")

    db = SessionLocal()
    try:
        results = []
        results.append(backfill_virtual_trades(db, dry_run))
        results.append(backfill_ks200_trades(db, dry_run))
        results.append(backfill_vip_trades(db, dry_run))

        if not dry_run:
            db.commit()
            print("\n✅ DB 커밋 완료\n")

        print(f"\n{'='*60}")
        print("  결과 요약")
        print(f"{'='*60}")
        for r in results:
            print(
                f"  {r['table']:20s} | 수정: {r['updated']:4d}건 | "
                f"PnL 변화합계: {r['pnl_delta']:+,}원 | 현금 보정: -{r['cash_adj']:,}원"
            )
        print(f"{'='*60}\n")

        if dry_run:
            print("  ⚠️  DRY-RUN 모드: 실제 DB 변경 없음. --dry-run 제거 후 재실행하면 적용됩니다.\n")

    except Exception as e:
        db.rollback()
        print(f"\n❌ 오류 발생, 롤백: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
