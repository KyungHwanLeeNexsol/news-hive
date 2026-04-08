"""VIP 추종 포트폴리오 포지션 5% 재조정 스크립트.

서버에서 직접 실행:
  cd /home/ubuntu/news-hive && python scripts/rebalance_vip.py
"""
import sys
import os

# backend 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import SessionLocal
from app.models.vip_trading import VIPPortfolio, VIPTrade


def rebalance():
    db = SessionLocal()
    try:
        portfolio = db.query(VIPPortfolio).filter(VIPPortfolio.is_active.is_(True)).first()
        if not portfolio:
            print("VIP 포트폴리오를 찾을 수 없습니다.")
            return

        target_invest = int(portfolio.initial_capital * 0.05)
        print(f"초기자본: {portfolio.initial_capital:,}원")
        print(f"포지션당 목표 투자금 (5%): {target_invest:,}원")
        print(f"현재 현금: {portfolio.current_cash:,}원")

        open_trades = (
            db.query(VIPTrade)
            .filter(VIPTrade.portfolio_id == portfolio.id, VIPTrade.is_open.is_(True))
            .order_by(VIPTrade.id)
            .all()
        )

        if not open_trades:
            print("오픈 포지션이 없습니다.")
            return

        print(f"\n오픈 포지션 수: {len(open_trades)}건")
        print("-" * 70)

        old_total = sum(t.entry_price * t.quantity for t in open_trades)
        adjusted_count = 0

        for trade in open_trades:
            if trade.entry_price <= 0:
                continue

            full_qty = max(1, target_invest // trade.entry_price)
            # partial_sold=True: 30% 이미 익절 → 70% 유지
            new_qty = max(1, round(full_qty * 0.7)) if trade.partial_sold else full_qty
            old_qty = trade.quantity

            old_invest = trade.entry_price * old_qty
            new_invest = trade.entry_price * new_qty

            status = "변경없음" if old_qty == new_qty else f"{old_qty} → {new_qty}"
            partial_tag = " [익절완료]" if trade.partial_sold else ""
            print(
                f"  trade#{trade.id} stock#{trade.stock_id} split={trade.split_sequence}{partial_tag}"
                f"  수량: {status}  투자금: {old_invest:,} → {new_invest:,}원"
            )

            if old_qty != new_qty:
                trade.quantity = new_qty
                adjusted_count += 1

        new_total = sum(t.entry_price * t.quantity for t in open_trades)
        cash_diff = old_total - new_total
        portfolio.current_cash = portfolio.current_cash + cash_diff

        print("-" * 70)
        print(f"\n총 투자금 변동: {old_total:,} → {new_total:,}원  (차이: {cash_diff:+,}원)")
        print(f"현금 조정 후: {portfolio.current_cash:,}원")
        print(f"조정 포지션: {adjusted_count}건")

        confirm = input("\n위 내용으로 DB를 업데이트하시겠습니까? (yes/no): ").strip().lower()
        if confirm == "yes":
            db.commit()
            print("완료: 포지션 재조정이 저장되었습니다.")
        else:
            db.rollback()
            print("취소: 변경사항이 반영되지 않았습니다.")

    finally:
        db.close()


if __name__ == "__main__":
    rebalance()
