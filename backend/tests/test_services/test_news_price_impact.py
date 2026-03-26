"""news_price_impact_service 테스트.

capture_price_snapshots, backfill_prices, get_news_impact,
get_stock_impact_stats, cleanup_old_impacts 함수를 검증한다.
외부 가격 조회(naver_finance)는 mock 처리한다.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.news_price_impact import NewsPriceImpact
from app.services.news_price_impact_service import (
    backfill_prices,
    capture_price_snapshots,
    cleanup_old_impacts,
    get_news_impact,
    get_stock_impact_stats,
)


def _make_fund(current_price: float | None) -> SimpleNamespace:
    """fetch_stock_fundamentals_batch 반환값 모사."""
    return SimpleNamespace(current_price=current_price)


def _run(coro):
    """async 함수를 동기적으로 실행하는 헬퍼."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# capture_price_snapshots
# ---------------------------------------------------------------------------

class TestCapturePriceSnapshots:
    """capture_price_snapshots 함수 검증."""

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_captures_snapshot_for_valid_stock(
        self, mock_fetch, db: Session, make_stock, make_news,
    ) -> None:
        """stock_id가 있는 관계에 대해 가격 스냅샷을 생성한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        mock_fetch.return_value = {"005930": _make_fund(50000.0)}

        pairs = [(news.id, stock.id, None)]
        count = _run(capture_price_snapshots(db, pairs))

        assert count == 1
        impact = db.query(NewsPriceImpact).first()
        assert impact is not None
        assert impact.news_id == news.id
        assert impact.stock_id == stock.id
        assert impact.price_at_news == 50000.0

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_skips_pairs_without_stock_id(
        self, mock_fetch, db: Session, make_news,
    ) -> None:
        """stock_id가 None인 항목(섹터 전용)은 건너뛴다 (REQ-NPI-005)."""
        news = make_news()
        pairs = [(news.id, None, None)]
        count = _run(capture_price_snapshots(db, pairs))

        assert count == 0
        mock_fetch.assert_not_called()

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_returns_zero_on_empty_pairs(
        self, mock_fetch, db: Session,
    ) -> None:
        """빈 리스트가 전달되면 0을 반환한다."""
        count = _run(capture_price_snapshots(db, []))
        assert count == 0
        mock_fetch.assert_not_called()

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_skips_stock_with_no_price(
        self, mock_fetch, db: Session, make_stock, make_news,
    ) -> None:
        """가격이 None인 종목은 건너뛰고 계속 진행 (REQ-NPI-004)."""
        stock = make_stock(stock_code="000660")
        news = make_news()
        mock_fetch.return_value = {"000660": _make_fund(None)}

        pairs = [(news.id, stock.id, None)]
        count = _run(capture_price_snapshots(db, pairs))

        assert count == 0
        assert db.query(NewsPriceImpact).count() == 0

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_returns_zero_on_fetch_exception(
        self, mock_fetch, db: Session, make_stock, make_news,
    ) -> None:
        """가격 배치 조회 실패 시 0을 반환한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        mock_fetch.side_effect = Exception("API Error")

        pairs = [(news.id, stock.id, None)]
        count = _run(capture_price_snapshots(db, pairs))

        assert count == 0

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_captures_multiple_stocks(
        self, mock_fetch, db: Session, make_stock, make_news, make_sector,
    ) -> None:
        """여러 종목에 대해 동시에 스냅샷을 캡처한다."""
        sector = make_sector()
        s1 = make_stock(stock_code="005930", sector_id=sector.id)
        s2 = make_stock(stock_code="000660", sector_id=sector.id)
        news = make_news()
        mock_fetch.return_value = {
            "005930": _make_fund(50000.0),
            "000660": _make_fund(120000.0),
        }

        pairs = [(news.id, s1.id, None), (news.id, s2.id, None)]
        count = _run(capture_price_snapshots(db, pairs))

        assert count == 2
        assert db.query(NewsPriceImpact).count() == 2


# ---------------------------------------------------------------------------
# backfill_prices
# ---------------------------------------------------------------------------

