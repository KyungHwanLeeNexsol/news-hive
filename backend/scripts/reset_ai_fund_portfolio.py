"""AI 펀드매니저 포트폴리오 초기화 스크립트.

활성 VirtualPortfolio를 1억원으로 리셋하고,
연결된 VirtualTrade / PortfolioSnapshot을 모두 삭제한다.
FundSignal 데이터는 보존 (적중률 검증 이력 유지).

사용법 (서버):
    cd ~/news-hive/backend
    source venv/bin/activate
    python scripts/reset_ai_fund_portfolio.py

옵션:
    --dry-run   실제 변경 없이 삭제 대상 건수만 출력
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.main import app  # noqa: E402, F401  — 모델 매퍼 초기화용
from app.database import SessionLocal  # noqa: E402
from app.models.virtual_portfolio import (  # noqa: E402
    PortfolioSnapshot,
    VirtualPortfolio,
    VirtualTrade,
)

INITIAL_CAPITAL = 100_000_000  # 1억원


def reset_portfolio(dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        portfolio = (
            db.query(VirtualPortfolio)
            .filter(VirtualPortfolio.is_active.is_(True))
            .first()
        )

        if portfolio is None:
            print("활성 포트폴리오 없음 — 초기화 대상 없음")
            return

        trade_count = (
            db.query(VirtualTrade)
            .filter(VirtualTrade.portfolio_id == portfolio.id)
            .count()
        )
        snapshot_count = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.portfolio_id == portfolio.id)
            .count()
        )

        print(f"초기화 대상 포트폴리오: id={portfolio.id}, name={portfolio.name!r}")
        print(f"  현재 현금: {portfolio.current_cash:,}원")
        print(f"  삭제 예정 VirtualTrade: {trade_count}건")
        print(f"  삭제 예정 PortfolioSnapshot: {snapshot_count}건")

        if dry_run:
            print("\n[DRY RUN] 변경 없이 종료")
            return

        # 1. VirtualTrade 전체 삭제
        db.query(VirtualTrade).filter(
            VirtualTrade.portfolio_id == portfolio.id
        ).delete(synchronize_session=False)

        # 2. PortfolioSnapshot 전체 삭제
        db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.portfolio_id == portfolio.id
        ).delete(synchronize_session=False)

        # 3. 포트폴리오 현금 및 방어모드 초기화
        portfolio.current_cash = INITIAL_CAPITAL
        portfolio.is_defensive_mode = False
        portfolio.defensive_mode_entered_at = None

        db.commit()
        print(
            f"\n초기화 완료: VirtualTrade {trade_count}건 삭제, "
            f"PortfolioSnapshot {snapshot_count}건 삭제, "
            f"현금 {INITIAL_CAPITAL:,}원으로 초기화"
        )
        print("FundSignal 데이터는 보존됨 (적중률 검증 이력 유지)")

    except Exception as e:
        db.rollback()
        print(f"오류 발생: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 펀드매니저 포트폴리오 초기화")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 삭제 대상 건수만 출력",
    )
    args = parser.parse_args()
    reset_portfolio(dry_run=args.dry_run)
