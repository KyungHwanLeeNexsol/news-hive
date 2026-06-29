"""SPEC-AI-065: 급등예측 리콜 개선 — 캐릭터라이제이션 및 인수조건 테스트.

AC-4: z-score 정규화 + cold-start fallback
AC-5: validate_ensemble_weights 8개 탐지기 합산=1.0
AC-6: surge_prediction_evaluation 4개 신규 컬럼 기록
AC-7: 기존 시그널 생성 파이프라인 테스트 통과
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.models.stock_signal_baseline import StockSignalBaseline
from app.surge_config.surge_settings import (
    EnsembleWeightsConfig,
    SurgeDetectionConfig,
    get_surge_config,
    reload_surge_config,
)
from app.services.surge_baseline_service import (
    BaselineStats,
    Observation,
    compute_zscore,
    get_baselines,
    update_baselines,
    zscore_to_score,
)
from app.services.surge_detector import (
    SurgeCandidate,
    compute_ensemble_score,
)


# ---------------------------------------------------------------------------
# AC-5: validate_ensemble_weights — 8개 탐지기 가중치 합산 검증
# ---------------------------------------------------------------------------

class TestCharacterizeValidateEnsembleWeights:
    """test_characterize_validate_ensemble_weights — 현재 config의 가중치 합산 검증."""

    def test_characterize_current_weights_sum_to_1(self):
        """현재 YAML 설정의 8개 탐지기 가중치 합산이 1.0이어야 한다 (AC-5)."""
        cfg = get_surge_config()
        w = cfg.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
            + w.volume_breakout
            + w.momentum_continuation
        )
        assert abs(total - 1.0) <= 0.001, f"가중치 합산 오류: {total:.4f}"

    def test_characterize_momentum_continuation_weight_nonzero(self):
        """momentum_continuation 가중치가 0.0 초과여야 한다 (AC-5, SPEC-AI-065 REQ-3)."""
        cfg = get_surge_config()
        assert cfg.ensemble.weights.momentum_continuation > 0.0

    def test_characterize_invalid_weights_raises(self):
        """8개 탐지기 가중치 합산이 1.0이 아니면 ValueError 발생한다."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises((ValueError, ValidationError)):
            from app.surge_config.surge_settings import (
                EnsembleWeightsConfig,
                EnsembleConfig,
                SurgeDetectionConfig,
                ThemeClusterConfig,
                VolumeNewsComboConfig,
                DisclosurePatternConfig,
                BacktestConfig,
            )
            # 합산=1.2로 의도적으로 오류 유발
            bad_weights = EnsembleWeightsConfig(
                theme_cluster=0.40,
                volume_news_combo=0.40,
                disclosure_pattern=0.40,  # 합산 = 1.2
                legacy_detectors=0.00,
                news_delayed=0.00,
                weekend_gap_up=0.00,
                volume_breakout=0.00,
                momentum_continuation=0.00,
            )
            SurgeDetectionConfig.model_validate(
                {
                    "theme_cluster": {
                        "keywords": ["반도체"],
                        "sector_theme_map": {"반도체": ["IT"]},
                        "cluster_window_hours": 48,
                        "min_article_count": 2,
                        "min_market_cap_krw": 50_000_000_000,
                    },
                    "volume_news_combo": {
                        "enabled": True,
                        "volume_zscore_threshold": 2.0,
                        "volume_baseline_days": 20,
                        "news_window_hours": 24,
                        "min_news_sentiment": 0.5,
                    },
                    "disclosure_pattern": {
                        "historical_surge_threshold_pct": 10.0,
                        "historical_lookback_days": 5,
                        "min_surge_rate": 0.40,
                        "min_sample_size": 20,
                        "cache_ttl_hours": 24,
                        "disclosure_window_hours": 24,
                    },
                    "ensemble": {
                        "weights": {
                            "theme_cluster": 0.40,
                            "volume_news_combo": 0.40,
                            "disclosure_pattern": 0.40,
                            "legacy_detectors": 0.00,
                            "news_delayed": 0.00,
                            "weekend_gap_up": 0.00,
                            "volume_breakout": 0.00,
                            "momentum_continuation": 0.00,  # 합산=1.2
                        },
                        "min_score_for_signal": 0.45,
                    },
                    "backtest": {"enabled": True, "evaluation_horizon_days": 5},
                }
            )

    def test_characterize_legacy_detectors_weight_is_zero(self):
        """legacy_detectors 가중치는 0.0이어야 한다 (SPEC-AI-050 REQ-5)."""
        cfg = get_surge_config()
        assert cfg.ensemble.weights.legacy_detectors == 0.0