class TestBackfillPrices:
    """backfill_prices 함수 검증."""

    def _create_impact(
        self, db: Session, stock_id: int, news_id: int,
        price_at_news: float = 10000.0,
        captured_at: datetime | None = None,
    ) -> NewsPriceImpact:
        """테스트용 NewsPriceImpact 레코드를 생성한다."""
        impact = NewsPriceImpact(
            news_id=news_id,
            stock_id=stock_id,
            price_at_news=price_at_news,
        )
        db.add(impact)
        db.flush()
        # captured_at은 server_default로 설정되지만 SQLite에서 직접 설정
        if captured_at:
            impact.captured_at = captured_at
            db.flush()
        return impact

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_backfill_1d_updates_record(
        self, mock_fetch, db: Session, make_stock, make_news,
    ) -> None:
        """1일 경과 레코드에 price_after_1d와 return_1d_pct를 갱신한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)

        impact = self._create_impact(
            db, stock.id, news.id, price_at_news=10000.0,
            captured_at=two_days_ago.replace(tzinfo=None),
        )

        mock_fetch.return_value = {"005930": _make_fund(10500.0)}

        stats = _run(backfill_prices(db))

        assert stats["updated_1d"] >= 1
        db.refresh(impact)
        assert impact.price_after_1d == 10500.0
        assert impact.return_1d_pct == 5.0

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_backfill_5d_updates_record(
        self, mock_fetch, db: Session, make_stock, make_news,
    ) -> None:
        """5일 경과 레코드에 price_after_5d와 return_5d_pct를 갱신한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)

        impact = self._create_impact(
            db, stock.id, news.id, price_at_news=10000.0,
            captured_at=six_days_ago.replace(tzinfo=None),
        )
        # 1d는 이미 채워진 상태로 시뮬레이션
        impact.price_after_1d = 10200.0
        impact.return_1d_pct = 2.0
        db.flush()

        mock_fetch.return_value = {"005930": _make_fund(11000.0)}

        stats = _run(backfill_prices(db))

        assert stats["updated_5d"] >= 1
        db.refresh(impact)
        assert impact.price_after_5d == 11000.0
        assert impact.return_5d_pct == 10.0

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_backfill_no_pending_records(
        self, mock_fetch, db: Session,
    ) -> None:
        """대상 레코드가 없으면 빈 stats를 반환한다."""
        stats = _run(backfill_prices(db))
        assert stats == {"updated_1d": 0, "updated_5d": 0}
        mock_fetch.assert_not_called()

    @patch("app.services.news_price_impact_service.fetch_stock_fundamentals_batch")
    def test_backfill_retries_on_failure(
        self, mock_fetch, db: Session, make_stock, make_news,
    ) -> None:
        """가격 조회 실패 시 3회 재시도 후 빈 stats를 반환 (REQ-NPI-009)."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        self._create_impact(
            db, stock.id, news.id, price_at_news=10000.0,
            captured_at=two_days_ago.replace(tzinfo=None),
        )

        mock_fetch.side_effect = Exception("API Error")

        stats = _run(backfill_prices(db))

        assert stats == {"updated_1d": 0, "updated_5d": 0}
        assert mock_fetch.call_count == 3


# ---------------------------------------------------------------------------
# get_news_impact
# ---------------------------------------------------------------------------

class TestGetNewsImpact:
    """get_news_impact 함수 검증."""

    def test_returns_impact_data_for_news(
        self, db: Session, make_stock, make_news,
    ) -> None:
        """뉴스 ID로 해당 뉴스의 가격 반응 데이터를 조회한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        impact = NewsPriceImpact(
            news_id=news.id, stock_id=stock.id, price_at_news=50000.0,
        )
        db.add(impact)
        db.flush()

        results = _run(get_news_impact(db, news.id))

        assert len(results) == 1
        assert results[0]["stock_id"] == stock.id
        assert results[0]["stock_name"] == stock.name
        assert results[0]["price_at_news"] == 50000.0

    def test_returns_empty_list_for_unknown_news(self, db: Session) -> None:
        """존재하지 않는 뉴스 ID에 대해 빈 리스트를 반환한다."""
        results = _run(get_news_impact(db, 99999))
        assert results == []


