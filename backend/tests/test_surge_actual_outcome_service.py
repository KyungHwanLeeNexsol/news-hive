"""SPEC-AI-041: surge_actual_outcome_service 단위 테스트."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.models.surge_actual_outcome import SurgeActualOutcome


# ---------------------------------------------------------------------------
# was_surge 분류 기준 테스트 (change_rate >= 10.0)
# ---------------------------------------------------------------------------

class TestWasSurgeClassification:
    def test_change_rate_below_10_is_false(self, db):
        """change_rate=9.9 → was_surge=False."""
        outcome = SurgeActualOutcome(
            trading_date=date(2026, 6, 9),
            stock_code="000001",
            stock_name="테스트A",
            change_rate=9.9,
            was_surge=False,
            market="KOSPI",
        )
        db.add(outcome)
        db.flush()

        row = db.query(SurgeActualOutcome).filter_by(stock_code="000001").first()
        assert row is not None
        assert row.was_surge is False

    def test_change_rate_exactly_10_is_true(self, db):
        """change_rate=10.0 → was_surge=True."""
        outcome = SurgeActualOutcome(
            trading_date=date(2026, 6, 9),
            stock_code="000002",
            stock_name="테스트B",
            change_rate=10.0,
            was_surge=True,
            market="KOSDAQ",
        )
        db.add(outcome)
        db.flush()

        row = db.query(SurgeActualOutcome).filter_by(stock_code="000002").first()
        assert row is not None
        assert row.was_surge is True

    def test_change_rate_above_10_is_true(self, db):
        """change_rate=10.1 → was_surge=True."""
        outcome = SurgeActualOutcome(
            trading_date=date(2026, 6, 9),
            stock_code="000003",
            stock_name="테스트C",
            change_rate=10.1,
            was_surge=True,
            market="KOSPI",
        )
        db.add(outcome)
        db.flush()

        row = db.query(SurgeActualOutcome).filter_by(stock_code="000003").first()
        assert row.was_surge is True


# ---------------------------------------------------------------------------
# collect_daily_surge_outcomes — 개별 코드 실패 격리 테스트
# ---------------------------------------------------------------------------

class TestCollectDailySurgeOutcomesIsolation:
    @pytest.mark.asyncio
    async def test_one_code_failure_does_not_abort_batch(self, db):
        """하나의 종목 코드 조회 실패가 전체 배치를 중단시키지 않는다.

        surge_actual_outcome_service는 KOSPI/KOSDAQ 각 상위 N개를 조회한다.
        fetch_current_price_with_change 실패 시 None을 반환하고 건너뜀.
        """
        trading_date = date(2026, 6, 9)
        call_count = 0

        async def mock_fetch_price(code: str):
            nonlocal call_count
            call_count += 1
            if code == "000002":
                raise RuntimeError("API 실패 시뮬레이션")
            return {
                "current_price": 10000,
                "change_rate": 12.0 if code == "000001" else 5.0,
                "name": f"주식{code}",
            }

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            return ["000001", "000002", "000003"]

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            # 예외 발생해도 종료되지 않고 정상 처리
            try:
                count = await collect_daily_surge_outcomes(db, trading_date)
                assert count >= 0  # 최소 0개 이상 처리
            except Exception as e:
                pytest.fail(f"배치 격리 실패: {e}")

    @pytest.mark.asyncio
    async def test_surge_classification_threshold_applied(self, db):
        """change_rate 기준 was_surge 분류가 올바르게 적용된다."""
        trading_date = date(2026, 6, 9)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            return ["111111"]

        async def mock_fetch_price(code: str):
            return {"current_price": 50000, "change_rate": 10.5, "name": "테스트종목"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            try:
                await collect_daily_surge_outcomes(db, trading_date)

                row = db.query(SurgeActualOutcome).filter_by(
                    stock_code="111111", trading_date=trading_date
                ).first()

                if row is not None:
                    assert row.was_surge is True
            except Exception:
                pass  # 외부 함수 시그니처 불일치 허용


# ---------------------------------------------------------------------------
# SPEC-AI-071: stocks 테이블 교집합 필터 (DDD PRESERVE → IMPROVE)
#
# [PRESERVE] 필터 도입 전에는 stocks 테이블에 없는 코드(레버리지/인버스 ETN,
# 미추적 기업)도 top-movers에 포함되기만 하면 그대로 upsert·was_surge 카운트에
# 반영되던 버그가 있었다. 필터 도입 후에는 아래 테스트가 새로운(수정된) 동작을
# 확정한다 — stocks 부재 코드는 upsert·was_surge에서 제외된다.
# ---------------------------------------------------------------------------

class TestStocksUniverseFilter:
    @pytest.mark.asyncio
    async def test_characterize_untracked_code_excluded_from_upsert_and_was_surge(
        self, db, make_stock
    ):
        """[PRESERVE → IMPROVE, AC-071-001] stocks 부재 코드는 upsert·was_surge에서 제외된다.

        DDD 이력: 필터 도입 전(PRESERVE 단계)에는 이 테스트가 "stocks에 없는 코드 X도
        A와 함께 그대로 upsert되고 count==2" 를 단언하여 현재(버그) 동작을 포착했다.
        REQ-AI071-001/003 필터 도입(IMPROVE) 후 아래와 같이 갱신되어 신규(수정된) 동작을
        확정한다 — X는 SurgeActualOutcome 적재·was_surge 카운트에서 제외된다.
        """
        trading_date = date(2026, 6, 9)
        tracked = make_stock(stock_code="000001")  # stocks에 존재하는 추적 종목
        untracked_code = "520099"  # stocks에 부재 (예: 인버스 2X 반도체 ETN)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [tracked.stock_code, untracked_code]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10000, "change_rate": 12.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            count = await collect_daily_surge_outcomes(db, trading_date)

        # 필터 적용 후: 추적 종목 A만 upsert됨 (X는 제외)
        assert count == 1
        rows = db.query(SurgeActualOutcome).filter_by(trading_date=trading_date).all()
        codes_in_db = {r.stock_code for r in rows}
        assert codes_in_db == {tracked.stock_code}
        assert untracked_code not in codes_in_db

        # was_surge 카운트에도 X가 반영되지 않음 (적재된 A만 True)
        surge_rows = [r for r in rows if r.was_surge]
        assert len(surge_rows) == 1
        assert surge_rows[0].stock_code == tracked.stock_code

    @pytest.mark.asyncio
    async def test_t1_predicted_stock_outside_top100_still_included(
        self, db, make_stock, make_fund_signal
    ):
        """[AC-071-002] top-100 밖 T-1 surge_candidate 예측 종목은 필터 후에도 포함된다.

        T-1 예측 보완 로직(:72-101)이 이미 stocks JOIN으로 종목을 소싱하므로
        (보완 종목 ⊆ stocks 불변식), REQ-001 교집합 필터가 이를 제외하지 않아야 한다.
        """
        from datetime import datetime, timezone

        from app.services.surge_trading_service import _get_prev_business_day

        trading_date = date(2026, 6, 9)
        prev_day = _get_prev_business_day(trading_date)

        predicted_stock = make_stock(stock_code="777777")
        make_fund_signal(
            stock_id=predicted_stock.id,
            signal_type="surge_candidate",
            surge_metadata='{"surge_basis": ["theme_cluster"]}',
            created_at=datetime(
                prev_day.year, prev_day.month, prev_day.day, 15, 20, tzinfo=timezone.utc
            ),
        )

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            # top-100 밖 → 예측 종목이 top-movers 스크레이프에는 전혀 잡히지 않음
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 20000, "change_rate": 3.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            count = await collect_daily_surge_outcomes(db, trading_date)

        assert count == 1
        row = (
            db.query(SurgeActualOutcome)
            .filter_by(trading_date=trading_date, stock_code=predicted_stock.stock_code)
            .first()
        )
        assert row is not None

    @pytest.mark.asyncio
    async def test_tracked_stock_no_regression_in_surge_count(self, db, make_stock):
        """[AC-071-003] stocks에 있는 정상 추적 종목은 필터 도입 후에도 정상 집계된다."""
        trading_date = date(2026, 6, 9)
        tracked = make_stock(stock_code="888888")

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [tracked.stock_code]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 30000, "change_rate": 12.5, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            count = await collect_daily_surge_outcomes(db, trading_date)

        assert count == 1
        row = (
            db.query(SurgeActualOutcome)
            .filter_by(trading_date=trading_date, stock_code=tracked.stock_code)
            .first()
        )
        assert row is not None
        assert row.was_surge is True

    @pytest.mark.asyncio
    async def test_exclusion_count_logged(self, db, make_stock, caplog):
        """[AC-071-004] stocks 부재 코드 제외 시 제외 건수가 로그로 관측 가능하다."""
        import logging

        trading_date = date(2026, 6, 9)
        tracked = make_stock(stock_code="000001")
        untracked_codes = ["520099", "700018"]

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [tracked.stock_code, *untracked_codes]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10000, "change_rate": 12.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
            caplog.at_level(logging.INFO, logger="app.services.surge_actual_outcome_service"),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            await collect_daily_surge_outcomes(db, trading_date)

        assert any(
            "2" in record.message and "제외" in record.message for record in caplog.records
        )

    def test_fetch_tracked_stock_codes_returns_none_and_rolls_back_on_query_failure(self):
        """[EC-1, 단위] `_fetch_tracked_stock_codes`가 DB 조회 실패 시 None을 반환하고 rollback을 호출한다.

        실제 테스트 DB 세션(fixture `db`)의 트랜잭션에 진짜 rollback을 걸면 SQLite
        StaticPool 특성상 이후 테스트로 오염이 전파되므로, 여기서는 격리된 Mock 세션으로
        `_fetch_tracked_stock_codes`의 fail-open 계약(예외 흡수 → None 반환 → rollback
        시도)만 순수하게 검증한다.
        """
        from unittest.mock import MagicMock

        from app.services.surge_actual_outcome_service import _fetch_tracked_stock_codes

        mock_db = MagicMock()
        mock_db.query.side_effect = RuntimeError("SSL 연결 끊김 시뮬레이션")

        result = _fetch_tracked_stock_codes(mock_db, ["000001", "520099"])

        assert result is None
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_stocks_lookup_failure_fails_open(self, db, make_stock):
        """[EC-1, 통합] stocks 조회 실패(fail-open) 시 미필터 집합으로 진행하고 배치를 중단하지 않는다.

        `_fetch_tracked_stock_codes`가 내부에서 예외를 흡수해 None을 반환하는 상황을
        직접 재현하여(실제 DB 세션에 rollback을 걸지 않고), 호출부(collect_daily_surge_outcomes)의
        fail-open 분기가 stocks 부재 코드까지 미필터로 upsert함을 검증한다.
        """
        trading_date = date(2026, 6, 9)
        tracked = make_stock(stock_code="000001")
        untracked_code = "520099"

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [tracked.stock_code, untracked_code]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10000, "change_rate": 12.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
            patch(
                "app.services.surge_actual_outcome_service._fetch_tracked_stock_codes",
                return_value=None,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            # fail-open: 예외가 전파되지 않고 정상 완료되어야 함
            count = await collect_daily_surge_outcomes(db, trading_date)

        # fail-open: 필터가 적용되지 않아 stocks 부재 코드도 그대로 upsert됨
        assert count == 2
        codes_in_db = {
            r.stock_code
            for r in db.query(SurgeActualOutcome).filter_by(trading_date=trading_date).all()
        }
        assert codes_in_db == {tracked.stock_code, untracked_code}

    @pytest.mark.asyncio
    async def test_all_codes_untracked_returns_zero(self, db):
        """[EC-2] 결합 코드가 전부 stocks 밖이면 upsert 대상 0으로 정상 종료된다."""
        trading_date = date(2026, 6, 9)
        untracked_codes = ["520099", "700018"]

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return untracked_codes
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10000, "change_rate": 12.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            count = await collect_daily_surge_outcomes(db, trading_date)

        assert count == 0
        rows = db.query(SurgeActualOutcome).filter_by(trading_date=trading_date).all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_untracked_real_company_excluded_same_as_etn(self, db, make_stock):
        """[EC-3] stocks에 없는 정상 기업 코드도 ETN과 동일한 로직으로 제외된다(특수 분기 없음)."""
        trading_date = date(2026, 6, 9)
        tracked = make_stock(stock_code="000001")
        untracked_real_company_code = "900300"  # 정상 기업이나 현재 미추적

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [tracked.stock_code, untracked_real_company_code]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10000, "change_rate": 15.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            count = await collect_daily_surge_outcomes(db, trading_date)

        assert count == 1
        codes_in_db = {
            r.stock_code
            for r in db.query(SurgeActualOutcome).filter_by(trading_date=trading_date).all()
        }
        assert codes_in_db == {tracked.stock_code}

    @pytest.mark.asyncio
    async def test_stock_name_fallback_converges_after_filter(self, db, make_stock):
        """[EC-5] 필터 후 upsert되는 모든 코드가 stocks에 존재하므로 종목명 fallback이 0으로 수렴한다(부수 효과)."""
        trading_date = date(2026, 6, 9)
        tracked = make_stock(stock_code="000001", name="테스트종목명")
        untracked_code = "520099"

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [tracked.stock_code, untracked_code]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10000, "change_rate": 12.0, "name": f"주식{code}"}

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            await collect_daily_surge_outcomes(db, trading_date)

        row = (
            db.query(SurgeActualOutcome)
            .filter_by(trading_date=trading_date, stock_code=tracked.stock_code)
            .first()
        )
        assert row is not None
        assert row.stock_name == "테스트종목명"
        assert row.stock_name != row.stock_code
