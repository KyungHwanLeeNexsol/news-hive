"""SPEC-AI-107: 급등예측 confidence 캘리브레이터 — 섀도우 학습 배선 테스트.

AC-107-001~011 coverage:
  AC-107-001: 시간순 분할로 candidate 아티팩트 생성
  AC-107-002: active pkl / in-process 싱글턴 무변경
  AC-107-003: 실행 로그 필수 필드 append
  AC-107-004: 데이터 부족 시 Brier/candidate 저장 건너뜀
  AC-107-005: 신규 DB 테이블/마이그레이션 0개 (코드 리뷰로 확인 — 이 파일 범위 아님)
  AC-107-006: 섀도우 학습 예외가 스케줄러의 다른 잡에 전파되지 않음
  AC-107-007: train_isotonic() 기존 호출부 무회귀 + min_positive_samples identity
  AC-107-008: 섀도우 학습 잡이 매주 정확히 1회 등록
  AC-107-009: 표본 수 floor가 설정 가능한 값에서 옴
  AC-107-010: 프로모션/롤백 절차 plan.md §C 문서화 (grep 기반 — 이 파일 범위 아님)
  AC-107-011: resolved 표본 수 floor가 train_isotonic()에 실제로 전달됨
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.signal_verifier import get_surge_calibration_pairs_with_time
from app.services.surge_calibrator import (
    ShadowTrainingRun,
    compute_brier_score,
    get_calibrator,
    promote_candidate,
    run_shadow_training,
    split_walk_forward,
    train_isotonic,
)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def make_stock(db: Session):
    """Sector + Stock 팩토리."""
    def _factory(stock_code: str = "AI107T") -> Stock:
        sector = Sector(name=f"섹터{stock_code}")
        db.add(sector)
        db.flush()
        stock = Stock(
            name=f"테스트종목{stock_code}",
            stock_code=stock_code,
            sector_id=sector.id,
            market_cap=100,
        )
        db.add(stock)
        db.flush()
        return stock
    return _factory


def _insert_signals(
    db: Session,
    stock: Stock,
    n_total: int,
    n_positive: int,
    days_span: int = 85,
) -> None:
    """검증 완료 surge_candidate 시그널 n_total개(양성 n_positive개)를 시간순으로 삽입한다.

    days_span은 lookback_days(기본 90)보다 여유 있게 작아야 한다 — 가장 오래된
    레코드의 created_at이 삽입 시점 기준이고, get_surge_calibration_pairs_with_time의
    cutoff는 그보다 나중(조회 시점) 기준으로 계산되므로 경계에 딱 걸치면 미세한
    시간차로 필터링될 수 있다.
    """
    now = datetime.now(timezone.utc)
    for i in range(n_total):
        is_correct = i < n_positive
        created_at = now - timedelta(days=days_span - (i * days_span / max(n_total, 1)))
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.30 + (0.6 * i / max(n_total, 1)),
                reasoning="test",
                is_correct=is_correct,
                verified_at=now,
                created_at=created_at,
            )
        )
    db.flush()


# ---------------------------------------------------------------------------
# AC-107-001 / split_walk_forward
# ---------------------------------------------------------------------------

class TestSplitWalkForward:
    def test_time_ordered_split_not_random(self):
        """created_at 기준 시간순 분할 — 무작위 셔플이 아님."""
        now = datetime.now(timezone.utc)
        triples = [
            (0.9, 1, now - timedelta(days=1)),  # 가장 최근
            (0.1, 0, now - timedelta(days=10)),  # 가장 오래됨
            (0.5, 1, now - timedelta(days=5)),
        ]
        training, holdout = split_walk_forward(triples, holdout_fraction=0.34)

        # holdout_count = int(3 * 0.34) = 1 → 가장 최근 1건이 holdout
        assert len(holdout) == 1
        assert holdout[0] == (0.9, 1)
        assert len(training) == 2

    def test_holdout_fraction_zero_count_yields_empty_holdout(self):
        """표본이 매우 적으면 holdout이 0개가 될 수 있다."""
        now = datetime.now(timezone.utc)
        triples = [(0.5, 1, now)]
        training, holdout = split_walk_forward(triples, holdout_fraction=0.3)
        assert holdout == []
        assert len(training) == 1


# ---------------------------------------------------------------------------
# compute_brier_score
# ---------------------------------------------------------------------------

class TestComputeBrierScore:
    def test_perfect_prediction_zero_score(self):
        assert compute_brier_score([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)

    def test_worst_prediction_max_score(self):
        assert compute_brier_score([(0.0, 1), (1.0, 0)]) == pytest.approx(1.0)

    def test_mixed_predictions(self):
        pairs = [(0.5, 1), (0.5, 0)]
        assert compute_brier_score(pairs) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# AC-107-007: train_isotonic min_positive_samples
# ---------------------------------------------------------------------------

class TestTrainIsotonicMinPositiveSamples:
    def test_omitted_argument_is_byte_identical(self):
        """min_positive_samples 생략 시 기존 동작과 완전히 동일하다."""
        pairs = [(float(i) / 100, 0) for i in range(50)]
        pairs += [(0.5 + float(i) / 100, 1) for i in range(50)]

        model_without_arg = train_isotonic(pairs, min_calibration_samples=50)
        model_with_none = train_isotonic(
            pairs, min_calibration_samples=50, min_positive_samples=None
        )

        assert model_without_arg.is_identity == model_with_none.is_identity
        assert model_without_arg.breakpoints == model_with_none.breakpoints

    def test_explicit_min_positive_samples_below_floor_returns_identity(self):
        """positive 표본 수가 min_positive_samples 미만이면 identity fallback."""
        # 표본 60개, positive 5개(<15)
        pairs = [(float(i) / 100, 0) for i in range(55)]
        pairs += [(0.9 + float(i) / 1000, 1) for i in range(5)]

        model = train_isotonic(pairs, min_calibration_samples=50, min_positive_samples=15)
        assert model.is_identity is True

    def test_explicit_min_positive_samples_satisfied_trains(self):
        """positive 표본 수가 min_positive_samples 이상이면 정상 학습된다."""
        pairs = [(float(i) / 100, 0) for i in range(35)]
        pairs += [(0.5 + float(i) / 100, 1) for i in range(20)]

        model = train_isotonic(pairs, min_calibration_samples=50, min_positive_samples=15)
        assert model.is_identity is False


# ---------------------------------------------------------------------------
# AC-107-001, AC-107-002, AC-107-003, AC-107-004: run_shadow_training
# ---------------------------------------------------------------------------

class TestRunShadowTraining:
    def test_sufficient_data_creates_candidate_and_logs(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-001/003: 충분한 데이터 → candidate 아티팩트 생성 + 실행 로그 append."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=80, n_positive=20)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
        ):
            run = run_shadow_training(
                db, min_calibration_samples=50, min_positive_samples=15
            )

        assert run.sufficient_data is True
        assert run.sample_count == 80
        assert run.positive_count == 20
        assert run.candidate_path is not None
        assert Path(run.candidate_path).exists()

        assert run_log_path.exists()
        lines = run_log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        logged = json.loads(lines[0])
        for field_name in (
            "run_date", "sample_count", "positive_count", "sufficient_data", "gate_passed",
        ):
            assert field_name in logged

    def test_two_consecutive_runs_append_not_overwrite(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-003: 2회 연속 실행 시 로그가 +2줄 된다 (덮어쓰지 않음)."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=80, n_positive=20)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
        ):
            run_shadow_training(db, min_calibration_samples=50, min_positive_samples=15)
            run_shadow_training(db, min_calibration_samples=50, min_positive_samples=15)

        lines = run_log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_active_pkl_and_singleton_unchanged(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-002: 섀도우 학습이 active pkl과 in-process 싱글턴을 변경하지 않는다."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=80, n_positive=20)

        active_path = tmp_path / "surge_calibrator.pkl"
        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        # active pkl 부재 상태 해시(부재 자체를 기록) + 싱글턴 id 기록
        assert not active_path.exists()
        singleton_before = id(get_calibrator())

        with (
            patch("app.services.surge_calibrator._CALIBRATOR_PATH", active_path),
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
        ):
            run_shadow_training(db, min_calibration_samples=50, min_positive_samples=15)

        assert not active_path.exists(), "active pkl이 섀도우 학습 중 생성/변경되면 안 된다"
        assert id(get_calibrator()) == singleton_before

    def test_empty_holdout_edge_case_absorbed_into_insufficient_path(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """Edge case (acceptance.md): floor/positive는 충족하나 holdout_fraction이
        지나치게 작아 holdout이 0개가 되는 극단적 경계는 데이터 부족 경로로
        흡수되어야 한다 (compute_brier_score([])의 ZeroDivisionError 방지)."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=50, n_positive=20)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
        ):
            # holdout_fraction=0.01 → int(50 * 0.01) == 0 → holdout_set == []
            run = run_shadow_training(
                db,
                min_calibration_samples=50,
                min_positive_samples=15,
                holdout_fraction=0.01,
            )

        assert run.sufficient_data is False
        assert run.candidate_path is None
        assert not candidate_dir.exists() or not any(candidate_dir.glob("*.pkl"))

    def test_insufficient_sample_count_skips_training(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-004(a): 표본 수 49개(floor=50 미만) → 데이터 부족 경로."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=49, n_positive=20)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
        ):
            run = run_shadow_training(
                db, min_calibration_samples=50, min_positive_samples=15
            )

        assert run.sufficient_data is False
        assert run.candidate_path is None
        assert not candidate_dir.exists() or not any(candidate_dir.glob("*.pkl"))

    def test_insufficient_positive_count_skips_training(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-004(b): 표본 60개(floor 이상)이나 positive 3개(floor=15 미만) → 데이터 부족."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=60, n_positive=3)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
        ):
            run = run_shadow_training(
                db, min_calibration_samples=50, min_positive_samples=15
            )

        assert run.sufficient_data is False
        assert run.candidate_path is None
        assert not candidate_dir.exists() or not any(candidate_dir.glob("*.pkl"))


