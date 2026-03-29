"""scheduler 서비스 테스트.

각 스케줄러 job 핸들러 함수가 올바른 서비스를 호출하는지 검증한다.
외부 의존성은 모두 mock 처리한다.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.services.scheduler import (
    _cleanup_old_articles,
    _cleanup_old_disclosures,
    _run_commodity_news_crawl,
    _run_commodity_price_fetch,
    _run_crawl_job,
    _run_daily_briefing,
    _run_dart_crawl,
    _run_exit_check,
    _run_fast_verify,
    _run_ml_feature_capture,
    _run_news_impact_backfill,
    _run_news_impact_cleanup,
    _run_portfolio_snapshot,
    _run_relation_inference,
    _run_sector_momentum,
    _run_signal_verification,
    _update_market_caps,
    start_scheduler,
    stop_scheduler,
    scheduler,
)


class TestRunCrawlJob:
    """_run_crawl_job이 올바른 서비스를 호출하는지 검증."""

    @patch("app.services.scheduler._cleanup_old_articles")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_crawl_and_sentiment(
        self, mock_session_cls, mock_arun, mock_cleanup,
    ) -> None:
        """crawl_all_news를 호출하고 sentiment 없는 기사를 backfill한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # asyncio.run은 crawl_all_news와 detect_macro_risks에서 호출됨
        mock_arun.side_effect = [5, []]  # crawl=5건, macro_risks=빈 리스트
        # sentiment backfill 대상: 빈 리스트 반환
        mock_db.query.return_value.filter.return_value.all.return_value = []

        _run_crawl_job()

        mock_cleanup.assert_called_once_with(mock_db)
        assert mock_arun.call_count >= 1  # crawl_all_news + detect_macro_risks
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler._cleanup_old_articles")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_crawl_exception(
        self, mock_session_cls, mock_arun, mock_cleanup, mock_sleep,
    ) -> None:
        """크롤링 실패 시 예외가 전파되지 않고 db.close()가 호출된다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_cleanup.side_effect = Exception("DB Error")

        _run_crawl_job()

        mock_db.close.assert_called()


class TestRunDailyBriefing:
    """_run_daily_briefing이 generate_daily_briefing을 호출하는지 검증."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_generate_daily_briefing(
        self, mock_session_cls, mock_arun,
    ) -> None:
        """generate_daily_briefing을 호출한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = MagicMock(briefing_date="2026-03-26")

        _run_daily_briefing()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_briefing_exception(
        self, mock_session_cls, mock_arun, mock_sleep,
    ) -> None:
        """브리핑 생성 실패 시 예외가 전파되지 않는다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("AI Error")

        _run_daily_briefing()

        mock_db.close.assert_called()


class TestRunSignalVerification:
    """_run_signal_verification이 verify_signals를 호출하는지 검증."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_verify_signals(
        self, mock_session_cls, mock_arun,
    ) -> None:
        """verify_signals를 호출한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = {"verified": 3, "updated": 2}

        _run_signal_verification()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()


class TestRunDartCrawl:
    """_run_dart_crawl이 disclosure 크롤러를 호출하는지 검증."""

    @patch("app.services.scheduler._cleanup_old_disclosures")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_dart_crawler(
        self, mock_session_cls, mock_arun, mock_cleanup,
    ) -> None:
        """fetch_dart_disclosures를 호출하고 backfill을 수행한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = 10

        _run_dart_crawl()

        mock_cleanup.assert_called_once_with(mock_db)
        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()


class TestRunNewsImpactBackfill:
    """_run_news_impact_backfill이 backfill_prices를 호출하는지 검증."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_backfill_prices(
        self, mock_session_cls, mock_arun,
    ) -> None:
        """backfill_prices를 호출한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = {"updated_1d": 5, "updated_5d": 3}

        _run_news_impact_backfill()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()


class TestRunNewsImpactCleanup:
    """_run_news_impact_cleanup이 cleanup_old_impacts를 호출하는지 검증."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_cleanup_old_impacts(
        self, mock_session_cls, mock_arun,
    ) -> None:
        """cleanup_old_impacts를 호출한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = 7

        _run_news_impact_cleanup()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_cleanup_exception(
        self, mock_session_cls, mock_arun, mock_sleep,
    ) -> None:
        """정리 실패 시 예외가 전파되지 않는다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("DB Error")

        _run_news_impact_cleanup()

        mock_db.close.assert_called()


# ---------------------------------------------------------------------------
# 추가 job 핸들러 테스트
# ---------------------------------------------------------------------------


class TestRunFastVerify:
    """_run_fast_verify가 fast_verify를 호출하는지 검증."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_fast_verify(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = {"checked": 5, "early_warnings": 1}

        _run_fast_verify()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_fast_verify_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        """fast_verify 실패 시 예외가 전파되지 않는다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("Error")

        _run_fast_verify()

        mock_db.close.assert_called()


