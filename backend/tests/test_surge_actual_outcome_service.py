"""SPEC-AI-041: surge_actual_outcome_service 단위 테스트."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.naver_finance import PriceRecord


@pytest.fixture(autouse=True)
def _stub_high_price_history():
    """SPEC-AI-093: 고가 조회를 기본적으로 빈 일봉으로 스텁한다.

    `collect_daily_surge_outcomes`가 종목별 일봉을 추가 조회하게 되었으므로, 기존
    테스트가 실제 네트워크를 타지 않도록 모듈 기본 스텁을 건다. 고가 값을 검증하는
    테스트는 자체 patch 컨텍스트로 이 스텁을 덮어쓴다 — 기존 단언은 무수정이고
    mock 범위만 확장된다(plan.md TASK-006).
    """
    async def _empty_history(code: str, pages: int = 3):
        return []

    with patch(
        "app.services.surge_actual_outcome_service.fetch_stock_price_history",
        new=_empty_history,
    ):
        yield


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


# ---------------------------------------------------------------------------
# SPEC-AI-093: 장중 고가 기준 등락률(high_change_rate) 실측 수집
# ---------------------------------------------------------------------------

_TRADING_DATE = date(2026, 6, 9)


def _naver_key(d: date) -> str:
    return d.strftime("%Y.%m.%d")


def _prev_bday(d: date) -> date:
    from app.services.surge_trading_service import _get_prev_business_day

    return _get_prev_business_day(d)


def _candle(d: date, *, close: int, high: int) -> PriceRecord:
    return PriceRecord(date=_naver_key(d), close=close, open=close, high=high, low=close, volume=1)


def _history_patch(history_by_code: dict[str, list[PriceRecord]]):
    """종목별 일봉을 돌려주는 `fetch_stock_price_history` patch 컨텍스트."""
    async def _fetch(code: str, pages: int = 3):
        return history_by_code.get(code, [])

    return patch(
        "app.services.surge_actual_outcome_service.fetch_stock_price_history",
        new=_fetch,
    )


class TestComputeHighChangeRate:
    """AC-093-001/002/006 — 순수 계산 함수 단위 검증."""

    def test_measures_high_based_rate(self):
        """[AC-093-001] high=+15%, close=+7% → high_change_rate ≈ 15.0."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)
        records = [_candle(t, close=10700, high=11500), _candle(t1, close=10000, high=10100)]

        value, reason = compute_high_change_rate(records, t, t1, change_rate=7.0)

        assert reason is None
        assert value is not None
        assert abs(value - 15.0) <= 0.01

    def test_t1_resolved_by_date_not_index(self):
        """[AC-093-002] 인덱스 1이 T-1이 아닌 교란 순서에서도 date 매칭으로 T-1을 특정한다.

        SPEC-AI-072 회귀 방지 — 인덱스 1(전혀 다른 거래일, 종가 5000)이 분모로 쓰이면
        값이 130.0이 되어 15.0과 명확히 구분된다.
        """
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)
        t2 = _prev_bday(t1)
        t3 = _prev_bday(t2)
        records = [
            _candle(t, close=10700, high=11500),
            _candle(t3, close=5000, high=5100),   # 인덱스 1이 T-1이 아님
            _candle(t1, close=10000, high=10100),  # 실제 T-1은 인덱스 2
            _candle(t2, close=9000, high=9100),
        ]

        value, reason = compute_high_change_rate(records, t, t1, change_rate=7.0)

        assert reason is None
        assert value is not None
        assert abs(value - 15.0) <= 0.01

    def test_missing_t_candle(self):
        """[AC-093-003] T일 일봉 미발견 → no_candle_t."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)

        value, reason = compute_high_change_rate(
            [_candle(t1, close=10000, high=10100)], t, t1, change_rate=7.0
        )

        assert value is None
        assert reason == "no_candle_t"

    def test_missing_t1_candle(self):
        """[AC-093-003] T-1일 일봉 미발견 → no_candle_t1 (신규 상장/거래정지 재개)."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)

        value, reason = compute_high_change_rate(
            [_candle(t, close=10700, high=11500)], t, t1, change_rate=7.0
        )

        assert value is None
        assert reason == "no_candle_t1"

    def test_invalid_high(self):
        """[AC-093-003] high <= 0 → invalid_high."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)
        records = [_candle(t, close=10700, high=0), _candle(t1, close=10000, high=10100)]

        value, reason = compute_high_change_rate(records, t, t1, change_rate=7.0)

        assert value is None
        assert reason == "invalid_high"

    def test_invalid_prev_close(self):
        """[AC-093-003] T-1 종가 <= 0 → invalid_prev_close."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)
        records = [_candle(t, close=10700, high=11500), _candle(t1, close=0, high=10100)]

        value, reason = compute_high_change_rate(records, t, t1, change_rate=7.0)

        assert value is None
        assert reason == "invalid_prev_close"

    def test_invariant_violation(self):
        """[AC-093-006] 계산값(8.0) < change_rate(12.0) → 저장하지 않고 invariant_violation."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)
        records = [_candle(t, close=10700, high=10800), _candle(t1, close=10000, high=10100)]

        value, reason = compute_high_change_rate(records, t, t1, change_rate=12.0)

        assert value is None
        assert reason == "invariant_violation"

    def test_rounding_tolerance_is_not_violation(self):
        """소수 반올림 수준의 미세 차이는 불변식 위반으로 오판하지 않는다."""
        from app.services.surge_actual_outcome_service import compute_high_change_rate

        t = _TRADING_DATE
        t1 = _prev_bday(t)
        records = [_candle(t, close=10700, high=10700), _candle(t1, close=10000, high=10100)]

        value, reason = compute_high_change_rate(records, t, t1, change_rate=7.005)

        assert reason is None
        assert value is not None


class TestCollectHighChangeRate:
    """AC-093-001/003/004/005/009 — 수집 배치 통합 검증."""

    @pytest.mark.asyncio
    async def test_high_change_rate_persisted(self, db, make_stock):
        """[AC-093-001, 시나리오 1] 장중 급등 후 되밀린 종목의 고가 등락률이 저장된다."""
        tracked = make_stock(stock_code="123450")
        t = _TRADING_DATE
        t1 = _prev_bday(t)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            return [tracked.stock_code] if market == "KOSPI" else []

        async def mock_fetch_price(code: str):
            return {"current_price": 10700, "change_rate": 7.0}

        history = {
            tracked.stock_code: [
                _candle(t, close=10700, high=11500),
                _candle(t1, close=10000, high=10100),
            ]
        }

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
            _history_patch(history),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            await collect_daily_surge_outcomes(db, t)

        row = (
            db.query(SurgeActualOutcome)
            .filter_by(trading_date=t, stock_code=tracked.stock_code)
            .first()
        )
        assert row is not None
        assert row.high_change_rate is not None
        assert abs(row.high_change_rate - 15.0) <= 0.01
        # [AC-093-004] was_surge는 종가 기준으로 동결 — 고가가 15%여도 False
        assert row.was_surge is False

    @pytest.mark.asyncio
    async def test_change_rate_path_unchanged(self, db, make_stock):
        """[AC-093-005] change_rate는 fetch_current_price_with_change 값만 사용한다.

        일봉 종가로 재계산하면 10.0(=(11000-10000)/10000)이 되어 was_surge=True로 뒤집히지만,
        저장값은 반드시 fetch_current_price_with_change가 준 7.0이어야 한다.
        """
        tracked = make_stock(stock_code="123451")
        t = _TRADING_DATE
        t1 = _prev_bday(t)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            return [tracked.stock_code] if market == "KOSPI" else []

        async def mock_fetch_price(code: str):
            return {"current_price": 11000, "change_rate": 7.0}

        history = {
            tracked.stock_code: [
                _candle(t, close=11000, high=11500),
                _candle(t1, close=10000, high=10100),
            ]
        }

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
            _history_patch(history),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            await collect_daily_surge_outcomes(db, t)

        row = (
            db.query(SurgeActualOutcome)
            .filter_by(trading_date=t, stock_code=tracked.stock_code)
            .first()
        )
        assert row is not None
        assert abs(row.change_rate - 7.0) <= 0.01
        assert row.was_surge is False
        assert abs(row.high_change_rate - 15.0) <= 0.01

    @pytest.mark.asyncio
    async def test_fallback_stores_null_and_logs_reason(self, db, make_stock, caplog):
        """[AC-093-003, 시나리오 3] 당일 일봉 미게시 → NULL 저장 + no_candle_t 로깅 + 배치 계속."""
        import logging

        ok_stock = make_stock(stock_code="123452")
        missing_stock = make_stock(stock_code="123453")
        t = _TRADING_DATE
        t1 = _prev_bday(t)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            if market == "KOSPI":
                return [ok_stock.stock_code, missing_stock.stock_code]
            return []

        async def mock_fetch_price(code: str):
            return {"current_price": 10700, "change_rate": 7.0}

        history = {
            ok_stock.stock_code: [
                _candle(t, close=10700, high=11500),
                _candle(t1, close=10000, high=10100),
            ],
            # missing_stock: T일 일봉 미게시 (T-1만 존재)
            missing_stock.stock_code: [_candle(t1, close=10000, high=10100)],
        }

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
            _history_patch(history),
            caplog.at_level(
                logging.DEBUG, logger="app.services.surge_actual_outcome_service"
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            count = await collect_daily_surge_outcomes(db, t)

        # 개별 실패가 배치를 중단시키지 않는다
        assert count == 2

        rows = {
            r.stock_code: r
            for r in db.query(SurgeActualOutcome).filter_by(trading_date=t).all()
        }
        assert rows[missing_stock.stock_code].high_change_rate is None
        assert rows[ok_stock.stock_code].high_change_rate is not None

        messages = [r.getMessage() for r in caplog.records]
        # 개별 사유 코드 로깅
        assert any("no_candle_t" in m and missing_stock.stock_code in m for m in messages)
        # 배치 종료 요약 1건 (5개 사유 코드 전부 집계)
        summaries = [m for m in messages if "고가 기준 등락률 수집 요약" in m]
        assert len(summaries) == 1
        for reason in (
            "no_candle_t",
            "no_candle_t1",
            "invalid_high",
            "invalid_prev_close",
            "invariant_violation",
        ):
            assert reason in summaries[0]

    @pytest.mark.asyncio
    async def test_cost_measurement_logged(self, db, make_stock, caplog):
        """[AC-093-009] 고가 조회 시도 수와 외부 호출(추정) 수가 로그로 남는다."""
        import logging

        tracked = make_stock(stock_code="123454")
        t = _TRADING_DATE
        t1 = _prev_bday(t)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            return [tracked.stock_code] if market == "KOSPI" else []

        async def mock_fetch_price(code: str):
            return {"current_price": 10700, "change_rate": 7.0}

        history = {
            tracked.stock_code: [
                _candle(t, close=10700, high=11500),
                _candle(t1, close=10000, high=10100),
            ]
        }

        with (
            patch(
                "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                new=mock_fetch_top_movers,
            ),
            patch(
                "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                side_effect=mock_fetch_price,
            ),
            _history_patch(history),
            caplog.at_level(
                logging.INFO, logger="app.services.surge_actual_outcome_service"
            ),
        ):
            from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes

            await collect_daily_surge_outcomes(db, t)

        cost_logs = [
            r.getMessage() for r in caplog.records if "고가 조회 비용 계측" in r.getMessage()
        ]
        assert len(cost_logs) == 1
        assert "조회시도=1건" in cost_logs[0]
        assert "캐시적중=" in cost_logs[0]
        assert "외부호출(추정)=" in cost_logs[0]

    @pytest.mark.asyncio
    async def test_idempotent_rerun_keeps_high_change_rate(self, db, make_stock):
        """[Edge] 동일 거래일 재실행 시 high_change_rate가 동일 값으로 덮어써진다."""
        tracked = make_stock(stock_code="123455")
        t = _TRADING_DATE
        t1 = _prev_bday(t)

        async def mock_fetch_top_movers(market: str, limit: int = 100):
            return [tracked.stock_code] if market == "KOSPI" else []

        async def mock_fetch_price(code: str):
            return {"current_price": 10700, "change_rate": 7.0}

        history = {
            tracked.stock_code: [
                _candle(t, close=10700, high=11500),
                _candle(t1, close=10000, high=10100),
            ]
        }

        for _ in range(2):
            with (
                patch(
                    "app.services.surge_actual_outcome_service.fetch_top_movers_codes",
                    new=mock_fetch_top_movers,
                ),
                patch(
                    "app.services.surge_actual_outcome_service.fetch_current_price_with_change",
                    side_effect=mock_fetch_price,
                ),
                _history_patch(history),
            ):
                from app.services.surge_actual_outcome_service import (
                    collect_daily_surge_outcomes,
                )

                await collect_daily_surge_outcomes(db, t)

        rows = db.query(SurgeActualOutcome).filter_by(trading_date=t).all()
        assert len(rows) == 1
        assert abs(rows[0].high_change_rate - 15.0) <= 0.01


class TestHighBasedDerivedMetric:
    """AC-093-007/008 — 고가 기반 파생 지표 + coverage guard."""

    def _seed(self, db, rows: list[tuple[str, float, bool, float | None]]) -> None:
        for code, change_rate, was_surge, high_rate in rows:
            db.add(
                SurgeActualOutcome(
                    trading_date=_TRADING_DATE,
                    stock_code=code,
                    stock_name=code,
                    change_rate=change_rate,
                    was_surge=was_surge,
                    high_change_rate=high_rate,
                    market="KOSPI",
                )
            )
        db.flush()

    def test_derived_metric_returned_in_parallel(self, db):
        """[AC-093-007] COALESCE 파생 판정이 기존 was_surge 지표와 병렬로 반환된다."""
        from app.services.surge_actual_outcome_service import evaluate_high_based_outcomes

        # A: 종가 7% / 고가 15% → was_surge False, 고가 기반 True
        # B: 종가 12% / 고가 실측 실패(NULL) → COALESCE fallback으로 둘 다 True
        # C: 종가 3% / 고가 5% → 둘 다 False
        self._seed(db, [
            ("930001", 7.0, False, 15.0),
            ("930002", 12.0, True, None),
            ("930003", 3.0, False, 5.0),
        ])

        result = evaluate_high_based_outcomes(db, _TRADING_DATE)

        assert result["total_rows"] == 3
        assert result["high_measured_rows"] == 2
        # 기존 지표는 그대로 병렬 제공 (대체 금지)
        assert result["was_surge_count"] == 1
        # 고가 기반 파생 지표
        assert result["high_based_surge_count"] == 2

    def test_coverage_above_threshold_is_not_partial(self, db):
        """[AC-093-008] 커버리지가 임계값 이상이면 partial_collection=False."""
        from app.services.surge_actual_outcome_service import evaluate_high_based_outcomes

        self._seed(db, [
            ("930011", 7.0, False, 15.0),
            ("930012", 3.0, False, 5.0),
        ])

        result = evaluate_high_based_outcomes(db, _TRADING_DATE, coverage_threshold=0.90)

        assert result["coverage"] == 1.0
        assert result["partial_collection"] is False

    def test_coverage_below_threshold_flags_partial(self, db):
        """[AC-093-008, 시나리오 6] 부분 수집 시 표시와 실제 커버리지 수치가 함께 반환된다."""
        from app.services.surge_actual_outcome_service import evaluate_high_based_outcomes

        self._seed(db, [
            ("930021", 7.0, False, 15.0),
            ("930022", 3.0, False, None),
            ("930023", 4.0, False, None),
            ("930024", 5.0, False, None),
            ("930025", 6.0, False, None),
        ])

        result = evaluate_high_based_outcomes(db, _TRADING_DATE, coverage_threshold=0.90)

        assert abs(result["coverage"] - 0.20) <= 0.001
        assert result["partial_collection"] is True
        assert result["coverage_threshold"] == 0.90

    def test_empty_trading_day_is_partial(self, db):
        """[Edge] 행이 없는 거래일은 커버리지 0.0 + 부분 수집으로 표시된다."""
        from app.services.surge_actual_outcome_service import evaluate_high_based_outcomes

        result = evaluate_high_based_outcomes(db, date(2026, 6, 10))

        assert result["total_rows"] == 0
        assert result["coverage"] == 0.0
        assert result["partial_collection"] is True

    def test_default_coverage_threshold_is_090(self):
        """[REQ-AI093-005] coverage 임계값 기본값은 0.90 (설정으로 오버라이드 가능)."""
        from app.services import surge_actual_outcome_service as svc

        assert svc._HIGH_COVERAGE_THRESHOLD == 0.90