# ---------------------------------------------------------------------------
# AC-107-009 / AC-107-011: 표본 수 floor 해석 + train_isotonic 전달 확인
# ---------------------------------------------------------------------------

class TestFloorResolution:
    def test_none_uses_surge_config_min_calibration_samples(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-009: min_calibration_samples 인자 없으면 설정값을 floor로 사용."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=35, n_positive=20)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        mock_config = MagicMock()
        mock_config.min_calibration_samples = 30

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
            patch(
                "app.surge_config.surge_settings.get_surge_config",
                return_value=mock_config,
            ),
        ):
            # 기본값(50) 기준으로는 35 < 50이라 부족하지만, monkeypatch된 30
            # 기준으로는 35 >= 30이라 충분 경계를 통과해야 한다.
            run = run_shadow_training(db, min_positive_samples=15)

        assert run.sample_count == 35
        assert run.sufficient_data is True

    def test_resolved_floor_passed_to_train_isotonic_not_internal_default(
        self, db: Session, make_stock, tmp_path: Path
    ) -> None:
        """AC-107-011: resolve된 min_calibration_samples가 train_isotonic()에
        키워드 인자로 그대로 전달되어야 한다 — train_isotonic() 자체의 독립
        기본값(50)에 암묵적으로 의존하면 안 된다."""
        stock = make_stock()
        _insert_signals(db, stock, n_total=80, n_positive=20)

        candidate_dir = tmp_path / "surge_calibrator"
        run_log_path = candidate_dir / "runs.jsonl"

        mock_config = MagicMock()
        mock_config.min_calibration_samples = 37  # train_isotonic 기본값(50)과 다른 값

        from app.services import surge_calibrator as calibrator_module

        spy = MagicMock(wraps=calibrator_module.train_isotonic)

        with (
            patch("app.services.surge_calibrator._CANDIDATE_DIR", candidate_dir),
            patch("app.services.surge_calibrator._RUN_LOG_PATH", run_log_path),
            patch(
                "app.surge_config.surge_settings.get_surge_config",
                return_value=mock_config,
            ),
            patch("app.services.surge_calibrator.train_isotonic", spy),
        ):
            run_shadow_training(db, min_positive_samples=15)

        spy.assert_called_once()
        _, kwargs = spy.call_args
        assert kwargs["min_calibration_samples"] == 37, (
            f"train_isotonic()에 전달된 min_calibration_samples가 37이 아님 "
            f"(50이면 train_isotonic()의 자체 기본값이 조용히 사용된 결함): {kwargs}"
        )
        assert kwargs["min_positive_samples"] == 15


