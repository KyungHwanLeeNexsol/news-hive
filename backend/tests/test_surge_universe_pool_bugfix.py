"""2026-07-01 급등예측 파이프라인 버그픽스 3종 검증 테스트.

Fix 1: Pool C 상한(15%) 제거 — 재진입 급등주(예: 금호건설 20%+) 포함 확인
Fix 2: SSL OperationalError 시 세션 재생성 후 1회 재시도
Fix 3: pool_counts 영속화 라운드트립 (persist_pool_counts -> get_pool_counts_for_date)
"""

from __future__ import annotations

from datetime import date as _date
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services import scheduler as scheduler_module
from app.services.surge_detector import build_scan_universe
from app.services.surge_universe_pool_service import (
    get_pool_counts_for_date,
    persist_pool_counts,
)
from app.surge_config.surge_settings import get_surge_config


# ---------------------------------------------------------------------------
# Fix 1: Pool C 상한(15%) 제거
# ---------------------------------------------------------------------------


class TestPoolCUpperBoundRemoved:
    """build_scan_universe의 Pool C가 더 이상 15%로 재진입을 차단하지 않는다."""

    def test_change_rate_over_15_percent_included_in_pool_c(self, db: Session):
        """20% 급등(예: 반복 상한가 종목 002990 유사 케이스)도 Pool C에 포함되어야 한다."""
        today = _date.today()
        db.add(
            SurgeActualOutcome(
                trading_date=today,
                stock_code="002990",
                stock_name="금호건설",
                change_rate=29.8,
                was_surge=True,
                market="KOSPI",
            )
        )
        db.commit()

        cfg = get_surge_config()
        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            _universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert entry_pool_map.get("002990") == "pool_c", (
            "change_rate=29.8%(구 상한 15% 초과)도 Pool C에 포함되어야 한다"
        )
        assert pool_counts["pool_c"] >= 1

    def test_change_rate_within_old_range_still_included(self, db: Session):
        """기존 범위(5~15%) 종목은 회귀 없이 계속 포함되어야 한다."""
        today = _date.today()
        db.add(
            SurgeActualOutcome(
                trading_date=today,
                stock_code="900001",
                stock_name="테스트종목",
                change_rate=8.0,
                was_surge=False,
                market="KOSDAQ",
            )
        )
        db.commit()

        cfg = get_surge_config()
        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            _universe, entry_pool_map, _pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert entry_pool_map.get("900001") == "pool_c"


# ---------------------------------------------------------------------------
# Fix 2: SSL OperationalError 재시도
# ---------------------------------------------------------------------------


class TestSurgeCollectOutcomesSSLRetry:
    """_run_surge_collect_outcomes: OperationalError 시 새 세션으로 1회 재시도."""

    def test_retry_succeeds_after_ssl_failure(self, monkeypatch):
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        mock_collect = AsyncMock(
            side_effect=[
                OperationalError(
                    "SELECT 1", {}, Exception("SSL connection has been closed unexpectedly")
                ),
                7,
            ]
        )
        fake_sessions = [MagicMock(name="session_1"), MagicMock(name="session_2")]

        with patch(
            "app.services.surge_actual_outcome_service.collect_daily_surge_outcomes",
            mock_collect,
        ), patch.object(scheduler_module, "SessionLocal", side_effect=fake_sessions):
            scheduler_module._run_surge_collect_outcomes()

        assert mock_collect.call_count == 2, "SSL 오류 후 정확히 1회 재시도해야 한다"
        # 첫 세션은 오염되어 폐기, 두 번째(새) 세션으로 재시도 성공
        fake_sessions[0].close.assert_called()
        fake_sessions[1].close.assert_called()

    def test_retry_failure_does_not_raise(self, monkeypatch):
        """재시도까지 실패해도 스케줄러로 예외가 전파되지 않아야 한다 (fail-open)."""
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        mock_collect = AsyncMock(
            side_effect=[
                OperationalError("SELECT 1", {}, Exception("ssl closed")),
                OperationalError("SELECT 1", {}, Exception("ssl closed again")),
            ]
        )
        fake_sessions = [MagicMock(name="session_1"), MagicMock(name="session_2")]

        with patch(
            "app.services.surge_actual_outcome_service.collect_daily_surge_outcomes",
            mock_collect,
        ), patch.object(scheduler_module, "SessionLocal", side_effect=fake_sessions):
            # 예외가 밖으로 전파되면 안 된다
            scheduler_module._run_surge_collect_outcomes()

        assert mock_collect.call_count == 2


# ---------------------------------------------------------------------------
# Fix 3: pool_counts 영속화 라운드트립
# ---------------------------------------------------------------------------


class TestPoolCountsPersistenceRoundTrip:
    """persist_pool_counts로 저장한 값을 get_pool_counts_for_date로 그대로 조회 가능해야 한다."""

    def test_round_trip(self, db: Session):
        today = _date.today()
        persist_pool_counts(
            db,
            today,
            {"pool_a": 3, "pool_b": 5, "pool_c": 12, "scan_universe_size": 40},
        )
        db.commit()

        loaded = get_pool_counts_for_date(db, today)

        assert loaded == {
            "pool_a": 3,
            "pool_b": 5,
            "pool_c": 12,
            "scan_universe_size": 40,
        }

    def test_upsert_updates_existing_record(self, db: Session):
        today = _date.today()
        persist_pool_counts(
            db, today, {"pool_a": 1, "pool_b": 1, "pool_c": 1, "scan_universe_size": 3}
        )
        db.commit()

        persist_pool_counts(
            db,
            today,
            {"pool_a": 9, "pool_b": 9, "pool_c": 9, "scan_universe_size": 27},
        )
        db.commit()

        loaded = get_pool_counts_for_date(db, today)
        assert loaded["pool_a"] == 9
        assert loaded["scan_universe_size"] == 27

    def test_missing_date_returns_none(self, db: Session):
        from datetime import timedelta

        result = get_pool_counts_for_date(db, _date.today() - timedelta(days=365))
        assert result is None