class TestRunCommodityPriceFetch:
    """_run_commodity_price_fetch 테스트."""

    @patch("app.services.commodity_service.check_commodity_alerts", return_value=[])
    @patch("app.services.commodity_service.fetch_commodity_prices", return_value=True)
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_commodity_services(self, mock_session_cls, mock_fetch, mock_alerts) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        _run_commodity_price_fetch()

        mock_fetch.assert_called_once_with(mock_db)
        mock_alerts.assert_called_once_with(mock_db)
        mock_db.close.assert_called_once()

    @patch("app.services.commodity_service.check_commodity_alerts")
    @patch("app.services.commodity_service.fetch_commodity_prices", return_value=False)
    @patch("app.services.scheduler.SessionLocal")
    def test_skips_alerts_when_no_update(self, mock_session_cls, mock_fetch, mock_alerts) -> None:
        """가격 업데이트가 없으면 알림 체크를 건너뛴다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        _run_commodity_price_fetch()

        mock_fetch.assert_called_once()
        mock_alerts.assert_not_called()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.commodity_service.fetch_commodity_prices", side_effect=Exception("err"))
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_fetch, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        _run_commodity_price_fetch()

        mock_db.close.assert_called()


class TestRunCommodityNewsCrawl:
    """_run_commodity_news_crawl 테스트."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_crawl_commodity_news(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = 15

        _run_commodity_news_crawl()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("crawl error")

        _run_commodity_news_crawl()

        mock_db.close.assert_called()


class TestRunRelationInference:
    """_run_relation_inference 주간 관계 추론 테스트."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_run_incremental_inference(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = {"inter_sector": 3, "intra_sector": 5}

        _run_relation_inference()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("inference error")

        _run_relation_inference()

        mock_db.close.assert_called()


class TestRunExitCheck:
    """_run_exit_check 청산 조건 확인 테스트."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_check_exit_conditions(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = {"closed": 2, "reasons": "stop_loss: 1, target_hit: 1"}

        _run_exit_check()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("exit check error")

        _run_exit_check()

        mock_db.close.assert_called()


class TestRunPortfolioSnapshot:
    """_run_portfolio_snapshot 포트폴리오 스냅샷 테스트."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_take_daily_snapshot(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = None

        _run_portfolio_snapshot()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("snapshot error")

        _run_portfolio_snapshot()

        mock_db.close.assert_called()


class TestRunSectorMomentum:
    """_run_sector_momentum 섹터 모멘텀 테스트."""

    @patch("app.services.sector_momentum.detect_sector_rotation", return_value=[])
    @patch("app.services.sector_momentum.detect_capital_inflow", return_value=[])
    @patch("app.services.sector_momentum.detect_momentum_sectors", return_value=[])
    @patch("app.services.scheduler.asyncio.run", return_value=10)
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_sector_momentum_services(
        self, mock_session_cls, mock_arun, mock_momentum, mock_inflow, mock_rotation,
    ) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        _run_sector_momentum()

        mock_momentum.assert_called_once_with(mock_db)
        mock_inflow.assert_called_once_with(mock_db)
        mock_rotation.assert_called_once_with(mock_db)
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("momentum error")

        _run_sector_momentum()

        mock_db.close.assert_called()


class TestRunMlFeatureCapture:
    """_run_ml_feature_capture ML 피처 스냅샷 테스트."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_capture_daily_features(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_snapshot = MagicMock(date="2026-03-29")
        mock_arun.return_value = mock_snapshot

        _run_ml_feature_capture()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("ML error")

        _run_ml_feature_capture()

        mock_db.close.assert_called()


class TestCleanupOldDisclosures:
    """_cleanup_old_disclosures 공시 정리 테스트."""

    def test_deletes_old_disclosures(self) -> None:
        """7일 초과 공시를 삭제한다."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 5

        _cleanup_old_disclosures(mock_db)

        mock_db.commit.assert_called_once()

    def test_skips_when_nothing_to_delete(self) -> None:
        """삭제할 공시가 없으면 commit하지 않는다."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 0

        _cleanup_old_disclosures(mock_db)

        mock_db.commit.assert_not_called()


class TestUpdateMarketCaps:
    """_update_market_caps 시가총액 업데이트 테스트."""

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_fetch_naver_stock_list(self, mock_session_cls, mock_arun) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # 빈 데이터 반환하여 early return
        mock_arun.return_value = ([], 0)

        _update_market_caps()

        # 최소 1회는 asyncio.run 호출
        assert mock_arun.called
        mock_db.close.assert_called_once()

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("market cap error")

        _update_market_caps()

        mock_db.close.assert_called()


class TestStartStopScheduler:
    """start_scheduler / stop_scheduler 테스트."""

    @patch("app.services.scheduler.scheduler")
    @patch("app.services.scheduler.settings")
    def test_start_scheduler_registers_jobs(self, mock_settings, mock_sched) -> None:
        """start_scheduler가 모든 job을 등록한다."""
        mock_settings.NEWS_CRAWL_INTERVAL_MINUTES = 30
        mock_settings.DART_CRAWL_INTERVAL_MINUTES = 60
        mock_settings.MARKET_CAP_UPDATE_HOURS = 6

        start_scheduler()

        # add_job이 여러 번 호출되어야 한다 (최소 15개 job)
        assert mock_sched.add_job.call_count >= 15
        mock_sched.start.assert_called_once()

    @patch("app.services.scheduler.scheduler")
    def test_stop_scheduler_when_running(self, mock_sched) -> None:
        """스케줄러가 실행 중이면 shutdown한다."""
        mock_sched.running = True

        stop_scheduler()

        mock_sched.shutdown.assert_called_once_with(wait=False)

    @patch("app.services.scheduler.scheduler")
    def test_stop_scheduler_when_not_running(self, mock_sched) -> None:
        """스케줄러가 실행 중이 아니면 shutdown하지 않는다."""
        mock_sched.running = False

        stop_scheduler()

        mock_sched.shutdown.assert_not_called()
