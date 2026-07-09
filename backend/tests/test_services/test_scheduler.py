"""scheduler 서비스 테스트.

각 스케줄러 job 핸들러 함수가 올바른 서비스를 호출하는지 검증한다.
외부 의존성은 모두 mock 처리한다.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.scheduler import (
    _check_dart_health,
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
)


class TestRunCrawlJob:
    """_run_crawl_job이 올바른 서비스를 호출하는지 검증."""

    @patch("app.services.scheduler._run_keyword_matching")
    @patch("app.services.scheduler._cleanup_old_articles")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_crawl_and_sentiment(
        self, mock_session_cls, mock_arun, mock_cleanup, mock_kw_match,
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


class TestRunDailyBriefing:
    """_run_daily_briefing 데일리 브리핑 생성 job 테스트.

    briefing.market_sentiment는 DailyBriefing 모델(app/models/daily_briefing.py)에
    존재하지 않는 컬럼이다. 로그 라인이 이를 참조하면 AttributeError가 발생해
    retry_with_backoff가 3회 모두 소진되고, 실제로는 이미 커밋된 브리핑임에도
    CRITICAL 실패로 오기록된다(순수 로깅 버그, 데이터 영향 없음).
    """

    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler._is_kr_market_open", return_value=True)
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_characterize_generated_briefing_logs_without_attribute_error(
        self, mock_session_cls, mock_arun, mock_market_open, mock_sleep,
    ) -> None:
        """재현(Rule 4): 존재하지 않는 briefing.market_sentiment 참조로 AttributeError가
        발생하면 retry_with_backoff가 3회 모두 소진(sleep 2회 호출)된다. 수정 후에는
        실제 모델 컬럼만 참조하여 첫 시도에서 성공해야 한다(재시도 없음).
        """
        from app.models.daily_briefing import DailyBriefing

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_briefing = MagicMock(spec=DailyBriefing)
        mock_briefing.id = 42
        mock_briefing.ai_model = "gemini-2.0-flash"
        mock_arun.return_value = mock_briefing

        _run_daily_briefing()

        mock_sleep.assert_not_called()
        assert mock_arun.call_count == 1
        mock_db.close.assert_called_once()

    @patch("app.services.scheduler._is_kr_market_open", return_value=False)
    @patch("app.services.scheduler.SessionLocal")
    def test_skips_on_weekend(self, mock_session_cls, mock_market_open) -> None:
        """주말에는 브리핑 생성을 건너뛴다."""
        _run_daily_briefing()

        mock_session_cls.assert_not_called()


class TestRunDartCrawl:
    """_run_dart_crawl이 disclosure 크롤러를 호출하는지 검증."""

    @patch("app.services.scheduler._run_keyword_matching")
    @patch("app.services.scheduler._cleanup_old_disclosures")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_dart_crawler(
        self, mock_session_cls, mock_arun, mock_cleanup, mock_kw_match,
    ) -> None:
        """fetch_dart_disclosures를 호출하고 backfill을 수행한다."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = 10

        _run_dart_crawl()

        mock_cleanup.assert_called_once_with(mock_db)
        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    # -------------------------------------------------------------------
    # SPEC-AI-073 REQ-AI073-001: 정리 실패가 수집을 차단하지 않도록 격리
    # -------------------------------------------------------------------

    @patch("app.services.scheduler._run_keyword_matching")
    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler._cleanup_old_disclosures")
    @patch("app.services.scheduler.SessionLocal")
    def test_characterize_cleanup_failure_does_not_block_fetch(
        self, mock_session_cls, mock_cleanup, mock_arun, mock_sleep, mock_kw_match,
    ) -> None:
        """AC-073-001/REQ-AI073-001 재현: 정리 실패가 수집을 막지 않아야 한다.

        재현(Rule 4): 격리 전 코드에서는 정리 예외가 그대로 전파되어
        retry_with_backoff가 3회 모두 재시도해도 fetch_dart_disclosures
        (asyncio.run)가 단 한 번도 호출되지 못한 채 종료됐다 — 수정 후에는
        정리 실패에도 불구하고 같은 시도 내에서 수집이 진행되어야 한다.
        """
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_cleanup.side_effect = Exception("FK violation simulation")
        mock_arun.return_value = 7

        _run_dart_crawl()

        mock_arun.assert_called_once()
        mock_kw_match.assert_called_once()
        # 정리 실패 후 수집 진행 전 세션이 rollback으로 복구되어야 한다(트랜잭션 abort 방지)
        mock_db.rollback.assert_called()

    @patch("app.services.scheduler._run_keyword_matching")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler._cleanup_old_disclosures")
    @patch("app.services.scheduler.SessionLocal")
    def test_cleanup_success_unaffected_by_isolation(
        self, mock_session_cls, mock_cleanup, mock_arun, mock_kw_match,
    ) -> None:
        """EC-1: 정리 성공 시 격리 도입 후에도 정상 동작(회귀 없음)."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = 3

        _run_dart_crawl()

        mock_cleanup.assert_called_once_with(mock_db)
        mock_arun.assert_called_once()
        mock_kw_match.assert_called_once()


class TestCheckDartHealthWatchdog:
    """SPEC-AI-073 REQ-AI073-005: watchdog 자동 복구 경로 회귀 가드.

    _check_dart_health의 2시간 임계·Telegram 알림 로직 자체는 변경하지 않는다(diff 0).
    본 테스트는 watchdog가 stale 감지 시 여전히 _run_dart_crawl을 직접 호출하며(REQ-001/002의
    격리·FK 혜택을 자동으로 상속), 임계/알림 로직이 그대로임을 확인하는 회귀 가드다.
    """

    @staticmethod
    def _fixed_now_kst_daytime():
        """장 시간(07~18 KST) 내 고정 시각을 반환하는 datetime 서브클래스.

        test_macro_risk.py의 FakeDatetime 패턴과 일관되게, datetime.now(tz)의 tz 인자에
        따라 올바른 절대시각을 반환해 now_kst.hour 게이트와 now_utc 경과시간 계산이 모두
        실제 datetime 연산으로 정확히 동작하도록 한다.
        """
        from datetime import datetime, timezone

        fixed_utc = datetime(2026, 7, 8, 1, 0, tzinfo=timezone.utc)  # KST 10:00

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_utc.replace(tzinfo=None)
                return fixed_utc.astimezone(tz)

        return FixedDatetime, fixed_utc

    @patch("app.services.scheduler.threading.Thread")
    @patch("app.services.scheduler._send_dart_stale_alert")
    @patch("app.services.scheduler.SessionLocal")
    def test_stale_detection_triggers_run_dart_crawl_recovery_thread(
        self, mock_session_cls, mock_alert, mock_thread_cls,
    ) -> None:
        """2시간 초과 stale 감지 시 CRITICAL 로그 + 알림 + _run_dart_crawl 복구 스레드 시작."""
        from datetime import timedelta

        fixed_dt, fixed_utc = self._fixed_now_kst_daytime()

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # 3시간 전 마지막 수집 (2시간 임계 초과)
        stale_time = fixed_utc - timedelta(hours=3)
        mock_db.query.return_value.scalar.return_value = stale_time

        with patch("app.services.scheduler.datetime", fixed_dt):
            _check_dart_health()

        mock_alert.assert_called_once()
        mock_thread_cls.assert_called_once()
        _, thread_kwargs = mock_thread_cls.call_args
        assert thread_kwargs["target"] is _run_dart_crawl, (
            "watchdog 복구는 여전히 _run_dart_crawl을 직접 호출해야 REQ-001/002 혜택을 상속받는다"
        )
        mock_thread_cls.return_value.start.assert_called_once()

    @patch("app.services.scheduler.threading.Thread")
    @patch("app.services.scheduler._send_dart_stale_alert")
    @patch("app.services.scheduler.SessionLocal")
    def test_not_stale_skips_recovery(
        self, mock_session_cls, mock_alert, mock_thread_cls,
    ) -> None:
        """2시간 이내 수집이면 복구 스레드를 시작하지 않는다(임계 로직 diff 0)."""
        from datetime import timedelta

        fixed_dt, fixed_utc = self._fixed_now_kst_daytime()

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        recent_time = fixed_utc - timedelta(minutes=30)
        mock_db.query.return_value.scalar.return_value = recent_time

        with patch("app.services.scheduler.datetime", fixed_dt):
            _check_dart_health()

        mock_alert.assert_not_called()
        mock_thread_cls.assert_not_called()


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

    @patch("app.services.scheduler._is_kr_market_open", return_value=True)
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_calls_check_exit_conditions(self, mock_session_cls, mock_arun, mock_market_open) -> None:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_arun.return_value = {"closed": 2, "reasons": "stop_loss: 1, target_hit: 1"}

        _run_exit_check()

        mock_arun.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.scheduler._is_kr_market_open", return_value=True)
    @patch("app.services.job_retry.time.sleep")
    @patch("app.services.scheduler.asyncio.run")
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception(self, mock_session_cls, mock_arun, mock_sleep, mock_market_open) -> None:
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


class TestRunSurgeBacktestGate:
    """SPEC-AI-069 REQ-AI069-001: _run_surge_backtest_gate 래퍼 테스트."""

    @patch("app.services.scheduler._is_kr_market_open", return_value=True)
    @patch("app.services.surge_backtest.run_backtest_gate")
    @patch("app.services.scheduler.SessionLocal")
    def test_persists_verdict_record(
        self, mock_session_cls, mock_gate, mock_market_open,
    ) -> None:
        from app.services.surge_backtest import BacktestGateVerdict
        from app.services.scheduler import _run_surge_backtest_gate

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_gate.return_value = BacktestGateVerdict(
            verdict="pass",
            total_signals=25,
            directional_accuracy=0.60,
            average_return_pct=3.2,
            by_combination={"theme_cluster": {"count": 10, "accuracy": 0.6, "avg_return": 2.0}},
            min_signals=20,
            min_directional_accuracy=0.50,
            lookback_days=30,
            config_hash="abcd1234abcd1234",
        )

        _run_surge_backtest_gate()

        mock_gate.assert_called_once_with(mock_db)
        assert mock_db.add.call_count == 1
        added = mock_db.add.call_args[0][0]
        assert added.verdict == "pass"
        assert added.total_signals == 25
        assert added.config_hash == "abcd1234abcd1234"
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.services.scheduler._is_kr_market_open", return_value=False)
    @patch("app.services.scheduler.SessionLocal")
    def test_skips_on_weekend(self, mock_session_cls, mock_market_open) -> None:
        from app.services.scheduler import _run_surge_backtest_gate

        _run_surge_backtest_gate()

        mock_session_cls.assert_not_called()

    @patch("app.services.scheduler._is_kr_market_open", return_value=True)
    @patch("app.services.surge_backtest.run_backtest_gate", side_effect=Exception("gate error"))
    @patch("app.services.scheduler.SessionLocal")
    def test_handles_exception_and_closes_db(
        self, mock_session_cls, mock_gate, mock_market_open,
    ) -> None:
        from app.services.scheduler import _run_surge_backtest_gate

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        with pytest.raises(Exception, match="gate error"):
            _run_surge_backtest_gate()

        mock_db.close.assert_called_once()


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
