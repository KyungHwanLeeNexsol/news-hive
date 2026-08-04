"""SPEC-AI-099: 급등예측 피처 스냅샷 데이터 인프라 (모델 학습 미포함) — 검증 스위트.

AC-099-001 ~ AC-099-009 검증. 모델 학습/서빙은 본 SPEC의 범위가 아니다 — 데이터
캡처·조회 가능 상태까지만.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_feature_snapshot import SurgeFeatureSnapshot
from app.services.ml_feature_engineering import check_ml_readiness
from app.services.surge_detector import SurgeCandidate, _persist_feature_snapshots
from app.services.surge_feature_snapshot_service import (
    FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS,
    backfill_outcome_labels,
    check_feature_snapshot_readiness,
)

# ---------------------------------------------------------------------------
# AC-099-001/002: 스냅샷 모델 저장 (승격/비승격 모두, 불변성)
# ---------------------------------------------------------------------------


class TestPersistFeatureSnapshots:
    """AC-099-001/002: 스냅샷 배치 삽입 — 전량 저장 + 불변성."""

    def test_ac099_001_all_merged_candidates_persisted_with_qualified_split(
        self, db: Session,
    ):
        """앙상블 스코어링 사이클이 N개 후보를 평가하면 N개 신규 행이 생성되고
        qualified 필드가 올바르게 분기된다 (AC-099-001, 시나리오 1)."""
        merged = {
            "000001": SurgeCandidate(stock_code="000001", stock_name="종목A", theme_cluster_score=0.9),
            "000002": SurgeCandidate(stock_code="000002", stock_name="종목B", theme_cluster_score=0.1),
            "000003": SurgeCandidate(stock_code="000003", stock_name="종목C", theme_cluster_score=0.05),
        }
        scores = {"000001": 0.90, "000002": 0.10, "000003": 0.05}
        qualified_codes = {"000001"}
        scanned_at = datetime.now(timezone.utc)

        with patch(
            "app.services.naver_finance.fetch_current_price_with_change_sync",
            return_value={"current_price": 10000, "change_rate": 1.0},
        ):
            _persist_feature_snapshots(db, scanned_at, merged, scores, qualified_codes)

        rows = db.query(SurgeFeatureSnapshot).all()
        assert len(rows) == 3
        qualified_rows = [r for r in rows if r.qualified]
        non_qualified_rows = [r for r in rows if not r.qualified]
        assert len(qualified_rows) == 1
        assert qualified_rows[0].stock_code == "000001"
        assert len(non_qualified_rows) == 2

    def test_ac099_001_edge_case_zero_candidates_is_noop(self, db: Session):
        """§D Edge Cases: 평가된 후보가 0개면 예외 없이 무해해야 한다."""
        _persist_feature_snapshots(db, datetime.now(timezone.utc), {}, {}, set())
        assert db.query(SurgeFeatureSnapshot).count() == 0

    def test_ac099_002_rescanned_stock_creates_new_row_and_preserves_old(
        self, db: Session,
    ):
        """동일 종목이 재스캔되면 기존 행을 UPDATE하지 않고 새 행을 추가하며,
        기존 행의 값은 변경되지 않는다 (AC-099-002)."""
        candidate_v1 = SurgeCandidate(stock_code="000001", stock_name="종목A", theme_cluster_score=0.3)
        with patch("app.services.naver_finance.fetch_current_price_with_change_sync", return_value=None):
            _persist_feature_snapshots(
                db, datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
                {"000001": candidate_v1}, {"000001": 0.30}, set(),
            )

        first_row = db.query(SurgeFeatureSnapshot).one()
        first_id = first_row.id
        first_score = first_row.surge_score

        candidate_v2 = SurgeCandidate(stock_code="000001", stock_name="종목A", theme_cluster_score=0.9)
        with patch(
            "app.services.naver_finance.fetch_current_price_with_change_sync",
            return_value={"current_price": 5000, "change_rate": 2.0},
        ):
            _persist_feature_snapshots(
                db, datetime(2026, 8, 1, 15, 20, tzinfo=timezone.utc),
                {"000001": candidate_v2}, {"000001": 0.90}, {"000001"},
            )

        rows = db.query(SurgeFeatureSnapshot).order_by(SurgeFeatureSnapshot.id).all()
        assert len(rows) == 2
        assert {r.id for r in rows} == {first_id, rows[1].id}
        # 1차 행은 변경되지 않았어야 한다
        unchanged_first = next(r for r in rows if r.id == first_id)
        assert unchanged_first.surge_score == pytest.approx(first_score)
        assert unchanged_first.qualified is False

    def test_ac099_009_persist_does_not_mutate_candidate_objects(self, db: Session):
        """부가 관측 경로는 순수 읽기 전용이어야 한다 — SurgeCandidate 객체를
        변형하지 않는다 (REQ-AI099-006 PRESERVE 확인)."""
        candidate = SurgeCandidate(stock_code="000001", stock_name="종목A", theme_cluster_score=0.5)
        before = dict(candidate.__dict__)

        with patch("app.services.naver_finance.fetch_current_price_with_change_sync", return_value=None):
            _persist_feature_snapshots(
                db, datetime.now(timezone.utc), {"000001": candidate}, {"000001": 0.5}, set(),
            )

        assert dict(candidate.__dict__) == before


# ---------------------------------------------------------------------------
# AC-099-003/004: 배치 쓰기 (단일 commit, 실패 격리)
# ---------------------------------------------------------------------------


class TestBatchWriteBehavior:
    """AC-099-003/004: 배치 쓰기가 단일 commit이며, 실패해도 예외가 전파되지 않는다."""

    def test_ac099_003_batch_write_is_single_commit_call(
        self, db: Session, monkeypatch: pytest.MonkeyPatch,
    ):
        """스코어링 사이클당 db.commit() 호출은 정확히 1회여야 한다 (AC-099-003)."""
        merged = {
            f"{i:06d}": SurgeCandidate(stock_code=f"{i:06d}", stock_name=f"종목{i}", theme_cluster_score=0.1)
            for i in range(5)
        }
        scores = {code: 0.1 for code in merged}

        commit_calls: list[int] = []
        original_commit = db.commit

        def _wrapped_commit():
            commit_calls.append(1)
            return original_commit()

        monkeypatch.setattr(db, "commit", _wrapped_commit)

        with patch("app.services.naver_finance.fetch_current_price_with_change_sync", return_value=None):
            _persist_feature_snapshots(db, datetime.now(timezone.utc), merged, scores, set())

        assert len(commit_calls) == 1
        assert db.query(SurgeFeatureSnapshot).count() == 5

    def test_ac099_004_batch_write_failure_does_not_raise(
        self, db: Session, monkeypatch: pytest.MonkeyPatch,
    ):
        """스냅샷 배치 쓰기가 예외를 발생시켜도 예외가 전파되지 않고 로그로만
        남는다 — 상위 함수(FundSignal 생성 등)의 흐름을 막지 않는다 (AC-099-004)."""
        merged = {"000001": SurgeCandidate(stock_code="000001", stock_name="종목A", theme_cluster_score=0.5)}
        scores = {"000001": 0.5}

        def _raise_commit():
            raise RuntimeError("simulated DB connection error")

        monkeypatch.setattr(db, "commit", _raise_commit)

        # 예외가 전파되지 않아야 한다 — 호출 자체가 성공적으로 반환되면 PASS.
        with patch("app.services.naver_finance.fetch_current_price_with_change_sync", return_value=None):
            _persist_feature_snapshots(db, datetime.now(timezone.utc), merged, scores, {"000001"})


# ---------------------------------------------------------------------------
# AC-099-005/006: 정답 라벨 백필
# ---------------------------------------------------------------------------


class TestOutcomeLabelBackfill:
    """AC-099-005/006: 정답 라벨 조인 가능 시 백필, 불가 시 NULL 유지."""

    def test_ac099_005_backfill_fills_labels_when_outcome_exists(self, db: Session):
        """SurgeActualOutcome이 존재하면 백필 잡 실행 시 필드가 채워진다 (AC-099-005)."""
        scanned_at = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)  # 월요일
        next_trading_date = date(2026, 8, 4)  # 화요일

        snapshot = SurgeFeatureSnapshot(
            stock_code="000001", scanned_at=scanned_at,
            theme_cluster_score=0.5, combo_score=0.0, best_disclosure_score=0.0,
            legacy_score=0.0, news_delayed_score=0.0, volume_breakout_score=0.0,
            momentum_continuation_score=0.0, squeeze_score=0.0, active_groups=1,
            surge_score=0.5, entry_pool="existing", qualified=True,
        )
        db.add(snapshot)
        db.add(SurgeActualOutcome(
            trading_date=next_trading_date, stock_code="000001", stock_name="종목A",
            change_rate=12.5, was_surge=True, market="KOSPI",
        ))
        db.commit()

        result = backfill_outcome_labels(db)

        assert result["filled"] == 1
        db.refresh(snapshot)
        assert snapshot.outcome_trading_date == next_trading_date
        assert snapshot.outcome_change_rate == pytest.approx(12.5)
        assert snapshot.outcome_was_surge is True

    def test_ac099_006_backfill_leaves_null_when_outcome_absent(self, db: Session):
        """SurgeActualOutcome이 아직 없으면 NULL로 유지되며 예외 없이 정상 종료된다
        (AC-099-006)."""
        scanned_at = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
        snapshot = SurgeFeatureSnapshot(
            stock_code="000002", scanned_at=scanned_at,
            theme_cluster_score=0.5, combo_score=0.0, best_disclosure_score=0.0,
            legacy_score=0.0, news_delayed_score=0.0, volume_breakout_score=0.0,
            momentum_continuation_score=0.0, squeeze_score=0.0, active_groups=1,
            surge_score=0.5, entry_pool="existing", qualified=False,
        )
        db.add(snapshot)
        db.commit()

        result = backfill_outcome_labels(db)

        assert result["filled"] == 0
        db.refresh(snapshot)
        assert snapshot.outcome_change_rate is None
        assert snapshot.outcome_was_surge is None
        # outcome_trading_date는 다음 거래일로 채워지되(조회 키), 라벨 자체는 NULL로 남는다
        assert snapshot.outcome_trading_date == date(2026, 8, 4)

    def test_ac099_006_weekend_scan_skips_to_next_monday(self, db: Session):
        """§D Edge Cases: 금요일 스캔은 주말을 건너뛰어 다음 월요일로 계산된다
        (최소 구현 — 공휴일 미처리)."""
        friday = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
        snapshot = SurgeFeatureSnapshot(
            stock_code="000003", scanned_at=friday,
            theme_cluster_score=0.0, combo_score=0.0, best_disclosure_score=0.0,
            legacy_score=0.0, news_delayed_score=0.0, volume_breakout_score=0.0,
            momentum_continuation_score=0.0, squeeze_score=0.0, active_groups=0,
            surge_score=0.0, entry_pool="existing", qualified=False,
        )
        db.add(snapshot)
        db.commit()

        backfill_outcome_labels(db)

        db.refresh(snapshot)
        assert snapshot.outcome_trading_date == date(2026, 8, 3)  # 월요일


# ---------------------------------------------------------------------------
# AC-099-007: 보존 정책 (자동 삭제 잡 미등록)
# ---------------------------------------------------------------------------


def test_ac099_007_no_cleanup_job_registered_for_feature_snapshots():
    """SurgeFeatureSnapshot 대상의 자동 삭제/정리 스케줄 잡이 등록되지 않아야 한다
    (AC-099-007). 백필 잡 등록은 허용된다."""
    import app.services.scheduler as scheduler_module

    source = inspect.getsource(scheduler_module)
    mentioning_lines = [
        line for line in source.splitlines() if "surge_feature_snapshot" in line.lower()
    ]
    assert mentioning_lines, "surge_feature_snapshot 백필 잡이 등록되어 있어야 한다"
    assert not any(
        "delete" in line.lower() or "cleanup" in line.lower() for line in mentioning_lines
    )


# ---------------------------------------------------------------------------
# AC-099-008: 신규 병렬 축적 카운터
# ---------------------------------------------------------------------------


class TestFeatureSnapshotReadinessCounter:
    """AC-099-008: 신규 카운터가 기존 check_ml_readiness()와 독립적으로 동작한다."""

    def test_ac099_008_counter_independent_of_check_ml_readiness(self, db: Session):
        """두 함수는 서로 다른 그레인을 측정하며 독립적인 결과를 반환한다."""
        base = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
        for day_offset in range(2):
            snapshot = SurgeFeatureSnapshot(
                stock_code="000001", scanned_at=base + timedelta(days=day_offset),
                theme_cluster_score=0.0, combo_score=0.0, best_disclosure_score=0.0,
                legacy_score=0.0, news_delayed_score=0.0, volume_breakout_score=0.0,
                momentum_continuation_score=0.0, squeeze_score=0.0, active_groups=0,
                surge_score=0.0, entry_pool="existing", qualified=False,
            )
            db.add(snapshot)
        db.commit()

        feature_result = check_feature_snapshot_readiness(db)
        ml_result = check_ml_readiness(db)

        assert feature_result["ready"] is False
        assert feature_result["days"] == 2
        assert set(feature_result.keys()) == {"ready", "days", "message"}

        # 기존 함수는 MLFeatureSnapshot(무관 테이블) 기준이라 완전히 독립적이다.
        assert ml_result["days"] == 0
        assert ml_result["ready"] is False

    def test_ac099_008_ready_when_threshold_reached(self, db: Session):
        """고유 스캔 일수가 임계값에 도달하면 ready=True를 반환한다."""
        base = date(2026, 1, 1)
        for day_offset in range(FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS):
            scanned_at = datetime.combine(
                base + timedelta(days=day_offset), datetime.min.time(), tzinfo=timezone.utc,
            )
            db.add(SurgeFeatureSnapshot(
                stock_code="000001", scanned_at=scanned_at,
                theme_cluster_score=0.0, combo_score=0.0, best_disclosure_score=0.0,
                legacy_score=0.0, news_delayed_score=0.0, volume_breakout_score=0.0,
                momentum_continuation_score=0.0, squeeze_score=0.0, active_groups=0,
                surge_score=0.0, entry_pool="existing", qualified=False,
            ))
        db.commit()

        result = check_feature_snapshot_readiness(db)
        assert result["ready"] is True
        assert result["days"] == FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS


# ---------------------------------------------------------------------------
# AC-099-009: 앙상블 계산/승격 로직 무변경 (회귀)
# ---------------------------------------------------------------------------


def test_ac099_009_gather_surge_candidates_empty_input_still_returns_list(db: Session):
    """gather_surge_candidates 무회귀 확인 — 빈 입력 시 기존과 동일하게 빈 리스트를
    반환해야 한다(스냅샷 캡처 경로 추가 후에도 기존 characterization 유지)."""
    from app.surge_config.surge_settings import get_surge_config
    from app.services.surge_detector import gather_surge_candidates

    result = gather_surge_candidates(
        db=db, recent_news=[], config=get_surge_config(), legacy_candidates=[],
    )
    assert isinstance(result, list)
    assert result == []