# ---------------------------------------------------------------------------
# AC-4: z-score 정규화 + cold-start fallback
# ---------------------------------------------------------------------------

class TestCharacterizeZScoreNormalization:
    """test_characterize_zscore_normalization — z-score 기준선 서비스 행동 캡처."""

    def test_characterize_compute_zscore_normal(self):
        """충분한 샘플이 있을 때 z-score를 올바르게 계산한다 (AC-4)."""
        stats = BaselineStats(
            rolling_mean=0.30,
            rolling_m2=0.08,  # var = 0.08 / 9 ≈ 0.0089, std ≈ 0.094
            sample_count=10,
        )
        z = compute_zscore(0.30, stats, min_samples=10)
        # raw == mean → z = 0.0
        assert z is not None
        assert abs(z) < 0.01, f"z={z}, 기대값: 0.0"

    def test_characterize_compute_zscore_above_mean(self):
        """평균보다 높은 점수는 양의 z-score를 반환한다 (AC-4)."""
        stats = BaselineStats(
            rolling_mean=0.30,
            rolling_m2=0.0225,  # var = 0.0225 / 9 = 0.0025, std = 0.05
            sample_count=10,
        )
        z = compute_zscore(0.40, stats, min_samples=10)
        assert z is not None
        assert z > 0.0

    def test_characterize_cold_start_insufficient_samples(self):
        """샘플 수 부족 시 None 반환 (cold-start fallback, AC-4)."""
        stats = BaselineStats(rolling_mean=0.30, rolling_m2=0.0, sample_count=5)
        z = compute_zscore(0.30, stats, min_samples=10)
        assert z is None

    def test_characterize_cold_start_zero_std(self):
        """표준편차=0이면 None 반환 (cold-start fallback, AC-4)."""
        stats = BaselineStats(rolling_mean=0.30, rolling_m2=0.0, sample_count=10)
        z = compute_zscore(0.30, stats, min_samples=10)
        assert z is None

    def test_characterize_zscore_to_score_midpoint(self):
        """z=0 → sigmoid score = 0.5 (AC-4)."""
        score = zscore_to_score(0.0)
        assert abs(score - 0.5) < 0.001

    def test_characterize_zscore_to_score_high_z(self):
        """큰 양의 z-score는 1.0에 가까운 점수를 반환한다 (AC-4)."""
        score = zscore_to_score(5.0)
        assert score > 0.95

    def test_characterize_zscore_to_score_low_z(self):
        """큰 음의 z-score는 0.0에 가까운 점수를 반환한다 (AC-4)."""
        score = zscore_to_score(-5.0)
        assert score < 0.05