# ---------------------------------------------------------------------------
# get_surge_calibration_pairs_with_time (TASK-001)
# ---------------------------------------------------------------------------

class TestGetSurgeCalibrationPairsWithTime:
    def test_returns_triples_with_created_at(self, db: Session, make_stock) -> None:
        stock = make_stock()
        now = datetime.now(timezone.utc)
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.55,
                reasoning="test",
                is_correct=True,
                verified_at=now,
                created_at=now,
            )
        )
        db.flush()

        triples = get_surge_calibration_pairs_with_time(db, lookback_days=90)

        assert len(triples) == 1
        raw, is_correct, created_at = triples[0]
        assert abs(raw - 0.55) < 1e-9
        assert is_correct == 1
        assert created_at is not None

    def test_same_filters_as_existing_function(self, db: Session, make_stock) -> None:
        """기존 get_surge_calibration_pairs()와 동일한 필터(미검증/다른 signal_type 제외)."""
        stock = make_stock()
        now = datetime.now(timezone.utc)

        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.40,
                reasoning="test",
                is_correct=None,
                verified_at=None,
                created_at=now,
            )
        )
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="disclosure_impact",
                confidence=0.60,
                reasoning="test",
                is_correct=True,
                verified_at=now,
                created_at=now,
            )
        )
        db.flush()

        triples = get_surge_calibration_pairs_with_time(db, lookback_days=90)
        assert triples == []


