"""SPEC-AI-065: 급등예측 리콜 개선 — 캐릭터라이제이션 및 인수조건 테스트.

AC-4: z-score 정규화 + cold-start fallback
AC-5: validate_ensemble_weights 8개 탐지기 합산=1.0
AC-6: surge_prediction_evaluation 4개 신규 컬럼 기록
AC-7: 기존 시그널 생성 파이프라인 테스트 통과
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.models.stock_signal_baseline import StockSignalBaseline
from app.surge_config.surge_settings import (
    get_surge_config,
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
    build_scan_universe,
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
                SurgeDetectionConfig,
            )
            # 합산=1.2로 의도적으로 오류 유발
            _ = EnsembleWeightsConfig(
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


# ---------------------------------------------------------------------------
# SPEC-AI-076: 스캔 유니버스 풀 절단 크라우딩아웃 교정 — quota 배분 (build_scan_universe)
# ---------------------------------------------------------------------------
#
# 픽스처 헬퍼: Pool A(DART 공시)/Pool C(당일 등락률 5%+)는 DB에 직접 raw 행을 삽입해
# 개수를 통제한다(test_surge_universe_pool_bugfix.py 관례 계승). Pool B는
# fetch_volume_leaders_sync만 patch하면 되므로(빈 리스트=raw 0, 코드 리스트=raw N) 별도 DB
# 삽입 없이 patch로 통제한다.

def _make_pool_a_disclosures(db: Session, count: int, prefix: str = "1") -> list[str]:
    """Pool A(DART 공시) raw 후보 `count`건을 DB에 직접 삽입한다."""
    today_str = _date.today().strftime("%Y%m%d")
    codes = [f"{prefix}{i:05d}" for i in range(count)]
    for idx, code in enumerate(codes):
        db.add(
            Disclosure(
                corp_code=f"{idx:08d}",
                corp_name=f"테스트기업A_{idx}",
                stock_code=code,
                report_name="테스트공시(SPEC-AI-076)",
                rcept_no=f"A076{idx:012d}",
                rcept_dt=today_str,
                url=f"https://dart.fss.or.kr/test076/{idx}",
            )
        )
    db.flush()
    return codes


def _make_pool_c_outcomes(db: Session, count: int, prefix: str = "2") -> list[str]:
    """Pool C(당일 등락률 5%+) raw 후보 `count`건을 DB에 직접 삽입한다."""
    today = _date.today()
    codes = [f"{prefix}{i:05d}" for i in range(count)]
    for idx, code in enumerate(codes):
        db.add(
            SurgeActualOutcome(
                trading_date=today,
                stock_code=code,
                stock_name=f"테스트종목C_{idx}",
                change_rate=10.0,
                was_surge=True,
                market="KOSPI",
            )
        )
    db.flush()
    return codes


def _make_pool_b_codes(count: int, prefix: str = "3") -> list[str]:
    """Pool B(거래량200%+) raw 후보 코드 `count`개를 생성한다(DB 삽입 없이 patch로 공급)."""
    return [f"{prefix}{i:05d}" for i in range(count)]


class _PoolBBar:
    """fetch_stock_price_history_sync가 반환하는 PriceRecord를 흉내내는 최소 스텁."""

    def __init__(self, volume: float):
        self.volume = volume


def _pool_b_history_always_passes(_code: str, pages: int = 3) -> list["_PoolBBar"]:
    """모든 Pool B 후보가 ratio=5.0x(>= _min_ratio 2.0)로 통과하는 fake history."""
    return [_PoolBBar(500.0)] + [_PoolBBar(100.0) for _ in range(20)]


class TestQuotaAllocationStarvationFix:
    """SPEC-AI-076 AC-076-001: 07-08형 replay — Pool C 굶주림 교정 (재현 우선, Rule 4).

    Given Pool A raw=232, Pool B raw=0, Pool C raw=52, cap=150,
    pool_c_min_slots=30, pool_b_min_slots=20, existing=∅.
    수정 전: pool_c 대표 수는 정확히 0 (엄격 concat-then-slice가 A만으로 150 상한 소진).
    수정 후: pool_c 대표 수 >= 30, len(final_universe)==150, pool_a 대표 수 <= 120.
    """

    def test_pool_c_represented_after_quota_allocation(self, db: Session):
        _make_pool_a_disclosures(db, 232)
        _make_pool_c_outcomes(db, 52)
        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 20,
                "pool_c_min_slots": 30,
            }
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        pool_c_represented = sum(
            1 for c in final_universe if entry_pool_map.get(c) == "pool_c"
        )
        pool_a_represented = sum(
            1 for c in final_universe if entry_pool_map.get(c) == "pool_a"
        )

        assert pool_c_represented >= 30, (
            f"Pool C 대표 수={pool_c_represented} (기대: >=30) — "
            "07-08형 굶주림 재현/교정 확인 (AC-076-001)"
        )
        assert len(final_universe) == 150
        assert pool_a_represented <= 120


def _pool_b_patches(pool_b_codes: list[str]):
    """Pool B raw 후보를 정확히 `pool_b_codes` 개수로 통제하는 patch 3종을 반환한다.

    fetch_tracked_stock_codes는 fail-open(None)으로 패치해 stocks 교집합 필터를
    우회한다(SPEC-AI-074 REQ-004 계승) — Pool B raw 개수를 순수하게 통제하기 위함.
    """
    return (
        patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=pool_b_codes,
        ),
        patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            side_effect=_pool_b_history_always_passes,
        ),
        patch(
            "app.services.stock_registry_service.fetch_tracked_stock_codes",
            return_value=None,
        ),
    )


class TestQuotaAllocationNonStarvationProperty:
    """SPEC-AI-076 AC-076-002: 비굶주림 일반 속성 (파라미터화).

    각 풀 P ∈ {B, C}에 대해 final_universe의 P 대표 수 >= min(R_p, F_p)이어야 한다
    (상위 풀 크기와 무관하게).
    """

    @pytest.mark.parametrize(
        "r_a, r_b, r_c, f_b, f_c",
        [
            (200, 10, 40, 20, 30),
            (160, 0, 60, 20, 30),
            (300, 25, 25, 20, 30),
        ],
        ids=["A200_B10_C40", "A160_B0_C60", "A300_B25_C25"],
    )
    def test_each_pool_meets_min_floor(
        self, db: Session, r_a: int, r_b: int, r_c: int, f_b: int, f_c: int
    ):
        _make_pool_a_disclosures(db, r_a)
        _make_pool_c_outcomes(db, r_c)
        pool_b_codes = _make_pool_b_codes(r_b)
        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": f_b,
                "pool_c_min_slots": f_c,
            }
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with p1, p2, p3:
            final_universe, entry_pool_map, _pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        b_represented = sum(1 for c in final_universe if entry_pool_map.get(c) == "pool_b")
        c_represented = sum(1 for c in final_universe if entry_pool_map.get(c) == "pool_c")

        assert b_represented >= min(r_b, f_b), (
            f"Pool B 대표 수={b_represented} < min(R_b={r_b}, F_b={f_b})"
        )
        assert c_represented >= min(r_c, f_c), (
            f"Pool C 대표 수={c_represented} < min(R_c={r_c}, F_c={f_c})"
        )
        assert len(final_universe) <= cfg.max_scan_universe


# ---------------------------------------------------------------------------
# AC-076-003 — 비용 상한 보존 + 상수 리터럴 불변
# ---------------------------------------------------------------------------

class TestCostCapPreserved:
    """SPEC-AI-076 AC-076-003: len(final_universe) <= max_scan_universe 항상 성립."""

    @pytest.mark.parametrize(
        "r_a, r_b, r_c",
        [
            (0, 0, 0),  # 절단 압력 없음
            (5, 3, 2),  # 절단 압력 없음(합계 <= 150)
            (232, 0, 52),  # 절단 압력 있음 (07-08형)
            (300, 25, 25),  # 절단 압력 있음
        ],
        ids=["all_zero", "no_pressure", "0708_replay", "heavy_pressure"],
    )
    def test_universe_never_exceeds_cap(self, db: Session, r_a: int, r_b: int, r_c: int):
        _make_pool_a_disclosures(db, r_a)
        _make_pool_c_outcomes(db, r_c)
        pool_b_codes = _make_pool_b_codes(r_b)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 20, "pool_c_min_slots": 30}
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with p1, p2, p3:
            final_universe, _map, _counts = build_scan_universe(db, cfg, existing_codes=set())

        assert len(final_universe) <= cfg.max_scan_universe


class TestInvariantConstantLiteralsUnchanged:
    """SPEC-AI-076 AC-076-003/AC-076-010: max_scan_universe/_min_ratio 상수 리터럴 불변."""

    def test_max_scan_universe_default_unchanged(self):
        """max_scan_universe 기본값은 150 그대로여야 한다(SPEC-AI-065 소유, 상향 금지)."""
        cfg = get_surge_config()
        assert cfg.max_scan_universe == 150

    def test_min_ratio_literal_unchanged_in_source(self):
        """_min_ratio=2.0 리터럴이 변경되면 안 된다(SPEC-AI-074 소유, 불변)."""
        import inspect

        from app.services import surge_detector as _mod

        source = inspect.getsource(_mod.build_scan_universe)
        assert "_min_ratio = 2.0" in source


# ---------------------------------------------------------------------------
# AC-076-004 — 절단 압력 없음: A/B/C 전 후보 포함 + 집합 동등성
# (existing_codes 미포함은 SPEC-AI-076 스캔 범위 밖의 기존 버그 — 그대로 보존, Exclusion 10)
# ---------------------------------------------------------------------------

class TestNoTruncationPressureSetEquivalence:
    """SPEC-AI-076 AC-076-004: 절단 압력 없을 때 A/B/C 합집합 전부 포함, existing은 기존과 동일하게 제외."""

    def test_all_abc_candidates_included_existing_excluded(self, db: Session):
        pool_a_codes = _make_pool_a_disclosures(db, 10)
        pool_c_codes = _make_pool_c_outcomes(db, 12)
        pool_b_codes = _make_pool_b_codes(8)
        existing_codes = {f"9{i:05d}" for i in range(5)}

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 20, "pool_c_min_slots": 30}
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with p1, p2, p3:
            final_universe, entry_pool_map, _counts = build_scan_universe(
                db, cfg, existing_codes=existing_codes
            )

        expected_abc_union = set(pool_a_codes) | set(pool_b_codes) | set(pool_c_codes)
        final_set = set(final_universe)

        assert final_set == expected_abc_union, (
            "A/B/C 3개 소스의 합집합(30개)이 final_universe 집합과 정확히 일치해야 한다"
        )
        assert len(final_set) == 30
        assert not (final_set & existing_codes), (
            "existing 5개는 현행(pre-existing) 버그와 동일하게 포함되지 않아야 한다 "
            "(SPEC-AI-076 Exclusion 10, 별도 후속 SPEC 범위)"
        )
        for code in pool_a_codes:
            assert entry_pool_map.get(code) == "pool_a"
        for code in pool_b_codes:
            assert entry_pool_map.get(code) == "pool_b"
        for code in pool_c_codes:
            assert entry_pool_map.get(code) == "pool_c"


# ---------------------------------------------------------------------------
# AC-076-005 — floors=0 레거시 동등성 (백워드 호환 탈출구)
# ---------------------------------------------------------------------------

class TestLegacyEquivalenceWhenFloorsZero:
    """SPEC-AI-076 AC-076-005: floors=0이면 기존 엄격 concat-then-slice와 정확히 동일."""

    def test_floors_zero_matches_legacy_concat_then_slice_exactly(self, db: Session):
        pool_a_codes = _make_pool_a_disclosures(db, 232)
        pool_c_codes = _make_pool_c_outcomes(db, 52)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        # 레거시 엄격 concat-then-slice를 직접 재현(existing 필터는 기존 버그로 항상 빈 리스트)
        legacy_ordered = pool_a_codes + [] + pool_c_codes
        seen: set[str] = set()
        legacy_dedup: list[str] = []
        for code in legacy_ordered:
            if code not in seen:
                seen.add(code)
                legacy_dedup.append(code)
        legacy_final = legacy_dedup[:150]

        assert final_universe == legacy_final, (
            "floors=0(pool_b_min_slots=pool_c_min_slots=0)이면 quota 배분이 기존 엄격 "
            "concat-then-slice와 순서까지 정확히 동일한 결과를 내야 한다(AC-076-005)"
        )
        # 사실상 pool_a[:150] — Pool C 대표는 0 (레거시 굶주림 버그 그대로 재현)
        assert legacy_final == pool_a_codes[:150]


# ---------------------------------------------------------------------------
# AC-076-006 — post-truncation 관측성 (스키마 0)
# ---------------------------------------------------------------------------

class TestPostTruncationObservability:
    """SPEC-AI-076 AC-076-006: pool_counts에 raw 보존 + scanned 신규 키 + 로그 관측성."""

    def test_pool_counts_raw_preserved_and_scanned_keys_added(self, db: Session, caplog):
        _make_pool_a_disclosures(db, 232)
        _make_pool_c_outcomes(db, 52)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 20, "pool_c_min_slots": 30}
        )

        with (
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=[],
            ),
            caplog.at_level(logging.INFO, logger="app.services.surge_detector"),
        ):
            final_universe, _map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert pool_counts["pool_a"] == 232
        assert pool_counts["pool_b"] == 0
        assert pool_counts["pool_c"] == 52

        assert pool_counts["pool_a_scanned"] == 120
        assert pool_counts["pool_b_scanned"] == 0
        assert pool_counts["pool_c_scanned"] == 30
        assert (
            pool_counts["pool_a_scanned"]
            + pool_counts["pool_b_scanned"]
            + pool_counts["pool_c_scanned"]
            == len(final_universe)
            == 150
        )

        assert any(
            "scanned" in record.message and "raw" in record.message
            for record in caplog.records
        ), "최종 로그 라인에 raw 대비 scanned가 함께 출력되어야 한다"


# ---------------------------------------------------------------------------
# AC-076-007 — SurgeUniversePoolHistory raw 의미 불변 (회귀 가드)
# ---------------------------------------------------------------------------

class TestSurgeUniversePoolHistoryRawSemanticsPreserved:
    """SPEC-AI-076 AC-076-007: scanned 키가 반환 dict에 있어도 persist에는 raw만 전달된다."""

    def test_persist_call_site_extracts_only_raw_keys(self, db: Session):
        from datetime import date as _dt

        from app.services.surge_universe_pool_service import (
            get_pool_counts_for_date,
            persist_pool_counts,
        )

        _make_pool_a_disclosures(db, 232)
        _make_pool_c_outcomes(db, 52)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 20, "pool_c_min_slots": 30}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            universe_codes, _map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert {"pool_a_scanned", "pool_b_scanned", "pool_c_scanned"} <= pool_counts.keys()

        # surge_detector.py:~1953 persist_pool_counts 호출부 로직을 그대로 재현
        # (raw 키만 .get()으로 명시 추출 — scanned 키는 전달되지 않음)
        persisted_payload = {
            "pool_a": pool_counts.get("pool_a", 0),
            "pool_b": pool_counts.get("pool_b", 0),
            "pool_c": pool_counts.get("pool_c", 0),
            "scan_universe_size": len(universe_codes),
        }
        assert persisted_payload["pool_c"] == 52, (
            "raw(52)가 유지되어야 한다 — scanned(30)로 오염되면 회귀"
        )

        persist_pool_counts(db, _dt.today(), persisted_payload)
        db.commit()
        loaded = get_pool_counts_for_date(db, _dt.today())
        assert loaded["pool_c"] == 52, (
            "SurgeUniversePoolHistory.pool_c_count는 raw pre-truncation 값(52)으로 "
            "유지되어야 하며 scanned 값(30)으로 대체되면 안 된다"
        )


# ---------------------------------------------------------------------------
# AC-076-008 — floor 설정 로딩 + 안전 clamp
# ---------------------------------------------------------------------------

class TestFloorConfigSafetyClamp:
    """SPEC-AI-076 AC-076-008: sum(floors) > cap인 오설정도 예외 없이 안전 축소된다."""

    def test_misconfigured_floors_sum_exceeds_cap_clamps_safely(self, db: Session, caplog):
        _make_pool_a_disclosures(db, 50)
        pool_c_codes = _make_pool_c_outcomes(db, 120)
        pool_b_codes = _make_pool_b_codes(120)
        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 100,
                "pool_c_min_slots": 100,
            }
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with (
            p1, p2, p3,
            caplog.at_level(logging.WARNING, logger="app.services.surge_detector"),
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) <= 150
        assert any(
            "축소" in record.message or "clamp" in record.message.lower()
            for record in caplog.records
        ), "오설정 시 경고 로그가 남아야 한다"

        # 정상 설정(합 <= cap)에서는 floor가 설정값 그대로 적용됨을 별도 확인(AC-076-001로 커버)
        assert len(pool_c_codes) == 120  # 픽스처 생성 확인용(사용 안 하면 lint 경고)


# ---------------------------------------------------------------------------
# SPEC-AI-078 — Pool A impact_score 기반 우선순위 절단 교정
# ---------------------------------------------------------------------------

def _make_pool_a_disclosures_with_impact(
    db: Session,
    codes_and_impacts: list[tuple[str, float | None]],
    prefix: str = "0",
) -> list[str]:
    """Pool A(DART 공시) raw 후보를 `impact_score`를 지정하여 DB 삽입 순서대로 생성한다.

    `codes_and_impacts`에 준 순서 그대로 DB에 삽입되므로, ORDER BY가 없는 현행(레거시)
    쿼리의 반환 순서를 결정론적으로 재현할 수 있다(SPEC-AI-078 REQ-006 재현 우선 테스트용).
    """
    codes: list[str] = []
    for idx, (code, impact) in enumerate(codes_and_impacts):
        db.add(
            Disclosure(
                corp_code=f"{prefix}{idx:07d}",
                corp_name=f"테스트기업078_{idx}",
                stock_code=code,
                report_name="테스트공시(SPEC-AI-078)",
                rcept_no=f"A078{prefix}{idx:010d}",
                rcept_dt=_date.today().strftime("%Y%m%d"),
                url=f"https://dart.fss.or.kr/test078/{prefix}/{idx}",
                impact_score=impact,
            )
        )
        codes.append(code)
    db.flush()
    return codes


class TestImpactRankedPoolATruncation:
    """SPEC-AI-078: Pool A raw > 실질 슬롯일 때 impact_score 내림차순 우선 잔존.

    2026-07-08 라이브 재현: 058730(다스코, impact_score=20)이 저impact/무순위(NULL) 공시
    150건 뒤(DB 반환 순서상)에 위치 → 현행(수정 전) 무순위 절단으로 final_universe에서
    누락된다(research.md 실증 사례). max_scan_universe=150, Pool B/C 압박 없음(quota=0)으로
    Pool A 풀-내부(intra-pool) 절단만 순수하게 재현한다.
    """

    def test_characterize_high_impact_disclosure_missing_before_fix(self, db: Session):
        """RED(수정 전 재현): 고impact 종목이 저impact 150건 뒤에 위치하면 절단으로 누락된다."""
        filler_codes = [(f"5{i:05d}", None) for i in range(150)]  # 무순위(NULL) 저impact 150건
        high_impact_code = "058730"
        codes_and_impacts = filler_codes + [(high_impact_code, 20.0)]  # 고impact가 맨 뒤(DB 반환 순서상)
        _make_pool_a_disclosures_with_impact(db, codes_and_impacts)

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, _pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 150
        assert high_impact_code in final_universe, (
            f"impact 우선순위 정렬 적용 후에는 고impact(20) 종목 {high_impact_code}이 "
            "저impact/무순위 150건보다 우선 잔존해야 한다(REQ-AI078-001, 058730형 사례). "
            "이 assert가 실패한다면 아직 정렬이 적용되지 않은 것이다."
        )

    def test_null_impact_disclosures_deprioritized_not_excluded(self, db: Session):
        """REQ-AI078-002: NULL(미스코어링) 공시는 최우선이 아닌 최후순위로 밀리되 배제되지 않는다."""
        # NULL 15건을 먼저 삽입(DB 반환 순서상 앞쪽) + 낮은 impact 1건을 맨 뒤에 삽입
        null_codes = [(f"6{i:05d}", None) for i in range(15)]
        low_impact_code = "060001"
        codes_and_impacts = null_codes + [(low_impact_code, 1.0)]
        _make_pool_a_disclosures_with_impact(db, codes_and_impacts)

        # 실질 슬롯을 1개만 남기도록 max_scan_universe=1로 강하게 좁힌다 — 16건 중 단 1건만
        # 잔존 가능하므로 NULLS FIRST 역효과가 있으면 즉시 드러난다.
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 1, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 1
        # NULLS FIRST 역효과가 없어야 한다: low_impact_code(1.0)가 NULL 15건보다 우선 잔존
        assert low_impact_code in final_universe, (
            "NULL 공시가 스코어링된 공시(impact=1.0)보다 우선 잔존하면 NULLS FIRST 역효과 "
            "(REQ-AI078-002 위반)"
        )

    def test_null_impact_disclosures_still_included_when_no_pressure(self, db: Session):
        """REQ-AI078-002: 절단 압력이 없으면 NULL 공시도 완전 배제되지 않고 포함된다."""
        codes_and_impacts = [(f"7{i:05d}", None) for i in range(5)] + [("070006", 20.0)]
        codes = _make_pool_a_disclosures_with_impact(db, codes_and_impacts)

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert set(codes) <= set(final_universe), (
            "절단 압력이 없으면 NULL 공시를 포함한 모든 Pool A 후보가 유니버스에 남아야 한다"
        )

    def test_stock_represented_by_max_impact_across_multiple_disclosures(self, db: Session):
        """REQ-AI078-003: 같은 종목의 복수 공시는 최고(MAX) impact_score로 대표된다."""
        target_code = "080001"
        # target_code가 낮은 impact(1.0) 공시를 먼저 내고, 나중에 높은 impact(20.0) 공시를 낸다.
        # 저impact 필러 149건을 사이에 끼워 넣어 절단 압력을 만든다.
        codes_and_impacts: list[tuple[str, float | None]] = [(target_code, 1.0)]
        codes_and_impacts += [(f"8{i:05d}", 5.0) for i in range(1, 150)]  # 149건, impact=5.0
        codes_and_impacts.append((target_code, 20.0))  # target_code의 두 번째(고impact) 공시
        _make_pool_a_disclosures_with_impact(db, codes_and_impacts)

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        # target_code는 자신의 최고 impact(20.0)로 대표되어 impact=5.0인 149건보다 우선 잔존해야 한다.
        assert target_code in final_universe, (
            "종목별 MAX(impact_score) 대표 집계가 없으면 target_code가 impact=5.0 149건에 밀려 "
            "누락될 수 있다(REQ-AI078-003)"
        )

    def test_toggle_off_matches_legacy_db_order_exactly(self, db: Session):
        """REQ-AI078-005(a): `pool_a_rank_by_impact=False`면 레거시 DB-순서 거동과 정확히 동일."""
        filler_codes = [(f"9{i:05d}", None) for i in range(150)]
        high_impact_code = "090730"
        codes_and_impacts = filler_codes + [(high_impact_code, 20.0)]
        _make_pool_a_disclosures_with_impact(db, codes_and_impacts, prefix="t")

        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 0,
                "pool_c_min_slots": 0,
                "pool_a_rank_by_impact": False,
            }
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 150
        assert high_impact_code not in final_universe, (
            "토글 비활성 시 정렬 미적용 레거시 거동과 동일해야 하므로, RED 테스트와 동일하게 "
            "고impact 종목이 여전히 절단되어야 한다(REQ-AI078-005 백워드 호환)"
        )

    def test_no_truncation_pressure_result_set_unchanged_by_sort_toggle(self, db: Session):
        """REQ-AI078-005(b): 절단 압력이 없으면 정렬 토글 여부와 무관하게 결과 집합이 동일하다."""
        codes_and_impacts = [
            ("a10001", 20.0), ("a10002", None), ("a10003", 5.0), ("a10004", None), ("a10005", 1.0),
        ]
        codes = _make_pool_a_disclosures_with_impact(db, codes_and_impacts, prefix="z")

        results: dict[bool, set[str]] = {}
        for toggle in (True, False):
            cfg = get_surge_config().model_copy(
                update={
                    "max_scan_universe": 150,
                    "pool_b_min_slots": 0,
                    "pool_c_min_slots": 0,
                    "pool_a_rank_by_impact": toggle,
                }
            )
            with patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=[],
            ):
                final_universe, _map, _counts = build_scan_universe(
                    db, cfg, existing_codes=set()
                )
            results[toggle] = set(final_universe)

        assert results[True] == results[False] == set(codes), (
            "절단 압력이 없으면 토글 ON/OFF 모두 동일한 결과 집합을 내야 한다(REQ-AI078-005)"
        )

    def test_pool_a_raw_count_unaffected_by_sort(self, db: Session):
        """REQ-AI078-004: 정렬은 리스트 순서만 바꾸고 pool_counts['pool_a'](raw) 길이는 불변."""
        filler_codes = [(f"c{i:05d}", None) for i in range(150)]
        codes_and_impacts = filler_codes + [("c99999", 20.0)]
        _make_pool_a_disclosures_with_impact(db, codes_and_impacts, prefix="q")

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            _final_universe, _map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert pool_counts["pool_a"] == 151, (
            "pool_counts['pool_a']는 절단 전 raw 공급 수(151)여야 한다 — 정렬 도입으로 "
            "길이가 바뀌면 SPEC-AI-065 REQ-5 raw 카운트 계약 위반(REQ-AI078-004)"
        )