class TestCharacterizeBaselineService:
    """test_characterize_baseline_service — DB 기준선 CRUD 행동 캡처."""

    def test_characterize_get_baselines_empty_db(self, db: Session):
        """DB에 기준선 없으면 빈 dict를 반환한다."""
        result = get_baselines(db, ["000001"], ["theme_cluster"])
        assert result == {}

    def test_characterize_update_then_get_baselines(self, db: Session):
        """update_baselines 후 get_baselines에서 저장된 통계를 조회한다."""
        obs = [Observation("000001", "theme_cluster", 0.50)]
        update_baselines(db, obs)
        baselines = get_baselines(db, ["000001"], ["theme_cluster"])
        key = ("000001", "theme_cluster")
        assert key in baselines
        stats = baselines[key]
        assert stats.sample_count == 1
        assert abs(stats.rolling_mean - 0.50) < 0.001

    def test_characterize_update_baselines_multiple_observations(self, db: Session):
        """여러 관측값을 업데이트하면 sample_count가 증가하고 rolling_mean이 수렴한다."""
        for i in range(5):
            obs = [Observation("000002", "combo_score", 0.30 + i * 0.05)]
            update_baselines(db, obs)

        baselines = get_baselines(db, ["000002"], ["combo_score"])
        stats = baselines.get(("000002", "combo_score"))
        assert stats is not None
        assert stats.sample_count == 5
        # rolling_mean은 [0.30, 0.35, 0.40, 0.45, 0.50] EMA → 0.30과 0.50 사이
        assert 0.28 < stats.rolling_mean < 0.52

    def test_characterize_update_baselines_cold_start_std_zero(self, db: Session):
        """단일 샘플에서는 std=0 (cold-start 조건)이다."""
        obs = [Observation("000003", "theme_cluster", 0.60)]
        update_baselines(db, obs)
        baselines = get_baselines(db, ["000003"], ["theme_cluster"])
        stats = baselines[("000003", "theme_cluster")]
        assert stats.rolling_std == 0.0


# ---------------------------------------------------------------------------
# AC-6: surge_prediction_evaluation 4개 신규 컬럼
# ---------------------------------------------------------------------------

class TestCharacterizeSurgePredictionEvaluation:
    """test_characterize_surge_prediction_evaluation — 신규 컬럼 행동 캡처."""

    def test_characterize_new_columns_exist(self, db: Session):
        """SurgePredictionEvaluation에 4개 신규 컬럼이 존재한다 (AC-6)."""
        from datetime import date as _date

        eval_row = SurgePredictionEvaluation(
            evaluation_date=_date.today(),
            predicted_count=5,
            actual_surge_count=3,
            true_positive=1,
            false_positive=4,
            false_negative=2,
            precision=0.2,
            recall=0.33,
            f1_score=0.25,
            scan_universe_size=120,
            pool_a_count=20,
            pool_b_count=35,
            pool_c_count=15,
        )
        db.add(eval_row)
        db.flush()

        loaded = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == _date.today())
            .first()
        )
        assert loaded is not None
        assert loaded.scan_universe_size == 120
        assert loaded.pool_a_count == 20
        assert loaded.pool_b_count == 35
        assert loaded.pool_c_count == 15

    def test_characterize_pool_counts_nullable(self, db: Session):
        """pool_count 컬럼은 nullable — 기존 레코드에 NULL 허용 (AC-6)."""
        from datetime import date as _date

        yesterday = _date.today() - timedelta(days=1)
        eval_row = SurgePredictionEvaluation(
            evaluation_date=yesterday,
            predicted_count=0,
            actual_surge_count=0,
            true_positive=0,
            false_positive=0,
            false_negative=0,
        )
        db.add(eval_row)
        db.flush()

        loaded = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == yesterday)
            .first()
        )
        assert loaded is not None
        # NULL이어도 오류 없이 처리되어야 함


# ---------------------------------------------------------------------------
# AC-7: 기존 compute_ensemble_score 행동 보존
# ---------------------------------------------------------------------------