# ---------------------------------------------------------------------------
# promote_candidate
# ---------------------------------------------------------------------------

class TestPromoteCandidate:
    def test_copies_candidate_to_active_path(self, tmp_path: Path) -> None:
        candidate_path = tmp_path / "candidate_20260809.pkl"
        candidate_path.write_bytes(b"fake-pickle-content")
        active_path = tmp_path / "nested" / "surge_calibrator.pkl"

        promote_candidate(candidate_path, active_path=active_path)

        assert active_path.exists()
        assert active_path.read_bytes() == b"fake-pickle-content"

    def test_does_not_delete_candidate_source(self, tmp_path: Path) -> None:
        candidate_path = tmp_path / "candidate_20260809.pkl"
        candidate_path.write_bytes(b"fake-pickle-content")
        active_path = tmp_path / "surge_calibrator.pkl"

        promote_candidate(candidate_path, active_path=active_path)

        assert candidate_path.exists(), "promote_candidate는 복사만 하고 원본을 지우면 안 된다"


# ---------------------------------------------------------------------------
# TASK-003: 스케줄러 핸들러 (AC-107-006, AC-107-008)
# ---------------------------------------------------------------------------

class TestSchedulerHandler:
    @patch("app.services.scheduler.SessionLocal")
    def test_normal_path_calls_run_shadow_training(self, mock_session_cls) -> None:
        """정상 경로: run_shadow_training을 호출하고 세션을 닫는다."""
        from app.services.scheduler import _run_surge_calibrator_shadow_training

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        fake_run = ShadowTrainingRun(
            run_date="20260809",
            sample_count=80,
            positive_count=20,
            sufficient_data=True,
            brier_raw=0.2,
            brier_calibrated=0.15,
            gate_passed=True,
            candidate_path="/tmp/candidate_20260809.pkl",
        )

        with patch(
            "app.services.surge_calibrator.run_shadow_training", return_value=fake_run
        ):
            _run_surge_calibrator_shadow_training()

        mock_db.close.assert_called_once()

    @patch("app.services.scheduler.SessionLocal")
    def test_exception_is_isolated_no_reraise(self, mock_session_cls, caplog) -> None:
        """AC-107-006: run_shadow_training 예외가 격리되어 경고 로그만 남고
        재발생시키지 않는다."""
        from app.services.scheduler import _run_surge_calibrator_shadow_training

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        with (
            patch(
                "app.services.surge_calibrator.run_shadow_training",
                side_effect=RuntimeError("DB 커넥션 장애 시뮬레이션"),
            ),
            caplog.at_level("WARNING"),
        ):
            # 예외 없이 정상 반환해야 한다
            _run_surge_calibrator_shadow_training()

        mock_db.close.assert_called_once()
        assert any(
            "캘리브레이터섀도우학습" in record.message for record in caplog.records
        )

    @patch("app.services.scheduler.scheduler")
    @patch("app.services.scheduler.settings")
    def test_job_registered_exactly_once_with_expected_cron(
        self, mock_settings, mock_sched
    ) -> None:
        """AC-107-008: surge_calibrator_shadow_training id로 sun 03:00 KST cron이
        정확히 1개 등록된다.

        기존 TestStartStopScheduler.test_start_scheduler_registers_jobs와 동일하게
        scheduler를 MagicMock으로 대체해 실제 SQLAlchemyJobStore(Postgres)
        연결 없이 add_job 호출 인자만 검증한다.
        """
        from app.services.scheduler import start_scheduler

        mock_settings.NEWS_CRAWL_INTERVAL_MINUTES = 30
        mock_settings.DART_CRAWL_INTERVAL_MINUTES = 60
        mock_settings.MARKET_CAP_UPDATE_HOURS = 6

        start_scheduler()

        matching_calls = [
            call
            for call in mock_sched.add_job.call_args_list
            if call.kwargs.get("id") == "surge_calibrator_shadow_training"
        ]
        assert len(matching_calls) == 1, (
            f"surge_calibrator_shadow_training id로 정확히 1회 등록되어야 함: "
            f"{len(matching_calls)}회 발견"
        )

        call = matching_calls[0]
        assert call.args[1] == "cron" or call.kwargs.get("trigger") == "cron" or (
            len(call.args) >= 2 and call.args[1] == "cron"
        )
        assert call.kwargs.get("day_of_week") == "sun"
        assert call.kwargs.get("hour") == 3
        assert call.kwargs.get("minute") == 0
        assert call.kwargs.get("timezone") == "Asia/Seoul"