# ---------------------------------------------------------------------------
# get_stock_impact_stats
# ---------------------------------------------------------------------------

class TestGetStockImpactStats:
    """get_stock_impact_stats 함수 검증."""

    def test_insufficient_when_no_data(self, db: Session) -> None:
        """데이터가 없으면 insufficient 상태를 반환한다 (REQ-NPI-013)."""
        result = _run(get_stock_impact_stats(db, stock_id=99999))
        assert result["status"] == "insufficient"
        assert result["count"] == 0
        assert result["avg_1d"] is None

    def test_sufficient_with_completed_records(
        self, db: Session, make_stock, make_news,
    ) -> None:
        """5일 backfill이 완료된 레코드가 있으면 sufficient 상태와 통계를 반환한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        now = datetime.now(timezone.utc)

        impact = NewsPriceImpact(
            news_id=news.id, stock_id=stock.id, price_at_news=10000.0,
            price_after_1d=10500.0, return_1d_pct=5.0,
            price_after_5d=11000.0, return_5d_pct=10.0,
        )
        db.add(impact)
        db.flush()
        # captured_at 설정 (30일 이내)
        impact.captured_at = (now - timedelta(days=7)).replace(tzinfo=None)
        db.flush()

        result = _run(get_stock_impact_stats(db, stock.id))

        assert result["status"] == "sufficient"
        assert result["count"] == 1
        assert result["avg_1d"] == 5.0
        assert result["avg_5d"] == 10.0
        assert result["win_rate_1d"] == 100.0
        assert result["win_rate_5d"] == 100.0

    def test_stats_exclude_old_records(
        self, db: Session, make_stock, make_news,
    ) -> None:
        """days 파라미터 이전의 오래된 레코드는 통계에서 제외한다."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        now = datetime.now(timezone.utc)

        # 60일 전 레코드 (30일 기준으로 제외 대상)
        impact = NewsPriceImpact(
            news_id=news.id, stock_id=stock.id, price_at_news=10000.0,
            price_after_1d=10500.0, return_1d_pct=5.0,
            price_after_5d=11000.0, return_5d_pct=10.0,
        )
        db.add(impact)
        db.flush()
        impact.captured_at = (now - timedelta(days=60)).replace(tzinfo=None)
        db.flush()

        result = _run(get_stock_impact_stats(db, stock.id, days=30))

        assert result["status"] == "insufficient"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# cleanup_old_impacts
# ---------------------------------------------------------------------------

class TestCleanupOldImpacts:
    """cleanup_old_impacts 함수 검증."""

    def test_deletes_records_older_than_90_days(
        self, db: Session, make_stock, make_news,
    ) -> None:
        """90일 초과 레코드를 삭제한다 (REQ-NPI-016)."""
        stock = make_stock(stock_code="005930")
        news = make_news()
        now = datetime.now(timezone.utc)

        old_impact = NewsPriceImpact(
            news_id=news.id, stock_id=stock.id, price_at_news=10000.0,
        )
        db.add(old_impact)
        db.flush()
        old_impact.created_at = (now - timedelta(days=100)).replace(tzinfo=None)
        db.flush()

        recent_impact = NewsPriceImpact(
            news_id=news.id, stock_id=stock.id, price_at_news=11000.0,
        )
        db.add(recent_impact)
        db.flush()
        recent_impact.created_at = (now - timedelta(days=30)).replace(tzinfo=None)
        db.flush()

        deleted = _run(cleanup_old_impacts(db))

        assert deleted == 1
        remaining = db.query(NewsPriceImpact).all()
        assert len(remaining) == 1
        assert remaining[0].price_at_news == 11000.0

    def test_returns_zero_when_no_old_records(self, db: Session) -> None:
        """삭제할 레코드가 없으면 0을 반환한다."""
        deleted = _run(cleanup_old_impacts(db))
        assert deleted == 0
