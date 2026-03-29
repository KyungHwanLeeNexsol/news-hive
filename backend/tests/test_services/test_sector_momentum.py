"""섹터 모멘텀 서비스 테스트.

SPEC-AI-002 Phase 2:
- REQ-AI-016: 섹터별 자금 흐름 추적
- REQ-AI-017: 섹터 로테이션 패턴 인식
- REQ-AI-019: 동일 섹터 시그널 중복 제거
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.sector_momentum import SectorMomentum
from app.models.sector_rotation_event import SectorRotationEvent
from app.services.sector_momentum import (
    CAPITAL_INFLOW_DAYS,
    MAX_SIGNALS_PER_SECTOR,
    MOMENTUM_THRESHOLD,
    ROTATION_CONFIDENCE_ADJUSTMENT,
    calculate_sector_momentum,
    deduplicate_sector_signals,
    detect_capital_inflow,
    detect_momentum_sectors,
    detect_sector_rotation,
    format_sector_momentum_for_briefing,
    get_rotation_adjusted_confidence,
    record_daily_sector_performance,
)


# ---------------------------------------------------------------------------
# REQ-AI-016: 섹터별 자금 흐름 추적
# ---------------------------------------------------------------------------


class TestRecordDailySectorPerformance:
    """record_daily_sector_performance 테스트."""

    @pytest.mark.asyncio
    async def test_records_sector_data(self, db, make_sector) -> None:
        """섹터 퍼포먼스 데이터를 정상적으로 저장한다."""
        sector = make_sector(name="반도체", naver_code="310")

        mock_perf = {
            "310": type("SP", (), {
                "naver_code": "310",
                "name": "반도체",
                "change_rate": 2.5,
                "total_stocks": 50,
                "rising_stocks": 30,
                "flat_stocks": 10,
                "falling_stocks": 10,
            })(),
        }

        with patch(
            "app.services.naver_finance.fetch_sector_performances",
            new_callable=AsyncMock,
            return_value=mock_perf,
        ):
            count = await record_daily_sector_performance(db)

        assert count == 1
        record = db.query(SectorMomentum).first()
        assert record is not None
        assert record.sector_id == sector.id
        assert record.daily_return == 2.5
        assert record.date == date.today()

    @pytest.mark.asyncio
    async def test_skips_if_already_exists(self, db, make_sector) -> None:
        """오늘 데이터가 이미 있으면 스킵한다."""
        sector = make_sector(name="반도체", naver_code="310")
        db.add(SectorMomentum(sector_id=sector.id, date=date.today(), daily_return=1.0))
        db.flush()

        count = await record_daily_sector_performance(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_fetch_failure(self, db) -> None:
        """퍼포먼스 수집 실패 시 0을 반환한다."""
        with patch(
            "app.services.naver_finance.fetch_sector_performances",
            new_callable=AsyncMock,
            side_effect=Exception("네트워크 오류"),
        ):
            count = await record_daily_sector_performance(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_empty_performances(self, db) -> None:
        """빈 퍼포먼스 데이터 시 0을 반환한다."""
        with patch(
            "app.services.naver_finance.fetch_sector_performances",
            new_callable=AsyncMock,
            return_value={},
        ):
            count = await record_daily_sector_performance(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_ignores_sectors_without_naver_code(self, db, make_sector) -> None:
        """naver_code가 없는 섹터는 무시한다."""
        make_sector(name="커스텀섹터")  # naver_code 없음

        mock_perf = {
            "999": type("SP", (), {
                "naver_code": "999",
                "name": "알 수 없는 섹터",
                "change_rate": 1.0,
                "total_stocks": 10,
                "rising_stocks": 5,
                "flat_stocks": 3,
                "falling_stocks": 2,
            })(),
        }

        with patch(
            "app.services.naver_finance.fetch_sector_performances",
            new_callable=AsyncMock,
            return_value=mock_perf,
        ):
            count = await record_daily_sector_performance(db)
        assert count == 0


class TestCalculateSectorMomentum:
    """calculate_sector_momentum 테스트."""

    def test_calculates_average_returns(self, db, make_sector) -> None:
        """5일 평균 등락률을 올바르게 계산한다."""
        sector = make_sector(name="반도체")
        today = date.today()

        # 5일간 데이터: 1.0, 2.0, 3.0, 4.0, 5.0 → 평균 3.0
        for i in range(5):
            db.add(SectorMomentum(
                sector_id=sector.id,
                date=today - timedelta(days=i),
                daily_return=float(i + 1),
            ))
        db.flush()

        result = calculate_sector_momentum(db)
        assert len(result) == 1
        assert result[0]["sector_id"] == sector.id
        assert result[0]["avg_return"] == 3.0
        assert result[0]["records"] == 5

    def test_empty_data_returns_empty(self, db) -> None:
        """데이터 없음 → 빈 리스트."""
        result = calculate_sector_momentum(db)
        assert result == []

    def test_multiple_sectors(self, db, make_sector) -> None:
        """여러 섹터의 평균을 각각 계산한다."""
        s1 = make_sector(name="반도체")
        s2 = make_sector(name="건설")
        today = date.today()

        for i in range(3):
            db.add(SectorMomentum(sector_id=s1.id, date=today - timedelta(days=i), daily_return=2.0))
            db.add(SectorMomentum(sector_id=s2.id, date=today - timedelta(days=i), daily_return=-1.0))
        db.flush()

        result = calculate_sector_momentum(db)
        assert len(result) == 2
        by_id = {r["sector_id"]: r for r in result}
        assert by_id[s1.id]["avg_return"] == 2.0
        assert by_id[s2.id]["avg_return"] == -1.0


class TestDetectMomentumSectors:
    """detect_momentum_sectors 테스트."""

    def test_detects_momentum_sector(self, db, make_sector) -> None:
        """시장 대비 +2%p 이상 섹터를 모멘텀으로 감지한다."""
        s1 = make_sector(name="핫섹터")
        s2 = make_sector(name="보통섹터")
        s3 = make_sector(name="부진섹터")
        today = date.today()

        for i in range(5):
            d = today - timedelta(days=i)
            db.add(SectorMomentum(sector_id=s1.id, date=d, daily_return=5.0))
            db.add(SectorMomentum(sector_id=s2.id, date=d, daily_return=1.0))
            db.add(SectorMomentum(sector_id=s3.id, date=d, daily_return=-1.0))
        # 오늘 데이터 추가 (momentum_tag 업데이트 대상)
        db.add(SectorMomentum(sector_id=s1.id, date=today, daily_return=5.0))
        db.flush()

        result = detect_momentum_sectors(db)

        # 시장 평균 ≈ (5+1-1)/3 ≈ 1.67, 핫섹터 excess ≈ 3.33 > 2.0
        assert len(result) >= 1
        sector_names = [r["sector_name"] for r in result]
        assert "핫섹터" in sector_names

    def test_no_momentum_when_similar(self, db, make_sector) -> None:
        """모든 섹터가 비슷하면 모멘텀 섹터 없음."""
        s1 = make_sector(name="A")
        s2 = make_sector(name="B")
        today = date.today()

        for i in range(5):
            d = today - timedelta(days=i)
            db.add(SectorMomentum(sector_id=s1.id, date=d, daily_return=1.0))
            db.add(SectorMomentum(sector_id=s2.id, date=d, daily_return=1.5))
        db.flush()

        result = detect_momentum_sectors(db)
        assert len(result) == 0

    def test_empty_data(self, db) -> None:
        """데이터 없음 → 빈 리스트."""
        result = detect_momentum_sectors(db)
        assert result == []


class TestDetectCapitalInflow:
    """detect_capital_inflow 테스트."""

    def test_detects_consecutive_positive_returns(self, db, make_sector) -> None:
        """3일 연속 양의 수익률 → 자금 유입 감지."""
        sector = make_sector(name="상승섹터")
        today = date.today()

        for i in range(3):
            db.add(SectorMomentum(
                sector_id=sector.id,
                date=today - timedelta(days=i),
                daily_return=1.5,
            ))
        db.flush()

        result = detect_capital_inflow(db)
        assert len(result) == 1
        assert result[0]["sector_name"] == "상승섹터"
        assert result[0]["consecutive_positive_days"] == CAPITAL_INFLOW_DAYS

    def test_no_inflow_with_negative_day(self, db, make_sector) -> None:
        """중간에 음의 수익률이 있으면 감지하지 않음."""
        sector = make_sector(name="혼합섹터")
        today = date.today()

        db.add(SectorMomentum(sector_id=sector.id, date=today, daily_return=2.0))
        db.add(SectorMomentum(sector_id=sector.id, date=today - timedelta(days=1), daily_return=-0.5))
        db.add(SectorMomentum(sector_id=sector.id, date=today - timedelta(days=2), daily_return=1.0))
        db.flush()

        result = detect_capital_inflow(db)
        assert len(result) == 0

    def test_insufficient_data(self, db, make_sector) -> None:
        """3일 미만 데이터 → 감지하지 않음."""
        sector = make_sector(name="신규섹터")
        today = date.today()

        db.add(SectorMomentum(sector_id=sector.id, date=today, daily_return=2.0))
        db.add(SectorMomentum(sector_id=sector.id, date=today - timedelta(days=1), daily_return=1.0))
        db.flush()

        result = detect_capital_inflow(db)
        assert len(result) == 0

    def test_zero_return_not_positive(self, db, make_sector) -> None:
        """0% 수익률은 양의 수익률이 아니므로 감지하지 않음."""
        sector = make_sector(name="횡보섹터")
        today = date.today()

        db.add(SectorMomentum(sector_id=sector.id, date=today, daily_return=0.0))
        db.add(SectorMomentum(sector_id=sector.id, date=today - timedelta(days=1), daily_return=1.0))
        db.add(SectorMomentum(sector_id=sector.id, date=today - timedelta(days=2), daily_return=2.0))
        db.flush()

        result = detect_capital_inflow(db)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# REQ-AI-017: 섹터 로테이션 패턴 인식
# ---------------------------------------------------------------------------


class TestDetectSectorRotation:
    """detect_sector_rotation 테스트."""

    def test_detects_rotation(self, db, make_sector) -> None:
        """어제 모멘텀 → 오늘 새 모멘텀으로 로테이션 감지."""
        s_old = make_sector(name="이전모멘텀")
        s_new = make_sector(name="신규모멘텀")
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 어제: s_old만 모멘텀
        db.add(SectorMomentum(
            sector_id=s_old.id, date=yesterday,
            daily_return=5.0, momentum_tag="momentum_sector",
        ))
        # 오늘: s_new만 모멘텀
        db.add(SectorMomentum(
            sector_id=s_new.id, date=today,
            daily_return=6.0, momentum_tag="momentum_sector",
        ))
        db.flush()

        events = detect_sector_rotation(db)
        assert len(events) == 1
        assert events[0].from_sector_id == s_old.id
        assert events[0].to_sector_id == s_new.id

    def test_no_rotation_same_momentum(self, db, make_sector) -> None:
        """어제와 오늘 같은 모멘텀 → 로테이션 없음."""
        sector = make_sector(name="지속모멘텀")
        today = date.today()
        yesterday = today - timedelta(days=1)

        db.add(SectorMomentum(
            sector_id=sector.id, date=yesterday,
            daily_return=5.0, momentum_tag="momentum_sector",
        ))
        db.add(SectorMomentum(
            sector_id=sector.id, date=today,
            daily_return=4.5, momentum_tag="momentum_sector",
        ))
        db.flush()

        events = detect_sector_rotation(db)
        assert len(events) == 0

    def test_no_rotation_without_previous_momentum(self, db, make_sector) -> None:
        """어제 모멘텀이 없으면 로테이션 감지하지 않음."""
        sector = make_sector(name="신규모멘텀")
        today = date.today()

        db.add(SectorMomentum(
            sector_id=sector.id, date=today,
            daily_return=5.0, momentum_tag="momentum_sector",
        ))
        db.flush()

        events = detect_sector_rotation(db)
        assert len(events) == 0

    def test_no_duplicate_rotation_events(self, db, make_sector) -> None:
        """같은 로테이션이 이미 있으면 중복 생성하지 않음."""
        s_old = make_sector(name="이전")
        s_new = make_sector(name="신규")
        today = date.today()
        yesterday = today - timedelta(days=1)

        db.add(SectorMomentum(
            sector_id=s_old.id, date=yesterday,
            daily_return=5.0, momentum_tag="momentum_sector",
        ))
        db.add(SectorMomentum(
            sector_id=s_new.id, date=today,
            daily_return=6.0, momentum_tag="momentum_sector",
        ))
        db.flush()

        # 첫 번째 호출
        events1 = detect_sector_rotation(db)
        assert len(events1) == 1

        # 두 번째 호출 → 중복 없어야 함
        events2 = detect_sector_rotation(db)
        assert len(events2) == 0


class TestGetRotationAdjustedConfidence:
    """get_rotation_adjusted_confidence 테스트."""

    def test_adjusts_confidence_on_rotation(self, db, make_sector) -> None:
        """로테이션된 섹터의 confidence를 -0.15 조정한다."""
        sector = make_sector(name="로테이션아웃")

        # 오늘 이 섹터가 from_sector로 기록
        event = SectorRotationEvent(
            from_sector_id=sector.id,
            to_sector_id=999,  # 임의
            confidence=0.5,
        )
        db.add(event)
        db.flush()

        adjusted = get_rotation_adjusted_confidence(db, sector.id, 0.8)
        assert adjusted == pytest.approx(0.8 + ROTATION_CONFIDENCE_ADJUSTMENT)

    def test_no_adjustment_without_rotation(self, db, make_sector) -> None:
        """로테이션 이벤트가 없으면 조정하지 않음."""
        sector = make_sector(name="안정섹터")
        adjusted = get_rotation_adjusted_confidence(db, sector.id, 0.8)
        assert adjusted == 0.8

    def test_confidence_floor_at_zero(self, db, make_sector) -> None:
        """조정 후 confidence가 0 미만이면 0.0으로 클램핑한다."""
        sector = make_sector(name="로테이션아웃")

        event = SectorRotationEvent(
            from_sector_id=sector.id,
            to_sector_id=999,
            confidence=0.5,
        )
        db.add(event)
        db.flush()

        adjusted = get_rotation_adjusted_confidence(db, sector.id, 0.1)
        assert adjusted == 0.0


# ---------------------------------------------------------------------------
# REQ-AI-019: 동일 섹터 시그널 중복 제거
# ---------------------------------------------------------------------------


class TestDeduplicateSectorSignals:
    """deduplicate_sector_signals 테스트."""

    def test_limits_to_max_per_sector(self) -> None:
        """같은 섹터 3개 시그널 → 최대 2개로 제한."""
        signals = [
            {"stock_name": "A", "sector_id": 1, "composite_score": 0.9, "trend_alignment": "aligned", "volume_spike": True},
            {"stock_name": "B", "sector_id": 1, "composite_score": 0.7, "trend_alignment": "divergent", "volume_spike": False},
            {"stock_name": "C", "sector_id": 1, "composite_score": 0.8, "trend_alignment": "aligned", "volume_spike": False},
        ]

        selected, excluded = deduplicate_sector_signals(signals)

        assert len(selected) == MAX_SIGNALS_PER_SECTOR
        assert len(excluded) == 1
        # 최고 점수 2개 선정
        selected_names = {s["stock_name"] for s in selected}
        assert "A" in selected_names  # 0.9 최고 점수

    def test_no_dedup_when_under_limit(self) -> None:
        """2개 이하면 모두 유지."""
        signals = [
            {"stock_name": "A", "sector_id": 1, "composite_score": 0.9, "trend_alignment": "aligned", "volume_spike": False},
            {"stock_name": "B", "sector_id": 1, "composite_score": 0.7, "trend_alignment": "divergent", "volume_spike": False},
        ]

        selected, excluded = deduplicate_sector_signals(signals)
        assert len(selected) == 2
        assert len(excluded) == 0

    def test_multiple_sectors_independent(self) -> None:
        """각 섹터별로 독립적으로 중복 제거."""
        signals = [
            {"stock_name": "A1", "sector_id": 1, "composite_score": 0.9, "trend_alignment": "aligned", "volume_spike": False},
            {"stock_name": "A2", "sector_id": 1, "composite_score": 0.8, "trend_alignment": "aligned", "volume_spike": False},
            {"stock_name": "A3", "sector_id": 1, "composite_score": 0.7, "trend_alignment": "divergent", "volume_spike": False},
            {"stock_name": "B1", "sector_id": 2, "composite_score": 0.6, "trend_alignment": "aligned", "volume_spike": False},
        ]

        selected, excluded = deduplicate_sector_signals(signals)
        assert len(selected) == 3  # 섹터1에서 2개, 섹터2에서 1개
        assert len(excluded) == 1

    def test_priority_composite_score_first(self) -> None:
        """composite_score가 가장 높은 순서로 선정."""
        signals = [
            {"stock_name": "Low", "sector_id": 1, "composite_score": 0.3, "trend_alignment": "aligned", "volume_spike": True},
            {"stock_name": "Mid", "sector_id": 1, "composite_score": 0.6, "trend_alignment": "divergent", "volume_spike": False},
            {"stock_name": "High", "sector_id": 1, "composite_score": 0.9, "trend_alignment": "divergent", "volume_spike": False},
        ]

        selected, excluded = deduplicate_sector_signals(signals)
        selected_names = {s["stock_name"] for s in selected}
        assert "High" in selected_names
        assert "Mid" in selected_names
        excluded_names = {s["stock_name"] for s in excluded}
        assert "Low" in excluded_names

    def test_priority_trend_alignment_tiebreaker(self) -> None:
        """composite_score 동점 시 aligned 우선."""
        signals = [
            {"stock_name": "Aligned", "sector_id": 1, "composite_score": 0.8, "trend_alignment": "aligned", "volume_spike": False},
            {"stock_name": "Divergent", "sector_id": 1, "composite_score": 0.8, "trend_alignment": "divergent", "volume_spike": False},
            {"stock_name": "Mixed", "sector_id": 1, "composite_score": 0.8, "trend_alignment": "mixed", "volume_spike": False},
        ]

        selected, excluded = deduplicate_sector_signals(signals)
        selected_names = {s["stock_name"] for s in selected}
        assert "Aligned" in selected_names

    def test_empty_signals(self) -> None:
        """빈 시그널 → 빈 결과."""
        selected, excluded = deduplicate_sector_signals([])
        assert selected == []
        assert excluded == []

    def test_signals_without_sector_id(self) -> None:
        """sector_id 없는 시그널은 무시."""
        signals = [
            {"stock_name": "NoSector", "composite_score": 0.9},
        ]
        selected, excluded = deduplicate_sector_signals(signals)
        assert len(selected) == 0
        assert len(excluded) == 0


# ---------------------------------------------------------------------------
# 브리핑 포맷팅 테스트
# ---------------------------------------------------------------------------


class TestFormatSectorMomentumForBriefing:
    """format_sector_momentum_for_briefing 테스트."""

    def test_with_momentum_data(self) -> None:
        """모멘텀 데이터가 있으면 섹터 모멘텀 섹션을 생성한다."""
        momentum = [
            {"sector_name": "반도체", "avg_return": 5.0, "excess_return": 3.0},
        ]
        text = format_sector_momentum_for_briefing(momentum)
        assert "섹터 모멘텀 분석" in text
        assert "반도체" in text
        assert "5.00%" in text
        assert "+3.00%p" in text

    def test_with_inflow_data(self) -> None:
        """자금 유입 데이터 표시."""
        inflow = [
            {"sector_name": "자동차", "consecutive_positive_days": 3, "avg_daily_return": 1.5},
        ]
        text = format_sector_momentum_for_briefing([], inflow)
        assert "자금 유입" in text
        assert "자동차" in text

    def test_with_rotation_events(self, db, make_sector) -> None:
        """로테이션 이벤트 표시."""
        s_from = make_sector(name="이전섹터")
        s_to = make_sector(name="새섹터")
        event = SectorRotationEvent(
            from_sector_id=s_from.id,
            to_sector_id=s_to.id,
            confidence=0.5,
        )
        db.add(event)
        db.flush()

        text = format_sector_momentum_for_briefing([], None, [event], db)
        assert "로테이션" in text
        assert "이전섹터" in text
        assert "새섹터" in text

    def test_empty_data(self) -> None:
        """데이터 없음 → '뚜렷한 모멘텀 섹터가 없습니다' 표시."""
        text = format_sector_momentum_for_briefing([])
        assert "뚜렷한 모멘텀 섹터가 없습니다" in text

    def test_combined_output(self, db, make_sector) -> None:
        """모든 데이터를 결합하여 출력한다."""
        s_from = make_sector(name="이전")
        s_to = make_sector(name="새로운")
        event = SectorRotationEvent(
            from_sector_id=s_from.id,
            to_sector_id=s_to.id,
            confidence=0.5,
        )
        db.add(event)
        db.flush()

        momentum = [{"sector_name": "핫섹터", "avg_return": 4.0, "excess_return": 2.5}]
        inflow = [{"sector_name": "유입섹터", "consecutive_positive_days": 3, "avg_daily_return": 1.2}]

        text = format_sector_momentum_for_briefing(momentum, inflow, [event], db)
        assert "핫섹터" in text
        assert "유입섹터" in text
        assert "로테이션" in text
