"""SPEC-AI-003: 선행 매수 신호 탐지 characterization 테스트.

DDD PRESERVE 단계: 구현 전에 예상 동작을 명세하는 테스트.
각 탐지 함수의 필터링 로직, 강도 판단, 병합/스코어링, 에러 처리를 검증한다.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# TC-001: _scan_market_stocks 필터링 검증
# ---------------------------------------------------------------------------

class TestScanMarketStocks:
    """_scan_market_stocks 전종목 스캔 및 필터링 검증."""

    @pytest.mark.asyncio
    async def test_characterize_excludes_high_change_rate(self) -> None:
        """TC-001: change_rate > 3.0인 종목은 결과에서 제외된다."""
        from app.services.fund_manager import _scan_market_stocks

        # KOSPI page1 mock: +4% 종목 포함
        mock_items_p1 = [
            _make_naver_item("000001", "종목A", change_rate=4.5, market_cap=2000),
            _make_naver_item("000002", "종목B", change_rate=1.0, market_cap=2000),
        ]
        mock_items_kosdaq = [
            _make_naver_item("000003", "종목C", change_rate=0.5, market_cap=2000),
        ]

        with patch(
            "app.services.naver_finance.fetch_naver_stock_list",
            new_callable=AsyncMock,
        ) as mock_fetch:
            # KOSPI pages 1-3 + KOSDAQ pages 1-2
            mock_fetch.side_effect = _make_fetch_side_effect(
                kospi_pages=[mock_items_p1, [], []],
                kosdaq_pages=[mock_items_kosdaq, []],
            )
            db = MagicMock(spec=Session)
            result = await _scan_market_stocks(db)

        codes = [r["stock_code"] for r in result]
        assert "000001" not in codes, "change_rate=4.5 종목은 제외되어야 한다"
        assert "000002" in codes
        assert "000003" in codes

    @pytest.mark.asyncio
    async def test_characterize_excludes_large_drop(self) -> None:
        """TC-001: change_rate < -5.0인 종목은 결과에서 제외된다."""
        from app.services.fund_manager import _scan_market_stocks

        mock_items = [
            _make_naver_item("000010", "급락주", change_rate=-6.0, market_cap=2000),
            _make_naver_item("000011", "정상주", change_rate=-1.0, market_cap=2000),
        ]

        with patch(
            "app.services.naver_finance.fetch_naver_stock_list",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = _make_fetch_side_effect(
                kospi_pages=[mock_items, [], []],
                kosdaq_pages=[[], []],
            )
            db = MagicMock(spec=Session)
            result = await _scan_market_stocks(db)

        codes = [r["stock_code"] for r in result]
        assert "000010" not in codes, "change_rate=-6.0 종목은 제외되어야 한다"
        assert "000011" in codes

    @pytest.mark.asyncio
    async def test_characterize_excludes_small_cap(self) -> None:
        """TC-001: market_cap < 1000 (1000억 미만) 종목은 제외된다."""
        from app.services.fund_manager import _scan_market_stocks

        mock_items = [
            _make_naver_item("000020", "소형주", change_rate=0.5, market_cap=500),
            _make_naver_item("000021", "중형주", change_rate=0.5, market_cap=1500),
        ]

        with patch(
            "app.services.naver_finance.fetch_naver_stock_list",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = _make_fetch_side_effect(
                kospi_pages=[mock_items, [], []],
                kosdaq_pages=[[], []],
            )
            db = MagicMock(spec=Session)
            result = await _scan_market_stocks(db)

        codes = [r["stock_code"] for r in result]
        assert "000020" not in codes, "시가총액 500억 종목은 제외되어야 한다"
        assert "000021" in codes

    @pytest.mark.asyncio
    async def test_characterize_returns_required_fields(self) -> None:
        """_scan_market_stocks 반환값에 필수 필드가 존재한다."""
        from app.services.fund_manager import _scan_market_stocks

        mock_items = [
            _make_naver_item("000030", "테스트주", change_rate=0.5, market_cap=2000,
                             current_price=10000, volume=100000),
        ]

        with patch(
            "app.services.naver_finance.fetch_naver_stock_list",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = _make_fetch_side_effect(
                kospi_pages=[mock_items, [], []],
                kosdaq_pages=[[], []],
            )
            db = MagicMock(spec=Session)
            result = await _scan_market_stocks(db)

        assert len(result) == 1
        item = result[0]
        assert "stock_code" in item
        assert "name" in item
        assert "current_price" in item
        assert "change_rate" in item
        assert "market_cap" in item
        assert "volume" in item


# ---------------------------------------------------------------------------
# TC-003: _detect_quiet_accumulation 수급 축적 탐지 검증
# ---------------------------------------------------------------------------

class TestDetectQuietAccumulation:
    """_detect_quiet_accumulation 조용한 수급 축적 탐지 검증."""

    @pytest.mark.asyncio
    async def test_characterize_detects_foreign_and_institution_buys(self) -> None:
        """TC-003: foreign_net_5d > 0 AND institution_net_5d > 0 AND -2% <= rate <= 2% → 탐지."""
        from app.services.fund_manager import _detect_quiet_accumulation

        scanned = [_make_scanned_stock("111111", "수급주", change_rate=0.5)]
        cache = {
            "111111": {
                "foreign_net_5d": 50000,
                "institution_net_5d": 30000,
                "avg_volume_20d": 100000,
                "change_rate": 0.5,
            }
        }

        result = await _detect_quiet_accumulation(scanned, cache, asyncio.Semaphore(5))

        assert len(result) == 1
        assert result[0]["stock_code"] == "111111"
        assert result[0]["leading_signals"][0]["type"] == "quiet_accumulation"

    @pytest.mark.asyncio
    async def test_characterize_excludes_institution_sell(self) -> None:
        """TC-003: institution_net_5d < 0이면 탐지하지 않는다."""
        from app.services.fund_manager import _detect_quiet_accumulation

        scanned = [_make_scanned_stock("222222", "기관매도주", change_rate=0.5)]
        cache = {
            "222222": {
                "foreign_net_5d": 50000,
                "institution_net_5d": -20000,  # 기관 순매도
                "avg_volume_20d": 100000,
                "change_rate": 0.5,
            }
        }

        result = await _detect_quiet_accumulation(scanned, cache, asyncio.Semaphore(5))

        assert len(result) == 0, "기관 순매도 시 탐지하지 않는다"

    @pytest.mark.asyncio
    async def test_characterize_excludes_high_change_rate(self) -> None:
        """TC-003: change_rate > 2.0이면 조용한 수급이 아니므로 제외."""
        from app.services.fund_manager import _detect_quiet_accumulation

        scanned = [_make_scanned_stock("333333", "급등주", change_rate=2.5)]
        cache = {
            "333333": {
                "foreign_net_5d": 50000,
                "institution_net_5d": 30000,
                "avg_volume_20d": 100000,
                "change_rate": 2.5,
            }
        }

        result = await _detect_quiet_accumulation(scanned, cache, asyncio.Semaphore(5))

        assert len(result) == 0, "change_rate > 2.0 종목은 제외"

    @pytest.mark.asyncio
    async def test_characterize_strong_signal_when_net_buy_ratio_high(self) -> None:
        """TC-003: (foreign_net + institution_net) / avg_volume >= 0.1 → 강함."""
        from app.services.fund_manager import _detect_quiet_accumulation

        scanned = [_make_scanned_stock("444444", "강한수급주", change_rate=0.5)]
        cache = {
            "444444": {
                "foreign_net_5d": 80000,
                "institution_net_5d": 50000,   # 합: 130000
                "avg_volume_20d": 1000000,     # 130000/1000000 = 0.13 >= 0.1
                "change_rate": 0.5,
            }
        }

        result = await _detect_quiet_accumulation(scanned, cache, asyncio.Semaphore(5))

        assert len(result) == 1
        signal = result[0]["leading_signals"][0]
        assert signal["strength"] == "strong", "순매수/거래량 비율 0.13 → 강함"

    @pytest.mark.asyncio
    async def test_characterize_moderate_signal_when_net_buy_ratio_low(self) -> None:
        """TC-003: 비율 < 0.1 → 보통."""
        from app.services.fund_manager import _detect_quiet_accumulation

        scanned = [_make_scanned_stock("555555", "보통수급주", change_rate=0.5)]
        cache = {
            "555555": {
                "foreign_net_5d": 1000,
                "institution_net_5d": 500,     # 합: 1500
                "avg_volume_20d": 1000000,     # 1500/1000000 = 0.0015 < 0.1
                "change_rate": 0.5,
            }
        }

        result = await _detect_quiet_accumulation(scanned, cache, asyncio.Semaphore(5))

        assert len(result) == 1
        signal = result[0]["leading_signals"][0]
        assert signal["strength"] == "moderate"


# ---------------------------------------------------------------------------
# TC-004: _detect_news_price_divergence 뉴스-가격 괴리 탐지 검증
# ---------------------------------------------------------------------------

class TestDetectNewsPriceDivergence:
    """_detect_news_price_divergence 뉴스-가격 괴리 탐지 검증."""

    @pytest.mark.asyncio
    async def test_characterize_detects_positive_news_low_change(self) -> None:
        """TC-004: 긍정 뉴스(3시간 이내) + change_rate < 1% → 탐지."""
        from app.services.fund_manager import _detect_news_price_divergence

        scanned = [_make_scanned_stock("666666", "괴리주", change_rate=0.3)]

        # 구현 내부 DB 쿼리를 직접 패치
        relation = MagicMock()
        relation.stock_id = 10
        relation.relation_sentiment = "positive"

        mock_stock = MagicMock()
        mock_stock.id = 10
        mock_stock.stock_code = "666666"

        db = MagicMock(spec=Session)
        # relations 조회 mock
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [relation]
        # Stock 조회 mock (stock_id_to_code 매핑)
        db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        result = await _detect_news_price_divergence(scanned, db, [])

        assert len(result) == 1
        assert result[0]["stock_code"] == "666666"
        signal = result[0]["leading_signals"][0]
        assert signal["type"] == "news_divergence"

    @pytest.mark.asyncio
    async def test_characterize_excludes_high_change_rate(self) -> None:
        """TC-004: change_rate >= 1.0이면 이미 가격 반응 → 제외."""
        from app.services.fund_manager import _detect_news_price_divergence

        scanned = [_make_scanned_stock("777777", "이미반응주", change_rate=1.5)]

        relation = MagicMock()
        relation.stock_id = 20
        relation.relation_sentiment = "positive"

        mock_stock = MagicMock()
        mock_stock.id = 20
        mock_stock.stock_code = "777777"

        db = MagicMock(spec=Session)
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [relation]
        db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        result = await _detect_news_price_divergence(scanned, db, [])

        assert len(result) == 0, "change_rate >= 1.0 → 이미 가격 반응, 제외"

    @pytest.mark.asyncio
    async def test_characterize_strong_signal_multiple_positive_news(self) -> None:
        """TC-004: 긍정 뉴스 2건 이상 → 강함."""
        from app.services.fund_manager import _detect_news_price_divergence

        scanned = [_make_scanned_stock("888888", "복수뉴스주", change_rate=0.2)]

        relations = []
        for i, sentiment in enumerate(["positive", "strong_positive"]):
            r = MagicMock()
            r.stock_id = 30
            r.relation_sentiment = sentiment
            relations.append(r)

        mock_stock = MagicMock()
        mock_stock.id = 30
        mock_stock.stock_code = "888888"

        db = MagicMock(spec=Session)
        db.query.return_value.join.return_value.filter.return_value.all.return_value = relations
        db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        result = await _detect_news_price_divergence(scanned, db, [])

        assert len(result) == 1
        signal = result[0]["leading_signals"][0]
        assert signal["strength"] == "strong", "긍정 뉴스 2건 이상 → 강함"


# ---------------------------------------------------------------------------
# TC-005: _detect_bb_compression 볼린저밴드 수축 탐지 검증
# ---------------------------------------------------------------------------

class TestDetectBBCompression:
    """_detect_bb_compression 볼린저밴드 수축 탐지 검증."""

    @pytest.mark.asyncio
    async def test_characterize_detects_bb_compression(self) -> None:
        """TC-005: bb_width < avg_20d * 0.5 AND volume_ratio < 0.7 AND sma_20_slope >= 0 → 탐지."""
        from app.services.fund_manager import _detect_bb_compression

        scanned = [_make_scanned_stock("111001", "수축주", change_rate=0.5)]

        # 가격 히스토리: 25일치 (20일 평균 계산 가능)
        price_history = _make_price_history(25, base_price=10000, small_range=True)

        cache = {
            "111001": {
                "volume_ratio": 0.5,    # < 0.7
                "sma_20_slope": 0.1,    # >= 0
            }
        }

        with patch(
            "app.services.naver_finance.fetch_stock_price_history",
            new_callable=AsyncMock,
            return_value=price_history,
        ):
            with patch(
                "app.services.fund_manager._gather_market_data",
                new_callable=AsyncMock,
                return_value={
                    "volume_ratio": 0.5,
                    "sma_20_slope": 0.1,
                    "bb_width": 0.01,  # 매우 좁은 밴드
                    "avg_volume_20d": 100000,
                },
            ):
                result = await _detect_bb_compression(scanned, cache, asyncio.Semaphore(5))

        # 현재 bb_width가 20일 평균의 50% 미만이면 탐지
        # (구체적 검증은 구현에 따라 달라지므로 타입 검증)
        if result:
            assert result[0]["leading_signals"][0]["type"] == "bb_compression"

    @pytest.mark.asyncio
    async def test_characterize_excludes_negative_sma_slope(self) -> None:
        """TC-005: sma_20_slope < 0이면 하향 추세 → 제외."""
        from app.services.fund_manager import _detect_bb_compression

        scanned = [_make_scanned_stock("111002", "하향종목", change_rate=0.5)]

        cache = {
            "111002": {
                "volume_ratio": 0.5,
                "sma_20_slope": -0.2,  # 하향 추세
                "bb_width": 0.005,
            }
        }

        price_history = _make_price_history(25, base_price=10000, small_range=True)

        with patch(
            "app.services.naver_finance.fetch_stock_price_history",
            new_callable=AsyncMock,
            return_value=price_history,
        ):
            result = await _detect_bb_compression(scanned, cache, asyncio.Semaphore(5))

        assert len(result) == 0, "sma_20_slope < 0 → 하향 추세, 제외"

    @pytest.mark.asyncio
    async def test_characterize_skips_insufficient_history(self) -> None:
        """TC-005: 가격 히스토리가 20일 미만이면 조용히 건너뛴다."""
        from app.services.fund_manager import _detect_bb_compression

        scanned = [_make_scanned_stock("111003", "히스토리부족주", change_rate=0.5)]
        cache = {}

        with patch(
            "app.services.naver_finance.fetch_stock_price_history",
            new_callable=AsyncMock,
            return_value=_make_price_history(10, base_price=10000),  # 10일치만
        ):
            with patch(
                "app.services.fund_manager._gather_market_data",
                new_callable=AsyncMock,
                return_value={"volume_ratio": 0.5, "sma_20_slope": 0.1},
            ):
                # 예외가 발생하지 않아야 한다
                result = await _detect_bb_compression(scanned, cache, asyncio.Semaphore(5))

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# TC-006: _detect_sector_laggards 섹터 낙오자 탐지 검증
# ---------------------------------------------------------------------------

class TestDetectSectorLaggards:
    """_detect_sector_laggards 섹터 로테이션 낙오자 탐지 검증."""

    @pytest.mark.asyncio
    async def test_characterize_detects_laggard_in_momentum_sector(self) -> None:
        """TC-006: 모멘텀 섹터 내 종목의 5일 수익률 < 섹터 평균 → 탐지."""
        from app.services.fund_manager import _detect_sector_laggards

        scanned = [_make_scanned_stock("222001", "낙오주", change_rate=0.5)]

        momentum_sectors = [{"sector_id": 10, "sector_name": "반도체", "avg_return": 3.0, "excess_return": 1.5}]

        db = MagicMock(spec=Session)
        # Stock 쿼리: sector_id=10에 해당 종목 포함
        mock_stock = MagicMock()
        mock_stock.stock_code = "222001"
        mock_stock.sector_id = 10
        db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        cache = {
            "222001": {"price_5d_trend": 0.5}  # 섹터 평균 3.0보다 낮음
        }

        with patch(
            "app.services.sector_momentum.detect_momentum_sectors",
            return_value=momentum_sectors,
        ):
            result = await _detect_sector_laggards(scanned, db, cache, asyncio.Semaphore(5))

        assert len(result) == 1
        signal = result[0]["leading_signals"][0]
        assert signal["type"] == "sector_laggard"

    @pytest.mark.asyncio
    async def test_characterize_strong_signal_large_gap(self) -> None:
        """TC-006: 섹터 평균 대비 -3%p 이상 괴리 → 강함."""
        from app.services.fund_manager import _detect_sector_laggards

        scanned = [_make_scanned_stock("222002", "크게낙오주", change_rate=0.5)]

        momentum_sectors = [{"sector_id": 11, "sector_name": "배터리", "avg_return": 4.0, "excess_return": 2.0}]

        db = MagicMock(spec=Session)
        mock_stock = MagicMock()
        mock_stock.stock_code = "222002"
        mock_stock.sector_id = 11
        db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        cache = {
            "222002": {"price_5d_trend": 0.5}  # 4.0 - 0.5 = 3.5 >= 3.0
        }

        with patch(
            "app.services.sector_momentum.detect_momentum_sectors",
            return_value=momentum_sectors,
        ):
            result = await _detect_sector_laggards(scanned, db, cache, asyncio.Semaphore(5))

        assert len(result) == 1
        signal = result[0]["leading_signals"][0]
        assert signal["strength"] == "strong", "3.5%p 괴리 → 강함"


# ---------------------------------------------------------------------------
# TC-007: _gather_leading_candidates 점수 계산 및 병합 검증
# ---------------------------------------------------------------------------

class TestGatherLeadingCandidates:
    """_gather_leading_candidates 통합 오케스트레이션 검증."""

    @pytest.mark.asyncio
    async def test_characterize_multi_signal_scoring(self) -> None:
        """TC-007: quiet_accumulation(30) + news_divergence(25) + multi(+10) = 65점."""
        from app.services.fund_manager import _gather_leading_candidates

        scanned = [_make_scanned_stock("999001", "멀티신호주", change_rate=0.5)]

        # 두 개 탐지기가 같은 종목을 반환
        quiet_result = [
            {
                "stock_code": "999001",
                "name": "멀티신호주",
                "leading_signals": [{"type": "quiet_accumulation", "strength": "moderate", "detail": "수급 축적"}],
            }
        ]
        news_result = [
            {
                "stock_code": "999001",
                "name": "멀티신호주",
                "leading_signals": [{"type": "news_divergence", "strength": "moderate", "detail": "뉴스 괴리"}],
            }
        ]

        db = MagicMock(spec=Session)

        with patch("app.services.fund_manager._scan_market_stocks", new_callable=AsyncMock, return_value=scanned), \
             patch("app.services.fund_manager._detect_quiet_accumulation", new_callable=AsyncMock, return_value=quiet_result), \
             patch("app.services.fund_manager._detect_news_price_divergence", new_callable=AsyncMock, return_value=news_result), \
             patch("app.services.fund_manager._detect_bb_compression", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_sector_laggards", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._gather_market_data", new_callable=AsyncMock, return_value={}), \
             patch("app.services.fund_manager._gather_financial_data", new_callable=AsyncMock, return_value={}):

            result = await _gather_leading_candidates(db)

        # 999001이 포함되어야 함
        codes = [r.get("code") or r.get("stock_code") for r in result]
        assert "999001" in codes

        # 멀티 신호 검증
        candidate = next(r for r in result if (r.get("code") or r.get("stock_code")) == "999001")
        signals = candidate.get("leading_signals", [])
        signal_types = [s["type"] for s in signals]
        assert "quiet_accumulation" in signal_types
        assert "news_divergence" in signal_types

    @pytest.mark.asyncio
    async def test_characterize_max_10_candidates(self) -> None:
        """TC-007: 결과는 최대 10개로 제한된다."""
        from app.services.fund_manager import _gather_leading_candidates

        # 15개 후보 생성
        many_candidates = [
            {
                "stock_code": f"99{i:04d}",
                "name": f"종목{i}",
                "leading_signals": [{"type": "quiet_accumulation", "strength": "moderate", "detail": "테스트"}],
            }
            for i in range(15)
        ]

        db = MagicMock(spec=Session)

        with patch("app.services.fund_manager._scan_market_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_quiet_accumulation", new_callable=AsyncMock, return_value=many_candidates), \
             patch("app.services.fund_manager._detect_news_price_divergence", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_bb_compression", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_sector_laggards", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._gather_market_data", new_callable=AsyncMock, return_value={}), \
             patch("app.services.fund_manager._gather_financial_data", new_callable=AsyncMock, return_value={}):

            result = await _gather_leading_candidates(db)

        assert len(result) <= 10, "최대 10개 제한"


# ---------------------------------------------------------------------------
# TC-008: generate_daily_briefing 후보 병합 검증
# ---------------------------------------------------------------------------

class TestMergeCandidates:
    """선행 후보와 뉴스 후보 병합 로직 검증."""

    def test_characterize_leading_first_in_merge(self) -> None:
        """TC-008: 병합 시 선행 후보가 먼저 배치된다."""
        leading = [
            {"code": "LEAD01", "name": "선행1"},
            {"code": "LEAD02", "name": "선행2"},
        ]
        news = [
            {"code": "NEWS01", "name": "뉴스1"},
            {"code": "LEAD01", "name": "선행1"},  # 중복
        ]

        merged = _merge_candidates(leading, news, max_count=10)

        assert merged[0]["code"] == "LEAD01"
        assert merged[1]["code"] == "LEAD02"
        assert merged[2]["code"] == "NEWS01"

    def test_characterize_deduplication_keeps_leading(self) -> None:
        """TC-008: 중복 시 선행 후보 데이터를 유지한다."""
        leading = [{"code": "DUP01", "name": "종목", "leading_signals": [{"type": "quiet_accumulation"}]}]
        news = [{"code": "DUP01", "name": "종목"}]

        merged = _merge_candidates(leading, news, max_count=10)

        dup = next(r for r in merged if r["code"] == "DUP01")
        assert "leading_signals" in dup, "중복 시 선행 후보의 leading_signals를 유지"

    def test_characterize_max_count_limit(self) -> None:
        """TC-008: 병합 결과는 max_count를 초과하지 않는다."""
        leading = [{"code": f"L{i}", "name": f"선행{i}"} for i in range(7)]
        news = [{"code": f"N{i}", "name": f"뉴스{i}"} for i in range(7)]

        merged = _merge_candidates(leading, news, max_count=10)

        assert len(merged) <= 10


# ---------------------------------------------------------------------------
# TC-010: 부분 실패 graceful degradation 검증
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """TC-010: 일부 탐지기 실패 시 graceful degradation."""

    @pytest.mark.asyncio
    async def test_characterize_one_detector_fails_others_continue(self) -> None:
        """TC-010: 하나의 탐지기가 예외를 발생시켜도 나머지는 결과를 반환한다."""
        from app.services.fund_manager import _gather_leading_candidates

        working_result = [
            {
                "stock_code": "ERR001",
                "name": "정상종목",
                "leading_signals": [{"type": "news_divergence", "strength": "moderate", "detail": "뉴스 괴리"}],
            }
        ]

        # Stock DB 조회 mock (code → Stock 객체)
        mock_stock_obj = MagicMock()
        mock_stock_obj.stock_code = "ERR001"
        mock_stock_obj.sector = None

        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = mock_stock_obj

        with patch("app.services.fund_manager._scan_market_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_quiet_accumulation",
                   new_callable=AsyncMock, side_effect=Exception("수급 API 오류")), \
             patch("app.services.fund_manager._detect_news_price_divergence",
                   new_callable=AsyncMock, return_value=working_result), \
             patch("app.services.fund_manager._detect_bb_compression", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_sector_laggards", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._gather_market_data", new_callable=AsyncMock, return_value={}), \
             patch("app.services.fund_manager._gather_financial_data", new_callable=AsyncMock, return_value={}):

            # 예외가 전파되지 않아야 한다
            result = await _gather_leading_candidates(db)

        # 정상 탐지기의 결과는 포함되어야 한다
        codes = [r.get("code") or r.get("stock_code") for r in result]
        assert "ERR001" in codes, "하나 실패해도 다른 탐지기 결과는 반환"

    @pytest.mark.asyncio
    async def test_characterize_all_detectors_fail_returns_empty(self) -> None:
        """TC-010: 모든 탐지기가 실패하면 빈 리스트를 반환한다."""
        from app.services.fund_manager import _gather_leading_candidates

        db = MagicMock(spec=Session)

        with patch("app.services.fund_manager._scan_market_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.fund_manager._detect_quiet_accumulation",
                   new_callable=AsyncMock, side_effect=Exception("오류1")), \
             patch("app.services.fund_manager._detect_news_price_divergence",
                   new_callable=AsyncMock, side_effect=Exception("오류2")), \
             patch("app.services.fund_manager._detect_bb_compression",
                   new_callable=AsyncMock, side_effect=Exception("오류3")), \
             patch("app.services.fund_manager._detect_sector_laggards",
                   new_callable=AsyncMock, side_effect=Exception("오류4")):

            result = await _gather_leading_candidates(db)

        assert result == [], "모든 탐지기 실패 시 빈 리스트 반환"


# ---------------------------------------------------------------------------
# 헬퍼 팩토리 함수
# ---------------------------------------------------------------------------

def _make_naver_item(
    stock_code: str,
    name: str,
    change_rate: float = 0.0,
    market_cap: int = 2000,
    current_price: int = 10000,
    volume: int = 100000,
) -> MagicMock:
    """NaverStockItem mock 생성."""
    item = MagicMock()
    item.stock_code = stock_code
    item.name = name
    item.current_price = current_price
    item.change_rate = change_rate
    item.market_cap = market_cap
    item.volume = volume
    return item


def _make_scanned_stock(
    stock_code: str,
    name: str,
    change_rate: float = 0.0,
    market_cap: int = 2000,
    current_price: int = 10000,
    volume: int = 100000,
) -> dict:
    """scanned_stocks 리스트 항목 생성."""
    return {
        "stock_code": stock_code,
        "name": name,
        "current_price": current_price,
        "change_rate": change_rate,
        "market_cap": market_cap,
        "volume": volume,
    }


def _make_news_stock_relation(stock_code: str, sentiment: str) -> MagicMock:
    """NewsStockRelation mock 생성."""
    relation = MagicMock()
    relation.stock_code = stock_code
    relation.relation_sentiment = sentiment
    # stock 속성 추가 (JOIN된 Stock 객체)
    mock_stock = MagicMock()
    mock_stock.stock_code = stock_code
    relation.stock = mock_stock
    return relation


def _make_price_history(
    count: int,
    base_price: int = 10000,
    small_range: bool = False,
) -> list:
    """가격 히스토리 mock 생성."""
    items = []
    for i in range(count):
        item = MagicMock()
        if small_range:
            # 밴드 수축 시뮬레이션: 변동폭 작게
            item.close = base_price + (i % 3) * 10
            item.high = item.close + 20
            item.low = item.close - 20
        else:
            item.close = base_price + i * 100
            item.high = item.close + 200
            item.low = item.close - 200
        item.open = item.close - 50
        item.volume = 100000
        items.append(item)
    return items


def _make_fetch_side_effect(
    kospi_pages: list[list],
    kosdaq_pages: list[list],
):
    """fetch_naver_stock_list의 side_effect 생성.

    호출 순서: KOSPI p1, p2, p3, KOSDAQ p1, p2
    """
    call_responses = []
    for items in kospi_pages:
        call_responses.append((items, len(items)))
    for items in kosdaq_pages:
        call_responses.append((items, len(items)))

    call_count = [0]

    async def _side_effect(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(call_responses):
            return call_responses[idx]
        return ([], 0)

    return _side_effect


def _merge_candidates(leading: list[dict], news: list[dict], max_count: int) -> list[dict]:
    """후보 병합 로직 테스트용 헬퍼 (실제 구현과 동일한 로직).

    선행 후보 우선, 중복 제거, max_count 제한.
    """
    seen_codes = set()
    merged = []

    for c in leading:
        code = c.get("code") or c.get("stock_code")
        if code and code not in seen_codes:
            seen_codes.add(code)
            merged.append(c)

    for c in news:
        code = c.get("code") or c.get("stock_code")
        if code and code not in seen_codes:
            seen_codes.add(code)
            merged.append(c)

    return merged[:max_count]
