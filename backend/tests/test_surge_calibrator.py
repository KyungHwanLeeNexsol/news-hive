"""SPEC-AI-036: surge_calibrator.py 테스트.

AC-1~AC-6 coverage:
  AC-1: PAV 단조성
  AC-2: 출력 [0.0, 1.0] 클램프
  AC-3: 샘플 < 50 → identity fallback
  AC-4: positive ratio 100% → 캘리브레이션 스킵
  AC-5: pickle save/load 왕복
  AC-6: 손상 pickle → identity fallback, 예외 전파 없음
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from app.services.surge_calibrator import (
    IsotonicModel,
    _run_pav,
    calibrate_confidence,
    load_calibrator,
    save_calibrator,
    train_isotonic,
)


# ---------------------------------------------------------------------------
# _run_pav 단위 테스트
# ---------------------------------------------------------------------------

class TestRunPav:
    def test_empty_returns_empty(self):
        assert _run_pav([]) == []

    def test_single_pair(self):
        result = _run_pav([(0.5, 1.0)])
        assert len(result) == 1
        assert result[0] == (0.5, 1.0)

    def test_already_monotone(self):
        pairs = [(0.1, 0.2), (0.3, 0.4), (0.6, 0.8)]
        result = _run_pav(pairs)
        # 단조 증가 유지
        probs = [r[1] for r in result]
        for i in range(len(probs) - 1):
            assert probs[i] <= probs[i + 1], f"단조 위반: {probs}"

    def test_violation_is_merged(self):
        # 역순 배열 → 하나의 블록으로 병합
        pairs = [(0.1, 1.0), (0.5, 0.0)]
        result = _run_pav(pairs)
        # 전체 평균 0.5 블록 하나
        assert len(result) == 1
        assert abs(result[0][1] - 0.5) < 1e-9

    def test_multiple_violations(self):
        pairs = [(0.1, 0.8), (0.3, 0.2), (0.5, 0.9), (0.7, 0.1)]
        result = _run_pav(pairs)
        probs = [r[1] for r in result]
        for i in range(len(probs) - 1):
            assert probs[i] <= probs[i + 1]


# ---------------------------------------------------------------------------
# IsotonicModel.predict 단위 테스트
# ---------------------------------------------------------------------------

class TestIsotonicModelPredict:
    def test_identity_returns_raw(self):
        model = IsotonicModel(is_identity=True)
        assert model.predict(0.4) == pytest.approx(0.4)

    def test_identity_clamps_to_0_1(self):
        model = IsotonicModel(is_identity=True)
        assert model.predict(-0.5) == pytest.approx(0.0)
        assert model.predict(1.5) == pytest.approx(1.0)

    def test_empty_breakpoints_identity(self):
        model = IsotonicModel(breakpoints=[])
        assert model.predict(0.5) == pytest.approx(0.5)

    def test_below_range_clamps(self):
        model = IsotonicModel(breakpoints=[(0.3, 0.2), (0.7, 0.6)])
        result = model.predict(0.1)
        assert result == pytest.approx(0.2)

    def test_above_range_clamps(self):
        model = IsotonicModel(breakpoints=[(0.3, 0.2), (0.7, 0.6)])
        result = model.predict(0.9)
        assert result == pytest.approx(0.6)

    def test_interpolation(self):
        model = IsotonicModel(breakpoints=[(0.0, 0.0), (1.0, 1.0)])
        assert model.predict(0.5) == pytest.approx(0.5)
        assert model.predict(0.25) == pytest.approx(0.25)

    def test_output_clamped_to_0_1(self):
        """AC-2: 출력값은 반드시 [0.0, 1.0] 이내."""
        model = IsotonicModel(breakpoints=[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
        for raw in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            result = model.predict(raw)
            assert 0.0 <= result <= 1.0, f"범위 이탈: predict({raw})={result}"


# ---------------------------------------------------------------------------
# train_isotonic 테스트
# ---------------------------------------------------------------------------

class TestTrainIsotonic:
    def test_insufficient_samples_returns_identity(self):
        """AC-3: 샘플 < 50 → identity fallback."""
        pairs = [(0.3, 1), (0.6, 0)] * 10  # 20개
        model = train_isotonic(pairs, min_calibration_samples=50)
        assert model.is_identity is True
        # identity 모델: predict(raw) = raw
        assert model.predict(0.4) == pytest.approx(0.4)

    def test_all_positive_returns_identity(self):
        """AC-4: positive ratio 100% → 캘리브레이션 스킵."""
        pairs = [(float(i) / 100, 1) for i in range(50)]
        model = train_isotonic(pairs, min_calibration_samples=50)
        assert model.is_identity is True

    def test_all_negative_returns_identity(self):
        """AC-4: positive ratio 0% → 캘리브레이션 스킵."""
        pairs = [(float(i) / 100, 0) for i in range(50)]
        model = train_isotonic(pairs, min_calibration_samples=50)
        assert model.is_identity is True

    def test_sufficient_samples_trains(self):
        """충분한 샘플 → is_identity=False."""
        # 0.0~0.49: 틀림, 0.5~0.99: 맞음 → 단조 증가 캘리브레이션
        pairs = [(float(i) / 100, 0) for i in range(50)]
        pairs += [(0.5 + float(i) / 100, 1) for i in range(50)]
        model = train_isotonic(pairs, min_calibration_samples=50)
        assert model.is_identity is False
        assert len(model.breakpoints) > 0

    def test_monotonicity_property(self):
        """AC-1: PAV 단조성 — raw_a <= raw_b → predict(raw_a) <= predict(raw_b)."""
        import random
        random.seed(42)
        n = 100
        pairs = [(random.random(), random.randint(0, 1)) for _ in range(n)]
        # positive ratio 보장
        pairs[:20] = [(float(i) / 100, 1) for i in range(20)]
        pairs[20:40] = [(0.4 + float(i) / 100, 0) for i in range(20)]

        model = train_isotonic(pairs, min_calibration_samples=50)

        test_points = [i / 20.0 for i in range(21)]
        preds = [model.predict(p) for p in test_points]
        for i in range(len(preds) - 1):
            assert preds[i] <= preds[i + 1] + 1e-9, (
                f"단조 위반: predict({test_points[i]:.2f})={preds[i]:.4f} "
                f"> predict({test_points[i+1]:.2f})={preds[i+1]:.4f}"
            )

    def test_metadata_stored(self):
        """학습 완료 시 trained_at, sample_count 기록."""
        pairs = [(float(i) / 100, i % 2) for i in range(60)]
        model = train_isotonic(pairs, min_calibration_samples=50)
        assert model.sample_count == 60
        assert model.trained_at != ""


# ---------------------------------------------------------------------------
# save/load 왕복 테스트
# ---------------------------------------------------------------------------

class TestPickleRoundTrip:
    def test_save_load_roundtrip(self, tmp_path: Path):
        """AC-5: pickle save/load 왕복 후 동일 예측값."""
        pairs = [(float(i) / 100, i % 2) for i in range(80)]
        model = train_isotonic(pairs, min_calibration_samples=50)

        pkl_path = tmp_path / "calibrator.pkl"
        save_calibrator(model, path=pkl_path)

        loaded = load_calibrator(path=pkl_path)
        assert not loaded.is_identity

        for raw in [0.1, 0.3, 0.5, 0.7, 0.9]:
            assert model.predict(raw) == pytest.approx(loaded.predict(raw), abs=1e-9)

    def test_corrupted_pickle_returns_identity(self, tmp_path: Path):
        """AC-6: 손상 pickle → identity fallback, 예외 전파 없음."""
        pkl_path = tmp_path / "bad.pkl"
        pkl_path.write_bytes(b"not-valid-pickle-data-xyz")

        model = load_calibrator(path=pkl_path)
        assert model.is_identity is True
        # 예외 없이 identity 동작
        assert model.predict(0.6) == pytest.approx(0.6)

    def test_missing_file_returns_identity(self, tmp_path: Path):
        """파일 없음 → identity fallback."""
        pkl_path = tmp_path / "nonexistent.pkl"
        model = load_calibrator(path=pkl_path)
        assert model.is_identity is True

    def test_wrong_type_in_pickle_returns_identity(self, tmp_path: Path):
        """잘못된 타입 → identity fallback, 예외 없음."""
        pkl_path = tmp_path / "wrong_type.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump({"not": "an IsotonicModel"}, f)

        model = load_calibrator(path=pkl_path)
        assert model.is_identity is True


# ---------------------------------------------------------------------------
# calibrate_confidence 함수 테스트
# ---------------------------------------------------------------------------

class TestCalibrateConfidence:
    def test_returns_float_in_range(self):
        """calibrate_confidence 항상 [0.0, 1.0] 반환."""
        # 글로벌 _calibrator 초기화 리셋은 별도 하지 않음 (identity fallback 경로)
        for raw in [0.0, 0.2, 0.5, 0.8, 1.0]:
            result = calibrate_confidence(raw)
            assert 0.0 <= result <= 1.0

    def test_identity_passthrough(self):
        """identity 모델 상태에서 raw == calibrated."""
        # load_calibrator는 파일 없으면 identity 반환
        # calibrate_confidence는 내부적으로 get_calibrator() 호출
        # 파일 없는 환경에서 identity fallback 확인
        raw = 0.42
        result = calibrate_confidence(raw)
        # identity이면 raw 그대로
        assert result == pytest.approx(raw, abs=0.01)