class TestCharacterizeComputeEnsembleScore:
    """test_characterize_compute_ensemble_score — 앙상블 점수 계산 행동 캡처."""

    def test_characterize_all_zero_scores_returns_zero(self):
        """모든 탐지기 점수=0이면 앙상블 점수=0이다 (AC-7)."""
        cfg = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트종목",
        )
        score = compute_ensemble_score(candidate, cfg)
        assert score == 0.0

    def test_characterize_score_clamped_to_one(self):
        """앙상블 점수는 1.0을 초과하지 않는다 (AC-7)."""
        cfg = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트종목",
            theme_cluster_score=1.0,
            combo_score=1.0,
            pattern_score=1.0,
            immediate_disclosure_score=1.0,
            news_delayed_score=1.0,
            volume_breakout_score=1.0,
            momentum_continuation_score=1.0,
        )
        score = compute_ensemble_score(candidate, cfg)
        assert score <= 1.0

    def test_characterize_momentum_continuation_contributes_to_score(self):
        """momentum_continuation_score가 앙상블 점수에 반영된다 (AC-7, SPEC-AI-065 REQ-3)."""
        cfg = get_surge_config()

        candidate_without = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트",
            theme_cluster_score=0.40,
        )
        candidate_with = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트",
            theme_cluster_score=0.40,
            momentum_continuation_score=0.50,
        )

        score_without = compute_ensemble_score(candidate_without, cfg)
        score_with = compute_ensemble_score(candidate_with, cfg)
        # momentum_continuation 가중치 > 0이면 점수가 더 높아야 함
        if cfg.ensemble.weights.momentum_continuation > 0:
            assert score_with > score_without

    def test_characterize_consensus_multiplier_applied(self):
        """2개 그룹 이상 활성화 시 consensus_multiplier가 적용된다 (AC-7)."""
        cfg = get_surge_config()

        # news 그룹만 (1개 그룹)
        single_group = SurgeCandidate(
            stock_code="000001", stock_name="테스트",
            theme_cluster_score=0.50, combo_score=0.50,  # news 그룹
        )
        # news + technical 그룹 (2개 그룹)
        two_groups = SurgeCandidate(
            stock_code="000001", stock_name="테스트",
            theme_cluster_score=0.50, combo_score=0.50,  # news
            volume_breakout_score=0.30,  # technical
        )

        score_single = compute_ensemble_score(single_group, cfg)
        score_two = compute_ensemble_score(two_groups, cfg)
        # 2그룹이면 consensus_multiplier_two 적용으로 점수가 더 높아야 함
        assert score_two > score_single


# ---------------------------------------------------------------------------
# StockSignalBaseline 모델 CRUD 테스트
# ---------------------------------------------------------------------------

class TestCharacterizeStockSignalBaseline:
    """test_characterize_stock_signal_baseline — 신규 모델 기본 CRUD."""

    def test_characterize_create_baseline_row(self, db: Session):
        """StockSignalBaseline 레코드를 생성하고 조회한다."""
        row = StockSignalBaseline(
            stock_code="005930",
            detector_name="theme_cluster",
            rolling_mean=0.35,
            rolling_m2=0.02,
            sample_count=15,
        )
        db.add(row)
        db.flush()

        loaded = (
            db.query(StockSignalBaseline)
            .filter(
                StockSignalBaseline.stock_code == "005930",
                StockSignalBaseline.detector_name == "theme_cluster",
            )
            .first()
        )
        assert loaded is not None
        assert abs(loaded.rolling_mean - 0.35) < 0.001
        assert loaded.sample_count == 15

    def test_characterize_unique_constraint(self, db: Session):
        """동일 (stock_code, detector_name) 조합에 중복 삽입은 불가하다."""
        from sqlalchemy.exc import IntegrityError

        db.add(StockSignalBaseline(
            stock_code="000660", detector_name="combo_score",
            rolling_mean=0.20, rolling_m2=0.0, sample_count=5,
        ))
        db.flush()

        with pytest.raises(IntegrityError):
            db.add(StockSignalBaseline(
                stock_code="000660", detector_name="combo_score",
                rolling_mean=0.30, rolling_m2=0.0, sample_count=10,
            ))
            db.flush()


# ---------------------------------------------------------------------------
# SurgeCandidate 신규 필드 테스트
# ---------------------------------------------------------------------------

class TestCharacterizeSurgeCandidateNewFields:
    """test_characterize_surge_candidate_new_fields — 신규 필드 기본값 검증."""

    def test_characterize_momentum_continuation_score_default_zero(self):
        """momentum_continuation_score 기본값은 0.0이다."""
        candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
        assert candidate.momentum_continuation_score == 0.0

    def test_characterize_entry_pool_default_existing(self):
        """entry_pool 기본값은 'existing'이다."""
        candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
        assert candidate.entry_pool == "existing"

    def test_characterize_momentum_continuation_score_set(self):
        """momentum_continuation_score를 설정하면 올바르게 반영된다."""
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트",
            momentum_continuation_score=0.55,
            entry_pool="pool_c",
        )
        assert abs(candidate.momentum_continuation_score - 0.55) < 0.001
        assert candidate.entry_pool == "pool_c"
