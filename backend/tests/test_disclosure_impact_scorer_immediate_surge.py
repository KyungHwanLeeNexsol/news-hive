"""SPEC-AI-080: 동일-당일 고확신 공시 촉매 즉시 급등 시그널 발화 테스트.

DDD PRESERVE(T2): process_disclosure_impact()의 기존 3분기(장중 30분 반영체크 예약 /
장마감후 impact>=25 gap_pullback_candidate 생성 / 그 외 무발화)를 즉시발화 분기 추가 전
characterization test로 고정한다. process_disclosure_impact()는 이 SPEC 이전 테스트
커버리지가 전무했다(Rule 4 대상).

IMPROVE(T3/T4): _is_immediate_event_class/_classify_disclosure_horizon/
_create_immediate_surge_signal 및 process_disclosure_impact()의 즉시발화 분기를 검증한다.

Scenario 6(하위호환): immediate_surge.enabled=false(기본값)에서 레거시 동작이 완전히
불변임을 별도로 확인한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.disclosure_impact_scorer import (
    _classify_disclosure_horizon,
    _is_immediate_event_class,
    process_disclosure_impact,
)
from app.surge_config.surge_settings import (
    DisclosureContentAwareScoringConfig,
    ImmediateSurgeConfig,
)

KST = ZoneInfo("Asia/Seoul")


def _make_disclosure(**kwargs) -> MagicMock:
    """테스트용 Disclosure MagicMock 생성 헬퍼 (기존 test_disclosure_impact_scorer.py 패턴)."""
    defaults = {
        "id": 1,
        "corp_code": "00000000",
        "corp_name": "테스트기업",
        "stock_code": "005930",
        "stock_id": 1,
        "report_name": "사업보고서",
        "report_type": "정기공시",
        "rcept_no": "202600000001",
        "rcept_dt": "20260709",
        "url": "https://dart.fss.or.kr/test/1",
        "ai_summary": None,
        "impact_score": None,
        "baseline_price": None,
        "reflected_pct": None,
        "unreflected_gap": None,
        "ripple_checked": False,
        "disclosed_at": None,
    }
    defaults.update(kwargs)
    d = MagicMock()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


def _make_db_with_stock(market_cap: int = 1000) -> MagicMock:
    db = MagicMock()
    stock = MagicMock()
    stock.market_cap = market_cap
    db.query.return_value.filter.return_value.first.return_value = stock
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    return db


def _immediate_cfg(**overrides) -> ImmediateSurgeConfig:
    return ImmediateSurgeConfig(**overrides)


class _StubSurgeConfig:
    """get_surge_config()를 대체하는 최소 스텁 — immediate_surge 필드만 필요.

    SPEC-AI-081: score_disclosure_impact()가 get_surge_config().disclosure_content_aware_scoring
    을 무조건 참조하게 되어(process_disclosure_impact() 내부에서 호출), 이 스텁도 해당 필드를
    갖추어야 한다. 기본값 enabled=False로 레거시 동작을 그대로 보존한다(REQ-AI081-004 정합).
    """

    def __init__(self, immediate_surge: ImmediateSurgeConfig) -> None:
        self.immediate_surge = immediate_surge
        self.disclosure_content_aware_scoring = DisclosureContentAwareScoringConfig(enabled=False)


# ---------------------------------------------------------------------------
# PRESERVE(T2): process_disclosure_impact() 기존 3분기 특성화
# (immediate_surge 기본값 enabled=false 기준 — 이 SPEC 이전 동작과 동일)
# ---------------------------------------------------------------------------

class TestProcessDisclosureImpactCharacterization:
    """PRESERVE: immediate_surge 비활성(기본값) 상태의 기존 3분기 동작 고정."""

    @pytest.mark.asyncio
    async def test_characterize_market_hours_schedules_reflection_check(self) -> None:
        """장중(09:00~15:30 KST 평일) + impact>=20 → 30분 반영체크 job 예약, 즉시발화 없음."""
        disclosure = _make_disclosure(
            report_name="단일판매ㆍ공급계약체결 500억원", stock_code="005930", stock_id=1,
        )
        db = _make_db_with_stock(market_cap=1000)
        market_dt = datetime(2026, 7, 9, 10, 0, tzinfo=KST)  # 목요일

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=market_dt),
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=50000,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=False, min_impact=1.0)),
            ),
            patch("app.services.disclosure_impact_scorer._schedule_reflection_check") as mock_schedule,
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_schedule.assert_called_once()
        mock_immediate.assert_not_called()

    @pytest.mark.asyncio
    async def test_characterize_after_market_high_impact_creates_gap_pullback(self) -> None:
        """장마감후(15:30~18:00) + impact>=25 → gap_pullback_candidate 생성, 즉시발화 없음."""
        disclosure = _make_disclosure(
            report_name="단일판매ㆍ공급계약체결 900억원", stock_code="005930", stock_id=1,
        )
        db = _make_db_with_stock(market_cap=100)
        after_market_dt = datetime(2026, 7, 9, 16, 0, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=after_market_dt),
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=50000,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=False, min_impact=1.0)),
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_gap_pullback_signal",
                new_callable=AsyncMock,
            ) as mock_gap,
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_gap.assert_called_once()
        mock_immediate.assert_not_called()

    @pytest.mark.asyncio
    async def test_characterize_low_impact_no_signal_no_schedule(self) -> None:
        """impact_score < 20 → 아무 분기도 실행되지 않는다(반영체크/gap_pullback/즉시발화 전부 없음)."""
        disclosure = _make_disclosure(report_name="사업보고서", stock_code="005930", stock_id=1)
        db = _make_db_with_stock(market_cap=1000)
        market_dt = datetime(2026, 7, 9, 10, 0, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=market_dt),
            patch("app.services.disclosure_impact_scorer._schedule_reflection_check") as mock_schedule,
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_schedule.assert_not_called()
        mock_immediate.assert_not_called()

    @pytest.mark.asyncio
    async def test_scenario6_disabled_config_never_triggers_immediate_path_even_when_eligible(
        self,
    ) -> None:
        """Scenario 6(rollback 완전성): immediate_surge.enabled=false이면 고확신 클래스 +
        고 impact_score여도 즉시발화 분기가 전혀 평가되지 않는다(레거시 동작만 실행)."""
        disclosure = _make_disclosure(
            report_name="단일판매ㆍ공급계약체결 900억원", stock_code="005930", stock_id=1,
        )
        db = _make_db_with_stock(market_cap=100)
        after_market_dt = datetime(2026, 7, 9, 16, 0, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=after_market_dt),
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=50000,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=False, min_impact=1.0)),
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_gap_pullback_signal",
                new_callable=AsyncMock,
            ) as mock_gap,
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_immediate.assert_not_called()
        mock_gap.assert_called_once()


# ---------------------------------------------------------------------------
# IMPROVE(T3): 헬퍼 함수 단위 테스트
# ---------------------------------------------------------------------------

class TestIsImmediateEventClass:
    """REQ-AI080-003: 고확신 이벤트 클래스 화이트리스트 판정."""

    @pytest.mark.parametrize(
        "report_name",
        [
            "자기주식소각결정",
            "주식소각결정",
            "보통주식소각 결정",
            "단일판매ㆍ공급계약체결",
            "단일판매·공급계약체결",
            "수주계약체결",
            "흡수합병결정",
            "합병결정 공고",
            "자기주식취득결정",
        ],
    )
    def test_whitelisted_classes_return_true(self, report_name: str) -> None:
        assert _is_immediate_event_class(report_name) is True

    @pytest.mark.parametrize(
        "report_name",
        ["지분공시", "정기주주총회결과", "사업보고서", "임원ㆍ주요주주특정증권등소유상황보고서"],
    )
    def test_non_whitelisted_classes_return_false(self, report_name: str) -> None:
        assert _is_immediate_event_class(report_name) is False

    def test_none_returns_false(self) -> None:
        assert _is_immediate_event_class(None) is False

    def test_empty_string_returns_false(self) -> None:
        assert _is_immediate_event_class("") is False


class TestClassifyDisclosureHorizon:
    """OQ-2: 접수 시각 기준 horizon(next_day/same_day) 분류."""

    def test_after_batch_cutoff_is_next_day(self) -> None:
        """15:20 KST 이후(장마감 무렵) 접수 → next_day."""
        cfg = _immediate_cfg()
        dt = datetime(2026, 7, 9, 16, 41, tzinfo=KST)  # 실증 사례: 신테카바이오 07-09 16:41
        assert _classify_disclosure_horizon(dt, cfg) == "next_day"

    def test_exact_batch_cutoff_is_next_day(self) -> None:
        """정확히 15:20 KST 접수 → next_day(컷오프 경계는 same_day 상한 미포함)."""
        cfg = _immediate_cfg()
        dt = datetime(2026, 7, 9, 15, 20, tzinfo=KST)
        assert _classify_disclosure_horizon(dt, cfg) == "next_day"

    def test_09_00_market_open_is_same_day(self) -> None:
        """09:00 KST(장 시작) 접수 → same_day(하한 경계는 포함)."""
        cfg = _immediate_cfg()
        dt = datetime(2026, 7, 9, 9, 0, tzinfo=KST)
        assert _classify_disclosure_horizon(dt, cfg) == "same_day"

    def test_market_hours_is_same_day(self) -> None:
        """장중(예: 11:00 KST) 접수 → same_day."""
        cfg = _immediate_cfg()
        dt = datetime(2026, 7, 9, 11, 0, tzinfo=KST)
        assert _classify_disclosure_horizon(dt, cfg) == "same_day"

    def test_overnight_pre_open_is_next_day(self) -> None:
        """EC-3: 야간/장전(예: 00:30 KST, 장 시작 전) 접수 → next_day."""
        cfg = _immediate_cfg()
        dt = datetime(2026, 7, 10, 0, 30, tzinfo=KST)
        assert _classify_disclosure_horizon(dt, cfg) == "next_day"

    def test_weekend_is_next_day(self) -> None:
        """주말(토요일) 접수 → next_day."""
        cfg = _immediate_cfg()
        dt = datetime(2026, 7, 11, 12, 0, tzinfo=KST)  # 토요일
        assert dt.weekday() == 5
        assert _classify_disclosure_horizon(dt, cfg) == "next_day"

    def test_respects_custom_cutoff_config(self) -> None:
        """batch_cutoff가 설정에서 오버라이드되면 그 값을 따른다."""
        cfg = _immediate_cfg(batch_cutoff_hour=14, batch_cutoff_minute=0)
        dt = datetime(2026, 7, 9, 14, 30, tzinfo=KST)
        assert _classify_disclosure_horizon(dt, cfg) == "next_day"


# ---------------------------------------------------------------------------
# IMPROVE(T3/T4): process_disclosure_impact() 즉시발화 분기 + _create_immediate_surge_signal
# ---------------------------------------------------------------------------

class TestImmediateFireIntegration:
    """즉시발화 분기 활성화 시 process_disclosure_impact() 및 시그널 생성 검증."""

    @pytest.mark.asyncio
    async def test_scenario1_qualifying_disclosure_bypasses_reflection_gate(self) -> None:
        """Scenario 1: 고확신 클래스 + impact>=min_impact → 즉시발화, 반영체크/gap_pullback 스킵(REQ-001)."""
        disclosure = _make_disclosure(
            report_name="단일판매ㆍ공급계약체결 500억원", stock_code="005930", stock_id=1,
        )
        db = _make_db_with_stock(market_cap=1000)
        after_close_dt = datetime(2026, 7, 9, 16, 41, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=after_close_dt),
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=50000,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=True, min_impact=1.0)),
            ),
            patch("app.services.disclosure_impact_scorer._schedule_reflection_check") as mock_schedule,
            patch(
                "app.services.disclosure_impact_scorer._create_gap_pullback_signal",
                new_callable=AsyncMock,
            ) as mock_gap,
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_immediate.assert_called_once()
        mock_schedule.assert_not_called()
        mock_gap.assert_not_called()

    @pytest.mark.asyncio
    async def test_scenario3_non_whitelisted_class_no_immediate_fire(self) -> None:
        """Scenario 3: 화이트리스트 밖 공시(지분공시)는 impact_score가 커도 즉시발화 안 됨(REQ-003)."""
        disclosure = _make_disclosure(
            report_name="지분공시 대량보유상황보고서", report_type="지분공시",
            stock_code="005930", stock_id=1,
        )
        db = _make_db_with_stock(market_cap=1000)
        after_close_dt = datetime(2026, 7, 9, 16, 41, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=after_close_dt),
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=50000,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=True, min_impact=1.0)),
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
            # 지분공시(impact=25)는 즉시발화 화이트리스트 밖이라 레거시 장마감후 gap_pullback
            # 분기(impact>=25)로 폴백된다 — 이 테스트는 그 분기의 정확성이 아니라 즉시발화
            # 미호출만 검증하므로 레거시 경로를 목 처리해 실제 네트워크/전역 캐시 부수효과를
            # 피한다(market_context._volatility_cache 오염 방지, 다른 테스트 모듈과 무관하게 유지).
            patch(
                "app.services.disclosure_impact_scorer._create_gap_pullback_signal",
                new_callable=AsyncMock,
            ),
        ):
            await process_disclosure_impact(db, disclosure)

        mock_immediate.assert_not_called()

    @pytest.mark.asyncio
    async def test_scenario3_below_min_impact_no_immediate_fire(self) -> None:
        """Scenario 3: 화이트리스트 클래스이나 impact_score < min_impact(소액 계약)면 즉시발화 안 됨(REQ-002)."""
        disclosure = _make_disclosure(
            report_name="단일판매ㆍ공급계약체결 10억원", stock_code="005930", stock_id=1,
        )
        db = _make_db_with_stock(market_cap=100000)  # ratio 작음 → impact_score 낮음
        after_close_dt = datetime(2026, 7, 9, 16, 41, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=after_close_dt),
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=50000,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=True, min_impact=40.0)),
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_immediate.assert_not_called()

    @pytest.mark.asyncio
    async def test_ec1_missing_stock_id_no_immediate_fire(self) -> None:
        """EC-1 관련: stock_id 없으면 즉시발화 게이트 자체가 스킵된다."""
        disclosure = _make_disclosure(
            report_name="단일판매ㆍ공급계약체결 500억원", stock_code="005930", stock_id=None,
        )
        db = _make_db_with_stock(market_cap=1000)
        after_close_dt = datetime(2026, 7, 9, 16, 41, tzinfo=KST)

        with (
            patch("app.services.disclosure_impact_scorer._get_kst_now", return_value=after_close_dt),
            # stock_id=None이라 즉시발화 게이트는 스킵되지만, 레거시 baseline_price 캡처
            # 분기(impact_score>=20 and stock_code)는 stock_id와 무관하게 여전히 평가되므로
            # 결정적 테스트를 위해 목 처리한다(실제 네트워크 호출 방지).
            patch(
                "app.services.disclosure_impact_scorer.capture_baseline_price",
                new_callable=AsyncMock, return_value=None,
            ),
            patch(
                "app.services.disclosure_impact_scorer.get_surge_config",
                return_value=_StubSurgeConfig(_immediate_cfg(enabled=True, min_impact=1.0)),
            ),
            patch(
                "app.services.disclosure_impact_scorer._create_immediate_surge_signal",
                new_callable=AsyncMock,
            ) as mock_immediate,
        ):
            await process_disclosure_impact(db, disclosure)

        mock_immediate.assert_not_called()


class TestCreateImmediateSurgeSignal:
    """_create_immediate_surge_signal 단위 테스트 — REQ-004/005/006, OQ-5."""

    @pytest.mark.asyncio
    async def test_signal_type_is_surge_candidate_with_non_none_metadata(self) -> None:
        """REQ-004/[E-1]: signal_type="surge_candidate" + surge_metadata non-None(EC-8 방지)."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure(
            id=42, report_name="단일판매ㆍ공급계약체결 500억원", stock_code="005930", stock_id=7,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # 신규 INSERT 경로
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        with (
            # SPEC-AI-088 REQ-002: _create_immediate_surge_signal이 fetch_current_price_with_change로
            # 교체되었으므로(current_price + change_rate 동시 반환), 이 모듈은 그 함수를 패치한다.
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 50000, "change_rate": 0.0},
            ),
            # 프로세스 전역 캐시(app.services.market_context._volatility_cache) 오염 방지 —
            # 실제 네트워크 호출을 막아 다른 테스트 모듈(test_market_context.py)에 영향 없게 한다.
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(db, disclosure, impact_score=82.0, horizon="next_day")

        assert signal is not None
        assert signal.signal_type == "surge_candidate"
        assert signal.surge_metadata is not None
        meta = json.loads(signal.surge_metadata)
        assert meta.get("immediate_disclosure") is True
        assert "immediate_disclosure" in meta.get("surge_basis", [])
        assert meta.get("horizon") == "next_day"

    @pytest.mark.asyncio
    async def test_oq5_marker_not_misidentified_as_near_limit_up_carry(self) -> None:
        """OQ-5(b): 마커가 _is_near_limit_up_carry_signal에 오판되지 않아야 한다(마커 충돌 없음)."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal
        from app.services.surge_evaluation_service import _is_near_limit_up_carry_signal

        disclosure = _make_disclosure(
            id=42, report_name="흡수합병결정", stock_code="005930", stock_id=7,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        with (
            # SPEC-AI-088 REQ-002: _create_immediate_surge_signal이 fetch_current_price_with_change로
            # 교체되었으므로(current_price + change_rate 동시 반환), 이 모듈은 그 함수를 패치한다.
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 50000, "change_rate": 0.0},
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(db, disclosure, impact_score=70.0, horizon="next_day")

        assert _is_near_limit_up_carry_signal(signal.surge_metadata) is False

    @pytest.mark.asyncio
    async def test_req005_never_calls_execute_signal_trade(self) -> None:
        """REQ-005(가장 안전 결정적 라인): execute_signal_trade가 절대 호출되지 않는다."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure(
            id=42, report_name="자기주식소각결정", stock_code="005930", stock_id=7,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        with (
            # SPEC-AI-088 REQ-002: _create_immediate_surge_signal이 fetch_current_price_with_change로
            # 교체되었으므로(current_price + change_rate 동시 반환), 이 모듈은 그 함수를 패치한다.
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 50000, "change_rate": 0.0},
            ),
            patch(
                "app.services.paper_trading.execute_signal_trade",
                new_callable=AsyncMock,
            ) as mock_trade,
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            await _create_immediate_surge_signal(db, disclosure, impact_score=90.0, horizon="next_day")

        mock_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_stock_id_returns_none(self) -> None:
        """stock_id 없으면 즉시 None 반환 — 시그널 미생성."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure(id=1, stock_id=None)
        db = MagicMock()

        result = await _create_immediate_surge_signal(db, disclosure, impact_score=90.0, horizon="next_day")
        assert result is None
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_req006_existing_recent_signal_updates_instead_of_duplicate_insert(self) -> None:
        """REQ-006/Scenario 5: 5역일 내 기존 surge_candidate 행이 있으면 UPDATE, 신규 INSERT 아님."""
        from app.models.fund_signal import FundSignal
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        existing_signal = FundSignal(
            stock_id=7, signal="buy", confidence=0.5, reasoning="기존",
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"surge_basis": ["theme_cluster"]}),
        )
        disclosure = _make_disclosure(
            id=42, report_name="단일판매ㆍ공급계약체결 500억원", stock_code="005930", stock_id=7,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_signal
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        with (
            # SPEC-AI-088 REQ-002: _create_immediate_surge_signal이 fetch_current_price_with_change로
            # 교체되었으므로(current_price + change_rate 동시 반환), 이 모듈은 그 함수를 패치한다.
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 50000, "change_rate": 0.0},
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(db, disclosure, impact_score=82.0, horizon="next_day")

        assert signal is existing_signal, "기존 행이 재사용(UPDATE)되어야 하며 신규 INSERT되지 않아야 한다"
        db.add.assert_not_called()
        meta = json.loads(signal.surge_metadata)
        assert meta.get("immediate_disclosure") is True

    @pytest.mark.asyncio
    async def test_price_fetch_failure_falls_back_to_baseline_price(self) -> None:
        """가격 조회 실패 시 disclosure.baseline_price로 대체하고 시그널 생성은 계속된다."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure(
            id=42, report_name="자기주식소각결정", stock_code="005930", stock_id=7,
            baseline_price=48000,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        with (
            # SPEC-AI-088 REQ-002: fetch_current_price_with_change로 교체됨(1콜→1콜, 응답 필드만 확장)
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock, side_effect=Exception("네트워크 오류"),
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(db, disclosure, impact_score=90.0, horizon="next_day")

        assert signal is not None
        assert signal.price_at_signal == 48000
