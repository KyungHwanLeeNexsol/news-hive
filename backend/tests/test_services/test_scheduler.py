"""scheduler 서비스 테스트.

각 스케줄러 job 핸들러 함수가 올바른 서비스를 호출하는지 검증한다.
외부 의존성은 모두 mock 처리한다.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.services.scheduler import (
    _cleanup_old_articles,
    _run_crawl_job,
    _run_daily_briefing,
    _run_dart_crawl,
    _run_news_impact_backfill,
    _run_news_impact_cleanup,
    _run_signal_verification,
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
        mock_arun.return_value = 5
        # sentiment backfill 대상: 빈 리스트 반환
        mock_db.query.return_value.filter.return_value.all.return_value = []

        _run_crawl_job()

        mock_cleanup.assert_called_once_with(mock_db)
        mock_arun.assert_called_once()  # crawl_all_news async 호출
        mock_db.close.assert_called_once()

    @patch("app.services.scheduler._cleanup_old_articles")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_crawl_exception(
        self, mock_session_cls, mock_arun, mock_cleanup,
    ) -> None:
        """크롤링 실패 시 예외가 전파되지 않고 db.close()가 호출된다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_cleanup.side_effect = Exception("DB Error")

        _run_crawl_job()

        mock_db.close.assert_called_once()


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

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_briefing_exception(
        self, mock_session_cls, mock_arun,
    ) -> None:
        """브리핑 생성 실패 시 예외가 전파되지 않는다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("AI Error")

        _run_daily_briefing()

        mock_db.close.assert_called_once()


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

    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_cleanup_exception(
        self, mock_session_cls, mock_arun,
    ) -> None:
        """정리 실패 시 예외가 전파되지 않는다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.side_effect = Exception("DB Error")

        _run_news_impact_cleanup()

        mock_db.close.assert_called_once()
