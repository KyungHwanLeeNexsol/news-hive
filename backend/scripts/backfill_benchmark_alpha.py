"""기존 포트폴리오 스냅샷 및 fund_signal 에 KOSPI 벤치마크/알파 소급 기록.

사용법 (서버):
    cd ~/news-hive/backend
    source venv/bin/activate
    python scripts/backfill_benchmark_alpha.py

옵션:
    --recompute-correctness  이미 검증된 시그널의 is_correct 를 알파 기반으로 재판정
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")

# FastAPI 앱을 임포트해 모든 모델을 로드해야 SQLAlchemy 매퍼가 초기화됨
from app.main import app  # noqa: E402, F401
from app.database import SessionLocal  # noqa: E402
from app.models.fund_signal import FundSignal  # noqa: E402
from app.models.virtual_portfolio import (  # noqa: E402
    PortfolioSnapshot,
    VirtualPortfolio,
    VirtualTrade,
)
from app.services.benchmark import (  # noqa: E402
    get_kospi_close,
    get_kospi_cumulative_return,
    get_kospi_period_return,
)

KST = ZoneInfo("Asia/Seoul")


async def backfill_snapshots() -> int:
    db = SessionLocal()
    updated = 0
    try:
        portfolio = (
            db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
        )
        if not portfolio:
            print("활성 포트폴리오 없음 — 스냅샷 백필 스킵")
            return 0

        snaps = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.portfolio_id == portfolio.id)
            .order_by(PortfolioSnapshot.snapshot_date.asc())
            .all()
        )
        if not snaps:
            print("스냅샷 없음")
            return 0

        base_date = snaps[0].snapshot_date.astimezone(KST).date()
        print(f"[snapshot] base_date={base_date}, 총 {len(snaps)}건")

        for snap in snaps:
            snap_date = snap.snapshot_date.astimezone(KST).date()
            close = await get_kospi_close(snap_date)
            cum = await get_kospi_cumulative_return(base_date, snap_date)
            snap.benchmark_value = close
            snap.benchmark_cumulative_return_pct = cum
            if cum is not None and snap.cumulative_return_pct is not None:
                snap.alpha_pct = round(snap.cumulative_return_pct - cum, 4)
            updated += 1
            print(
                f"  {snap_date} total={snap.total_value:,} "
                f"cum={snap.cumulative_return_pct}% "
                f"KOSPI={cum}% α={snap.alpha_pct}%"
            )

        db.commit()
        print(f"[snapshot] 업데이트 {updated}건")
        return updated
    finally:
        db.close()


async def backfill_signals(recompute_correctness: bool = False) -> int:
    db = SessionLocal()
    updated = 0
    try:
        signals = (
            db.query(FundSignal)
            .filter(
                FundSignal.price_after_5d.isnot(None),
                FundSignal.return_pct.isnot(None),
                FundSignal.verified_at.isnot(None),
            )
            .order_by(FundSignal.id.asc())
            .all()
        )
        print(f"[signals] 검증 완료 시그널 {len(signals)}건 백필 대상")

        for sig in signals:
            if not sig.created_at or not sig.verified_at:
                continue
            bench = await get_kospi_period_return(sig.created_at, sig.verified_at)
            if bench is None:
                continue
            sig.benchmark_return_pct = round(bench, 2)
            sig.alpha_pct = round((sig.return_pct or 0) - bench, 2)
            if recompute_correctness and sig.alpha_pct is not None:
                if sig.signal == "buy":
                    sig.is_correct = sig.alpha_pct > 0
                elif sig.signal == "sell":
                    sig.is_correct = sig.alpha_pct < 0
            updated += 1

        db.commit()
        print(f"[signals] 업데이트 {updated}건 (recompute={recompute_correctness})")
        return updated
    finally:
        db.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recompute-correctness",
        action="store_true",
        help="알파 기반으로 is_correct 재판정",
    )
    parser.add_argument(
        "--skip-snapshots",
        action="store_true",
        help="스냅샷 백필 건너뛰기",
    )
    parser.add_argument(
        "--skip-signals",
        action="store_true",
        help="시그널 백필 건너뛰기",
    )
    args = parser.parse_args()

    if not args.skip_snapshots:
        await backfill_snapshots()
    if not args.skip_signals:
        await backfill_signals(recompute_correctness=args.recompute_correctness)


if __name__ == "__main__":
    asyncio.run(main())
