"""SPEC-AI-080: fund_manager.py 마커 인지형 스킵(재탐지 업서트/캐리오버) 특성화 및 회귀 테스트.

DDD PRESERVE(T2): 즉시 발화 마커가 없는 기존 시그널에 대해 두 덮어쓰기 사이트
(재탐지 업서트 fund_manager.py:1437-1464, SPEC-AI-039 캐리오버 :1531-1597)가
created_at/surge_metadata를 무조건 덮어쓰는 현재(레거시) 동작을 characterization test로
고정한다 — 가드 구현 전/후 모두 이 클래스는 GREEN이어야 한다(R-7 무회귀의 대조군).

Reproduction-First(CLAUDE.md Rule 4, acceptance.md Scenario 7): 즉시 발화 시그널
(created_at=T-1, surge_metadata에 immediate_disclosure 마커)이 익일 재탐지 업서트 또는
SPEC-AI-039 캐리오버를 거쳐도 T-1 created_at과 마커가 보존되는지 검증한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_detector import SurgeCandidate
from app.surge_config.surge_settings import SurgeDetectionConfig


@pytest.fixture
def surge_config() -> SurgeDetectionConfig:
    """테스트용 SurgeDetectionConfig (기본 설정 파일 기준)."""
    from app.surge_config.surge_settings import get_surge_config

    return get_surge_config()


@pytest.fixture
def sector_ai080(db: Session) -> Sector:
    """SPEC-AI-080 테스트 전용 섹터."""
    s = Sector(name="SPEC-AI-080테스트섹터")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def make_stock_ai080(db: Session):
    """SPEC-AI-080 테스트 전용 종목 팩토리."""
    _counter = [0]

    def _factory(name: str, stock_code: str, sector: Sector, market_cap: int = 500) -> Stock:
        _counter[0] += 1
        stock = Stock(
            name=name,
            stock_code=stock_code,
            sector_id=sector.id,
            market_cap=market_cap,
        )
        db.add(stock)
        db.flush()
        return stock

    return _factory


def _immediate_metadata(**overrides) -> str:
    """disclosure_impact_scorer._create_immediate_surge_signal이 부여하는 마커를 흉내낸다."""
    meta = {
        "surge_basis": ["immediate_disclosure"],
        "immediate_disclosure": True,
        "surge_probability_score": 0.8,
        "event_class": "단일판매ㆍ공급계약체결",
        "impact_score": 82.0,
        "disclosure_id": 999,
        "horizon": "next_day",
        "rcept_dt": "20260709",
    }
    meta.update(overrides)
    return json.dumps(meta, ensure_ascii=False)


# ---------------------------------------------------------------------------
# _is_immediate_disclosure_signal 단위 테스트
# ---------------------------------------------------------------------------

class TestIsImmediateDisclosureSignal:
    """_is_immediate_disclosure_signal 판별 함수 단위 테스트."""

    def test_none_returns_false(self) -> None:
        from app.services.fund_manager import _is_immediate_disclosure_signal

        assert _is_immediate_disclosure_signal(None) is False

    def test_empty_string_returns_false(self) -> None:
        from app.services.fund_manager import _is_immediate_disclosure_signal

        assert _is_immediate_disclosure_signal("") is False

    def test_invalid_json_returns_false(self) -> None:
        from app.services.fund_manager import _is_immediate_disclosure_signal

        assert _is_immediate_disclosure_signal("not json at all") is False

    def test_non_dict_json_returns_false(self) -> None:
        from app.services.fund_manager import _is_immediate_disclosure_signal

        assert _is_immediate_disclosure_signal("[1, 2, 3]") is False

    def test_surge_basis_list_membership_true(self) -> None:
        from app.services.fund_manager import _is_immediate_disclosure_signal

        assert _is_immediate_disclosure_signal(_immediate_metadata()) is True

    def test_flat_key_fallback_true(self) -> None:
        from app.services.fund_manager import _is_immediate_disclosure_signal

        meta = json.dumps({"immediate_disclosure": True})
        assert _is_immediate_disclosure_signal(meta) is True

    def test_theme_cluster_metadata_returns_false(self) -> None:
        """표준 지평 탐지기(theme_cluster) 마커는 즉시발화로 오판되지 않아야 한다."""
        from app.services.fund_manager import _is_immediate_disclosure_signal

        meta = json.dumps({"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8})
        assert _is_immediate_disclosure_signal(meta) is False

    def test_near_limit_up_carry_metadata_returns_false(self) -> None:
        """SPEC-AI-075 near_limit_up_carry 마커는 즉시발화로 오판되지 않아야 한다(마커 충돌 없음)."""
        from app.services.fund_manager import _is_immediate_disclosure_signal

        meta = json.dumps({"surge_basis": ["near_limit_up_carry"], "near_limit_up_carry": True})
        assert _is_immediate_disclosure_signal(meta) is False


# ---------------------------------------------------------------------------
# PRESERVE: 재탐지 업서트(fund_manager.py:1437-1464) 특성화 — 마커 없는 기존 거동
# ---------------------------------------------------------------------------

class TestReDetectionUpsertCharacterization:
    """PRESERVE(T2): 마커 없는 기존 시그널 재탐지 업서트 — 무조건 덮어쓰기 거동을 고정한다."""

    @pytest.mark.asyncio
    async def test_characterize_non_immediate_signal_overwritten_on_redetection(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_ai080: Sector,
        make_stock_ai080,
    ) -> None:
        """마커 없는(theme_cluster) 기존 surge_candidate가 재탐지되면 created_at/surge_metadata가
        무조건 오늘 값으로 갱신된다 — 가드 구현 전후 모두 이 동작이 유지되어야 한다(R-7 대조군).
        """
        from app.services.fund_manager import _gather_surge_candidates

        stock = make_stock_ai080("일반탐지종목", "900001", sector_ai080)
        old_created = datetime.now(timezone.utc) - timedelta(days=2)
        existing = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.5,
            reasoning="기존",
            signal_type="surge_candidate",
            surge_metadata=json.dumps(
                {"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.7}
            ),
            created_at=old_created,
        )
        db.add(existing)
        db.flush()

        # theme_cluster>=0.85 + combo_score>0.1 → strong_single_bypass 충족(품질 floor 우회) —
        # 그렇지 않으면 후보가 quality floor gate에서 continue되어 업서트 코드 자체에 도달하지
        # 못해(어설션이 우연히 통과하는) 거짓 양성 테스트가 된다.
        mock_candidate = SurgeCandidate(
            stock_code=stock.stock_code,
            stock_name=stock.name,
            theme_cluster_score=0.9,
            combo_score=0.9,
            active_detectors=["theme_cluster", "volume_news_combo"],
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[mock_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert existing.created_at > old_created, (
            "재탐지 시 created_at이 오늘로 갱신되어야 한다(레거시 거동)"
        )
        meta = json.loads(existing.surge_metadata)
        assert meta.get("surge_basis") == ["theme_cluster", "volume_news_combo"], (
            "재탐지 시 surge_metadata가 배치 값으로 교체되어야 한다(레거시 거동)"
        )


# ---------------------------------------------------------------------------
# IMPROVE + Scenario 7 (재탐지 업서트 절반): 즉시 발화 마커 보호
# ---------------------------------------------------------------------------

class TestReDetectionUpsertMarkerAwareSkip:
    """IMPROVE/Scenario 7: 즉시 발화 마커가 있는 기존 시그널은 재탐지 업서트에서 보호된다."""

    @pytest.mark.asyncio
    async def test_reproduce_immediate_signal_t1_attribution_survives_redetection(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_ai080: Sector,
        make_stock_ai080,
    ) -> None:
        """Scenario 7 (재탐지 경로): 즉시 발화 시그널(created_at=T-1, 마커 포함)이 익일
        재탐지 업서트를 거쳐도 created_at(T-1)·surge_metadata 마커가 보존되어야 한다.
        """
        from app.services.fund_manager import _gather_surge_candidates

        stock = make_stock_ai080("즉시발화종목", "900002", sector_ai080)
        t_minus_1 = datetime.now(timezone.utc) - timedelta(hours=20)
        immediate_signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.82,
            reasoning="즉시발화",
            signal_type="surge_candidate",
            surge_metadata=_immediate_metadata(),
            created_at=t_minus_1,
            originally_created_at=t_minus_1,
        )
        db.add(immediate_signal)
        db.flush()

        # 품질 floor 우회(strong_single_bypass) 조합 — 업서트 코드 경로에 실제로 도달시킨다.
        mock_candidate = SurgeCandidate(
            stock_code=stock.stock_code,
            stock_name=stock.name,
            theme_cluster_score=0.9,
            combo_score=0.9,
            active_detectors=["theme_cluster", "volume_news_combo"],
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[mock_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert immediate_signal.created_at == t_minus_1, (
            "즉시 발화 시그널의 T-1 created_at은 익일 재탐지 업서트에도 보존되어야 한다(R-6)"
        )
        meta = json.loads(immediate_signal.surge_metadata)
        assert meta.get("immediate_disclosure") is True, (
            "즉시 발화 마커가 재탐지 업서트에도 보존되어야 한다"
        )
        assert "immediate_disclosure" in meta.get("surge_basis", [])

    @pytest.mark.asyncio
    async def test_immediate_signal_confidence_still_updated_on_redetection(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_ai080: Sector,
        make_stock_ai080,
    ) -> None:
        """confidence/composite_score 갱신은 recall 버킷팅에 영향이 없으므로 가드 대상이
        아니다 — 재탐지 시에도 정상적으로 갱신되어야 한다(설계 메모, R-6/R-7과 무관)."""
        from app.services.fund_manager import _gather_surge_candidates

        stock = make_stock_ai080("즉시발화종목2", "900003", sector_ai080)
        t_minus_1 = datetime.now(timezone.utc) - timedelta(hours=20)
        immediate_signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.10,
            reasoning="즉시발화",
            signal_type="surge_candidate",
            surge_metadata=_immediate_metadata(),
            created_at=t_minus_1,
            originally_created_at=t_minus_1,
        )
        db.add(immediate_signal)
        db.flush()

        mock_candidate = SurgeCandidate(
            stock_code=stock.stock_code,
            stock_name=stock.name,
            theme_cluster_score=0.9,
            combo_score=0.9,
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[mock_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert immediate_signal.confidence != 0.10, "confidence는 마커와 무관하게 갱신되어야 한다"


# ---------------------------------------------------------------------------
# PRESERVE: SPEC-AI-039 캐리오버(fund_manager.py:1531-1597) 특성화 — 마커 없는 기존 거동
# ---------------------------------------------------------------------------

class TestCarryoverCharacterization:
    """PRESERVE(T2): 마커 없는 기존 시그널의 캐리오버 — 무조건 덮어쓰기 거동을 고정한다."""

    @pytest.mark.asyncio
    async def test_characterize_non_immediate_signal_overwritten_on_carryover(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_ai080: Sector,
        make_stock_ai080,
    ) -> None:
        """마커 없는(theme_cluster) 기존 시그널이 캐리오버 대상이 되면 created_at이 무조건
        오늘로 갱신된다 — 가드 구현 전후 모두 이 동작이 유지되어야 한다(R-7 대조군).
        """
        from app.services.fund_manager import _gather_surge_candidates

        filler_stock = make_stock_ai080("필러종목", "900010", sector_ai080)
        carry_stock = make_stock_ai080("캐리오버종목", "900011", sector_ai080)

        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        carry_created = today_start - timedelta(hours=20)

        carry_signal = FundSignal(
            stock_id=carry_stock.id,
            signal="buy",
            confidence=0.90,
            reasoning="기존",
            signal_type="surge_candidate",
            surge_metadata=json.dumps(
                {"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}
            ),
            created_at=carry_created,
            originally_created_at=carry_created,
        )
        db.add(carry_signal)
        db.flush()

        # candidates가 비어 있으면 _gather_surge_candidates가 캐리오버 섹션 진입 전
        # 조기 반환하므로(fund_manager.py:1321 `if not candidates: return []`), 캐리오버
        # 대상과 무관한 필러 후보를 하나 포함시켜 캐리오버 섹션까지 도달하게 한다.
        filler_candidate = SurgeCandidate(
            stock_code=filler_stock.stock_code,
            stock_name=filler_stock.name,
            theme_cluster_score=0.1,
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[filler_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert carry_signal.created_at > carry_created, (
            "캐리오버 시 created_at이 오늘로 갱신되어야 한다(레거시 거동)"
        )
        meta = json.loads(carry_signal.surge_metadata)
        assert meta.get("carry_over") is True


# ---------------------------------------------------------------------------
# IMPROVE + Scenario 7 (캐리오버 절반): 즉시 발화 마커 보호
# ---------------------------------------------------------------------------

class TestCarryoverMarkerAwareSkip:
    """IMPROVE/Scenario 7: 즉시 발화 마커가 있는 기존 시그널은 캐리오버에서도 보호된다."""

    @pytest.mark.asyncio
    async def test_reproduce_immediate_signal_t1_attribution_survives_carryover(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_ai080: Sector,
        make_stock_ai080,
    ) -> None:
        """Scenario 7 (캐리오버 경로): 즉시 발화 시그널(created_at=T-1, 마커 포함)이 재탐지
        되지 않아도 SPEC-AI-039 캐리오버를 거치면 created_at(T-1)·마커가 보존되어야 한다.
        """
        from app.services.fund_manager import _gather_surge_candidates

        filler_stock = make_stock_ai080("필러종목2", "900012", sector_ai080)
        carry_stock = make_stock_ai080("즉시발화캐리종목", "900013", sector_ai080)

        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        t_minus_1 = today_start - timedelta(hours=20)

        immediate_signal = FundSignal(
            stock_id=carry_stock.id,
            signal="buy",
            confidence=0.90,
            reasoning="즉시발화",
            signal_type="surge_candidate",
            surge_metadata=_immediate_metadata(),
            created_at=t_minus_1,
            originally_created_at=t_minus_1,
        )
        db.add(immediate_signal)
        db.flush()

        filler_candidate = SurgeCandidate(
            stock_code=filler_stock.stock_code,
            stock_name=filler_stock.name,
            theme_cluster_score=0.1,
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[filler_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert immediate_signal.created_at == t_minus_1, (
            "즉시 발화 시그널의 T-1 created_at은 캐리오버에도 보존되어야 한다(R-6)"
        )
        meta = json.loads(immediate_signal.surge_metadata)
        assert meta.get("immediate_disclosure") is True
        assert "immediate_disclosure" in meta.get("surge_basis", [])
        assert meta.get("carry_over") is True, (
            "carry_over 마킹(confidence decay 등 recall과 무관한 값 갱신)은 마커와 무관하게 계속 적용된다"
        )

    @pytest.mark.asyncio
    async def test_immediate_signal_below_carryover_threshold_skipped_same_as_legacy(
        self,
        db: Session,
        surge_config: SurgeDetectionConfig,
        sector_ai080: Sector,
        make_stock_ai080,
    ) -> None:
        """마커 유무와 무관하게 decayed_score < 0.50이면 캐리오버 자체가 skip된다
        (마커 인지형 스킵은 캐리오버 진입 이후에만 개입 — 임계 게이트 자체는 불변)."""
        from app.services.fund_manager import _gather_surge_candidates

        filler_stock = make_stock_ai080("필러종목3", "900014", sector_ai080)
        low_conf_stock = make_stock_ai080("저신뢰도즉시발화종목", "900015", sector_ai080)

        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        t_minus_1 = today_start - timedelta(hours=20)

        low_conf_signal = FundSignal(
            stock_id=low_conf_stock.id,
            signal="buy",
            confidence=0.30,  # decayed = 0.285 < 0.50 → carryover skip
            reasoning="즉시발화",
            signal_type="surge_candidate",
            surge_metadata=_immediate_metadata(),
            created_at=t_minus_1,
            originally_created_at=t_minus_1,
        )
        db.add(low_conf_signal)
        db.flush()

        filler_candidate = SurgeCandidate(
            stock_code=filler_stock.stock_code,
            stock_name=filler_stock.name,
            theme_cluster_score=0.1,
        )
        with patch(
            "app.services.fund_manager.gather_surge_candidates",
            return_value=[filler_candidate],
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        # 캐리오버 임계 미달로 skip되어 confidence/created_at 모두 불변이어야 한다
        assert low_conf_signal.confidence == 0.30
        assert low_conf_signal.created_at == t_minus_1
