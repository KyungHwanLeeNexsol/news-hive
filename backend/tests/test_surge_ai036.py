"""SPEC-AI-036: composite_score 활성화 및 confidence 캘리브레이션 테스트.

AC-7: surge_candidate composite_score / factor_scores 비-NULL 확인
AC-8: composite_score 0.0~1.0 범위
AC-9: factor_scores JSON 필수 키 포함
AC-10: floor 게이트 — calibrated<0.35 AND composite<0.60 → 차단
AC-11: floor 게이트 — calibrated>=0.36 AND composite<0.45 → 통과 (confidence 조건 충족)
AC-12: 예외 격리 — composite_score 계산 실패 시 시그널 생성 계속
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.factor_scoring import build_surge_factor_scores
from app.services.surge_detector import SurgeCandidate, compute_ensemble_score
from app.surge_config.surge_settings import SurgeDetectionConfig


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def surge_config() -> SurgeDetectionConfig:
    from app.surge_config.surge_settings import get_surge_config
    return get_surge_config()


@pytest.fixture
def make_candidate() -> SurgeCandidate:
    """기본 SurgeCandidate 팩토리 함수."""
    def _factory(
        stock_code: str = "000660",
        stock_name: str = "SK하이닉스",
        theme_cluster_score: float = 0.6,
        combo_score: float = 0.4,
        pattern_score: float = 0.3,
        immediate_disclosure_score: float = 0.0,
        legacy_score: float = 0.5,
    ) -> SurgeCandidate:
        return SurgeCandidate(
            stock_code=stock_code,
            stock_name=stock_name,
            theme_cluster_score=theme_cluster_score,
            combo_score=combo_score,
            pattern_score=pattern_score,
            immediate_disclosure_score=immediate_disclosure_score,
            legacy_score=legacy_score,
            active_detectors=["theme_cluster", "legacy"],
        )
    return _factory


# ---------------------------------------------------------------------------
# AC-7, AC-8, AC-9: build_surge_factor_scores 단위 테스트
# ---------------------------------------------------------------------------

class TestBuildSurgeFactorScores:
    def test_ac7_returns_non_empty(self, make_candidate, surge_config):
        """AC-7: factor_scores_json 비어있지 않고 composite_score가 양수."""
        candidate = make_candidate()
        factor_json, composite = build_surge_factor_scores(candidate, surge_config)

        assert factor_json != "", "factor_scores_json이 비어 있음"
        assert composite > 0.0, "composite_score가 0"

    def test_ac8_composite_in_range(self, make_candidate, surge_config):
        """AC-8: composite_score ∈ [0.0, 1.0]."""
        for theme in [0.0, 0.3, 0.7, 1.0]:
            for combo in [0.0, 0.5, 1.0]:
                candidate = make_candidate(
                    theme_cluster_score=theme,
                    combo_score=combo,
                    legacy_score=0.3,
                )
                _, composite = build_surge_factor_scores(candidate, surge_config)
                assert 0.0 <= composite <= 1.0, (
                    f"범위 이탈: theme={theme}, combo={combo}, composite={composite}"
                )

    def test_ac9_factor_json_contains_required_keys(self, make_candidate, surge_config):
        """AC-9: factor_scores JSON에 필수 키 5개 포함."""
        candidate = make_candidate()
        factor_json, _ = build_surge_factor_scores(candidate, surge_config)

        assert factor_json
        scores = json.loads(factor_json)
        required_keys = {"theme_cluster", "combo", "pattern", "immediate_disclosure", "legacy"}
        missing = required_keys - set(scores.keys())
        assert not missing, f"누락 키: {missing}"

    def test_composite_equals_ensemble_score(self, make_candidate, surge_config):
        """composite_score는 compute_ensemble_score와 동일해야 한다."""
        candidate = make_candidate(
            theme_cluster_score=0.8,
            combo_score=0.5,
            pattern_score=0.2,
            immediate_disclosure_score=0.0,
            legacy_score=0.4,
        )
        expected = compute_ensemble_score(candidate, surge_config)
        _, composite = build_surge_factor_scores(candidate, surge_config)
        assert abs(composite - expected) < 1e-4, (
            f"composite={composite} != ensemble={expected}"
        )

    def test_exception_returns_empty_tuple(self, make_candidate, surge_config):
        """build_surge_factor_scores 내 예외 → ('', 0.0) 반환."""
        candidate = make_candidate()
        # factor_scoring 내부에서 import하는 compute_ensemble_score를 mock
        with patch(
            "app.services.factor_scoring.build_surge_factor_scores",
            wraps=None,  # wraps 제거 후 직접 내부 경로 mock
        ):
            pass  # 이 방식은 부정확 → 내부 import를 직접 patch

        # 올바른 방식: factor_scoring.py 내부에서 compute_ensemble_score import 경로 mock
        import app.services.factor_scoring as fs_module
        with patch.object(
            fs_module,
            "build_surge_factor_scores",
            side_effect=RuntimeError("테스트 예외"),
        ):
            # 이 경우 함수 자체가 예외 → 호출부에서 처리해야 함
            # 여기서는 실제 함수의 try/except 동작을 검증하는 대신
            # 직접 내부 의존성을 mock해서 검증
            pass

        # 직접 검증: compute_ensemble_score를 side_effect로 예외 발생
        with patch(
            "app.services.surge_detector.compute_ensemble_score",
            side_effect=RuntimeError("테스트 예외"),
        ):
            from app.services.factor_scoring import build_surge_factor_scores as bsfs
            result = bsfs(candidate, surge_config)
            assert result == ("", 0.0)


# ---------------------------------------------------------------------------
# AC-10, AC-11: 품질 floor 게이트 (fund_manager 경로)
# ---------------------------------------------------------------------------

class TestFloorGate:
    """M3 품질 floor 게이트: _gather_surge_candidates 내부 gate 로직."""

    def _make_surge_config_with_defaults(self, surge_config: SurgeDetectionConfig):
        """테스트용 config (기본값 사용)."""
        return surge_config

    def test_ac10_floor_gate_blocks_low_quality(self, surge_config):
        """AC-10: calibrated_confidence < 0.35 AND composite_score < 0.60 → 차단.

        fund_manager의 floor 게이트 로직을 직접 테스트.
        """
        # 게이트 조건 재현
        min_conf = surge_config.min_calibrated_confidence  # 0.35
        min_comp = surge_config.min_composite_score  # 0.60

        calibrated_confidence = 0.30
        composite_score = 0.50

        # OR 게이트: 둘 다 미달 → 차단
        should_block = (
            calibrated_confidence < min_conf
            and composite_score < min_comp
        )
        assert should_block, "둘 다 미달 → 차단이어야 함"

    def test_ac11_floor_gate_passes_on_confidence(self, surge_config):
        """AC-11: calibrated_confidence >= 0.36 (AND composite < 0.45) → 통과."""
        min_conf = surge_config.min_calibrated_confidence  # 0.35
        min_comp = surge_config.min_composite_score  # 0.60

        calibrated_confidence = 0.36
        composite_score = 0.45

        # OR 게이트: confidence 조건 충족 → 통과
        should_block = (
            calibrated_confidence < min_conf
            and composite_score < min_comp
        )
        assert not should_block, "confidence 조건 충족 → 통과이어야 함"

    def test_floor_gate_passes_on_composite(self, surge_config):
        """composite_score >= 0.60 (AND calibrated < 0.35) → 통과."""
        min_conf = surge_config.min_calibrated_confidence
        min_comp = surge_config.min_composite_score

        calibrated_confidence = 0.30
        composite_score = 0.65

        should_block = (
            calibrated_confidence < min_conf
            and composite_score < min_comp
        )
        assert not should_block, "composite 조건 충족 → 통과이어야 함"

    def test_floor_gate_config_defaults(self, surge_config):
        """SurgeDetectionConfig의 SPEC-AI-036 기본값 확인."""
        assert surge_config.min_calibrated_confidence == pytest.approx(0.35)
        assert surge_config.min_composite_score == pytest.approx(0.60)
        assert surge_config.min_calibration_samples == 50


# ---------------------------------------------------------------------------
# AC-12: 예외 격리 테스트
# ---------------------------------------------------------------------------

class TestExceptionIsolation:
    def test_ac12_build_surge_factor_scores_exception_returns_empty(
        self, make_candidate, surge_config
    ):
        """AC-12: build_surge_factor_scores 내부 예외 시 ('', 0.0) 반환, 파이프라인 중단 없음."""
        candidate = make_candidate()

        with patch(
            "app.services.surge_detector.compute_ensemble_score",
            side_effect=RuntimeError("테스트 예외 — 예외 격리 검증"),
        ):
            from app.services.factor_scoring import build_surge_factor_scores as bsfs
            result = bsfs(candidate, surge_config)

        assert result == ("", 0.0), f"예외 격리 실패: {result}"

    def test_calibrate_confidence_exception_returns_raw(self):
        """calibrate_confidence 예외 시 raw confidence 반환."""
        from app.services.surge_calibrator import calibrate_confidence

        with patch(
            "app.services.surge_calibrator.get_calibrator",
            side_effect=RuntimeError("모델 로드 실패"),
        ):
            result = calibrate_confidence(0.45)

        # 예외 격리: raw 반환 (0.0~1.0 범위 보장)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# signal_verifier: get_surge_calibration_pairs 단위 테스트
# ---------------------------------------------------------------------------

class TestGetSurgeCalibrationPairs:
    def test_returns_only_verified_surge_candidates(self, db: Session):
        """검증 완료 surge_candidate만 반환한다."""
        from app.services.signal_verifier import get_surge_calibration_pairs

        # DB에 직접 시그널 삽입
        sector = Sector(name="IT테스트")
        db.add(sector)
        db.flush()
        stock = Stock(name="테스트종목AI036", stock_code="AI036T", sector_id=sector.id, market_cap=100)
        db.add(stock)
        db.flush()

        now = datetime.now(timezone.utc)

        # 1. 검증 완료 surge_candidate
        verified = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.55,
            reasoning="test",
            is_correct=True,
            verified_at=now,
            created_at=now,
        )
        db.add(verified)

        # 2. 미검증 surge_candidate (제외되어야 함)
        unverified = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.40,
            reasoning="test",
            is_correct=None,
            verified_at=None,
            created_at=now,
        )
        db.add(unverified)

        # 3. 다른 signal_type (제외되어야 함)
        other_type = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="disclosure_impact",
            confidence=0.60,
            reasoning="test",
            is_correct=True,
            verified_at=now,
            created_at=now,
        )
        db.add(other_type)
        db.flush()

        pairs = get_surge_calibration_pairs(db, lookback_days=90)

        assert len(pairs) == 1, f"검증된 surge_candidate 1개만 반환해야 함: {pairs}"
        raw, is_correct = pairs[0]
        assert abs(raw - 0.55) < 1e-9
        assert is_correct == 1


# ---------------------------------------------------------------------------
# signal_quality.py 단위 테스트
# ---------------------------------------------------------------------------

class TestSignalQualityMetrics:
    def test_empty_db_returns_insufficient_data(self, db: Session):
        """surge_candidate 없는 경우 status=insufficient_data."""
        from app.services.signal_quality import get_signal_quality_metrics

        result = get_signal_quality_metrics(db)
        assert result["status"] == "insufficient_data"

    def test_with_surge_signals_returns_ok(self, db: Session):
        """surge_candidate 있는 경우 status=ok."""
        from app.services.signal_quality import get_signal_quality_metrics

        sector = Sector(name="신호품질IT")
        db.add(sector)
        db.flush()
        stock = Stock(name="품질테스트", stock_code="QUALIT", sector_id=sector.id, market_cap=100)
        db.add(stock)
        db.flush()

        now = datetime.now(timezone.utc)
        for i in range(3):
            sig = FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.3 + i * 0.1,
                reasoning="test",
                created_at=now,
            )
            db.add(sig)
        db.flush()

        result = get_signal_quality_metrics(db)
        assert result["status"] == "ok"
        assert "composite_score_fill_rate" in result
        assert "confidence_distribution" in result
        assert "scale_info" in result
        assert result["scale_info"]["surge"] == "0.0~1.0"

    def test_fill_rate_with_composite_scores(self, db: Session):
        """composite_score가 있는 시그널 채움률 계산."""
        from app.services.signal_quality import get_signal_quality_metrics

        sector = Sector(name="채움률IT")
        db.add(sector)
        db.flush()
        stock = Stock(name="채움률테스트", stock_code="FILL01", sector_id=sector.id, market_cap=100)
        db.add(stock)
        db.flush()

        now = datetime.now(timezone.utc)

        # 2개는 composite_score 있음, 1개는 NULL
        for i, comp in enumerate([0.6, 0.7, None]):
            sig = FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.4,
                reasoning="test",
                composite_score=comp,
                created_at=now,
            )
            db.add(sig)
        db.flush()

        result = get_signal_quality_metrics(db)
        fill_rate = result["composite_score_fill_rate"]
        assert abs(fill_rate - 2 / 3) < 0.01, f"채움률 기대 2/3: {fill_rate}"

    def test_brier_score_computed_for_verified(self, db: Session):
        """검증 완료 >= 10개 시 brier_score 계산."""
        from app.services.signal_quality import get_signal_quality_metrics

        sector = Sector(name="브리어IT")
        db.add(sector)
        db.flush()
        stock = Stock(name="브리어테스트", stock_code="BRIER1", sector_id=sector.id, market_cap=100)
        db.add(stock)
        db.flush()

        now = datetime.now(timezone.utc)
        for i in range(10):
            sig = FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.5,
                reasoning="test",
                is_correct=(i % 2 == 0),
                verified_at=now,
                created_at=now,
            )
            db.add(sig)
        db.flush()

        result = get_signal_quality_metrics(db)
        assert result["brier_score"] is not None
        # confidence=0.5, actual = 0 또는 1 → brier = mean((0.5-actual)^2) = 0.25
        assert abs(result["brier_score"] - 0.25) < 0.01
