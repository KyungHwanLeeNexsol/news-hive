"""SPEC-AI-070 인수 테스트.

DDD 특성화 테스트 — REQ-AI070-001~005의 신규 로직을 검증한다. 신호 생성 경로
(compute_ensemble_score/gather_surge_candidates/build_scan_universe)와 매매 로직은
전혀 호출하지 않으며, SPEC-AI-068/069 기존 스위트(test_surge_evaluation_service.py,
test_spec_ai_069.py)는 이 파일에서 전혀 수정되지 않는다(별도 diff 0 확인 — 회귀 없음).

AC-070-001~004 + EC-1~EC-7 커버.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_detector_contribution import SurgeDetectorContribution
from app.services.surge_trading_service import _get_prev_business_day

TRADING_DATE = date(2026, 6, 30)
PREV_DAY = _get_prev_business_day(TRADING_DATE)


def _prev_day_dt() -> datetime:
    return datetime(PREV_DAY.year, PREV_DAY.month, PREV_DAY.day, 15, 20, tzinfo=timezone.utc)


def _make_signal(
    db: Session, stock_id: int, surge_basis: list[str], created_at: datetime, **extra
) -> FundSignal:
    metadata = {"surge_basis": surge_basis, **extra}
    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        signal_type="surge_candidate",
        confidence=0.7,
        reasoning="SPEC-AI-070 테스트 시그널",
        surge_metadata=json.dumps(metadata, ensure_ascii=False),
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def _make_outcome(
    db: Session, trading_date: date, stock_code: str, surge_type: str | None
) -> SurgeActualOutcome:
    outcome = SurgeActualOutcome(
        trading_date=trading_date,
        stock_code=stock_code,
        stock_name=f"주식{stock_code}",
        change_rate=12.0,
        was_surge=True,
        market="KOSPI",
        surge_type=surge_type,
    )
    db.add(outcome)
    db.flush()
    return outcome


def _recent_trading_days(end_date: date, n: int) -> list[date]:
    """end_date를 포함해 과거로 n개의 영업일을 반환한다(최신순)."""
    days = [end_date]
    d = end_date
    for _ in range(n - 1):
        d = _get_prev_business_day(d)
        days.append(d)
    return days


def _seed_contribution_row(
    db: Session,
    run_date: date,
    detector: str,
    *,
    emission_count: int = 0,
    solo_count: int = 0,
    solo_tp: int = 0,
    coincident_hit_rate: float | None = None,
    unique_catch: int = 0,
) -> SurgeDetectorContribution:
    row = SurgeDetectorContribution(
        run_date=run_date,
        detector=detector,
        emission_count=emission_count,
        solo_count=solo_count,
        solo_tp=solo_tp,
        coincident_hit_rate=coincident_hit_rate,
        unique_catch=unique_catch,
        retire_candidate=False,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# AC-070-001: 기여도 계산 정확성 & 영속화
# ---------------------------------------------------------------------------


class TestEvaluateDetectorContributionAccuracy:
    def test_ac070_001_scenario_solo_combo_and_miss(self, db: Session, make_stock) -> None:
        """A=volume_news_combo solo hit, B=theme_cluster+volume_news_combo combo hit,
        C=momentum_continuation solo miss (AC-070-001)."""
        stock_a = make_stock(stock_code="900001")
        stock_b = make_stock(stock_code="900002")
        stock_c = make_stock(stock_code="900003")

        _make_signal(db, stock_a.id, ["volume_news_combo"], _prev_day_dt())
        _make_signal(db, stock_b.id, ["theme_cluster", "volume_news_combo"], _prev_day_dt())
        _make_signal(db, stock_c.id, ["momentum_continuation"], _prev_day_dt())

        _make_outcome(db, TRADING_DATE, "900001", surge_type="scannable")
        _make_outcome(db, TRADING_DATE, "900002", surge_type="scannable")
        # C(900003)는 급등 실패 — SurgeActualOutcome 레코드 자체가 없음
        db.commit()

        from app.services.surge_contribution_service import evaluate_detector_contribution

        rows = evaluate_detector_contribution(db, TRADING_DATE)
        by_detector = {r.detector: r for r in rows}

        combo = by_detector["volume_news_combo"]
        assert combo.emission_count == 2
        assert combo.solo_count == 1
        assert combo.solo_tp == 1
        assert combo.unique_catch >= 1

        theme = by_detector["theme_cluster"]
        assert theme.emission_count == 1
        assert theme.solo_count == 0
        assert theme.solo_tp == 0

        momentum = by_detector["momentum_continuation"]
        assert momentum.emission_count == 1
        assert momentum.solo_count == 1
        assert momentum.solo_tp == 0
        assert momentum.unique_catch == 0

        # 영속화 검증: run_date 기준 DB에 실제로 반영됨
        persisted_combo = (
            db.query(SurgeDetectorContribution)
            .filter(
                SurgeDetectorContribution.run_date == TRADING_DATE,
                SurgeDetectorContribution.detector == "volume_news_combo",
            )
            .one()
        )
        assert persisted_combo.emission_count == 2

    def test_registry_completeness_all_detectors_get_one_row(
        self, db: Session, make_stock
    ) -> None:
        """REQ-002: 발신 이력이 없는 탐지기도 emission_count=0 행으로 기록된다."""
        stock = make_stock(stock_code="900010")
        _make_signal(db, stock.id, ["theme_cluster"], _prev_day_dt())
        db.commit()

        from app.services.surge_contribution_service import (
            DETECTOR_REGISTRY,
            evaluate_detector_contribution,
        )

        rows = evaluate_detector_contribution(db, TRADING_DATE)
        assert len(rows) == len(DETECTOR_REGISTRY)
        by_detector = {r.detector: r for r in rows}
        assert by_detector["weekend_gap_up"].emission_count == 0
        assert by_detector["forum_mention_surge"].emission_count == 0

    def test_upsert_idempotent_on_rerun_same_run_date(self, db: Session, make_stock) -> None:
        stock = make_stock(stock_code="900011")
        _make_signal(db, stock.id, ["theme_cluster"], _prev_day_dt())
        db.commit()

        from app.services.surge_contribution_service import (
            DETECTOR_REGISTRY,
            evaluate_detector_contribution,
        )

        evaluate_detector_contribution(db, TRADING_DATE)
        evaluate_detector_contribution(db, TRADING_DATE)

        count = (
            db.query(SurgeDetectorContribution)
            .filter(SurgeDetectorContribution.run_date == TRADING_DATE)
            .count()
        )
        assert count == len(DETECTOR_REGISTRY)  # 중복 행 없음(upsert)

    def test_unique_constraint_run_date_detector(self, db: Session) -> None:
        """모델의 UniqueConstraint(run_date, detector)가 실제로 강제된다."""
        from sqlalchemy.exc import IntegrityError

        _seed_contribution_row(db, TRADING_DATE, "theme_cluster", emission_count=1)
        db.commit()

        dup = SurgeDetectorContribution(
            run_date=TRADING_DATE, detector="theme_cluster", emission_count=2
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# ---------------------------------------------------------------------------
# EC-2: scannable 분모 0 → coincident_hit_rate null
# ---------------------------------------------------------------------------


class TestEC2ScannableDenominatorZero:
    def test_null_hit_rate_when_no_scannable_actual_that_day(
        self, db: Session, make_stock
    ) -> None:
        stock = make_stock(stock_code="900020")
        _make_signal(db, stock.id, ["theme_cluster"], _prev_day_dt())
        db.commit()  # SurgeActualOutcome 레코드 없음 → scannable 0건

        from app.services.surge_contribution_service import evaluate_detector_contribution

        rows = evaluate_detector_contribution(db, TRADING_DATE)
        theme = next(r for r in rows if r.detector == "theme_cluster")
        assert theme.emission_count == 1
        assert theme.coincident_hit_rate is None


# ---------------------------------------------------------------------------
# EC-3: 유니버스 부재(과거 날짜) — surge_type이 채워지지 않은 outcome은 scannable 미포함
# ---------------------------------------------------------------------------


class TestEC3UniverseAbsent:
    def test_non_scannable_outcome_not_counted_as_hit(self, db: Session, make_stock) -> None:
        stock = make_stock(stock_code="900021")
        _make_signal(db, stock.id, ["theme_cluster"], _prev_day_dt())
        # 유니버스 부재 시 evaluate_surge_predictions는 surge_type을 non_scannable로 라벨링한다
        _make_outcome(db, TRADING_DATE, "900021", surge_type="non_scannable")
        db.commit()

        from app.services.surge_contribution_service import evaluate_detector_contribution

        rows = evaluate_detector_contribution(db, TRADING_DATE)
        theme = next(r for r in rows if r.detector == "theme_cluster")
        assert theme.solo_tp == 0
        assert theme.unique_catch == 0
        # scannable 실제급등주가 전혀 없으므로(non_scannable만 존재) hit_rate는 null
        assert theme.coincident_hit_rate is None


# ---------------------------------------------------------------------------
# AC-070-002: dead-weight & consensus 뉘앙스 표면화
# ---------------------------------------------------------------------------


class TestContributionReportClassification:
    def test_ac070_002_three_way_classification_and_notes(
        self, db: Session, make_stock
    ) -> None:
        stock = make_stock(stock_code="900030")
        _make_signal(db, stock.id, ["theme_cluster"], _prev_day_dt())
        db.commit()

        from app.services.surge_contribution_service import (
            build_contribution_report,
            evaluate_detector_contribution,
        )

        rows = evaluate_detector_contribution(db, TRADING_DATE)
        report = build_contribution_report(db, TRADING_DATE, contribution_rows=rows)

        assert "(a) 앙상블 weighted_sum 편입" in report
        assert "(b) standalone/bypass 발신" in report
        assert "(c) 0-가중치" in report

        # weekend_gap_up: dead config 뉘앙스
        assert "weekend_gap_up" in report
        assert "dead config" in report

        # legacy_detectors: consensus 그룹 기여 뉘앙스
        assert "legacy" in report
        assert "consensus" in report or "컨센서스" in report

    def test_ec6_component_score_footnote_present(self, db: Session) -> None:
        from app.services.surge_contribution_service import build_contribution_report

        report = build_contribution_report(db, TRADING_DATE, contribution_rows=[])
        assert "EC-6" in report
        assert "component score" in report


# ---------------------------------------------------------------------------
# EC-1: 표본 부족 — retire_candidate는 false로 보수화
# ---------------------------------------------------------------------------


class TestEC1InsufficientSample:
    def test_insufficient_window_keeps_retire_candidate_false(self, db: Session) -> None:
        days = _recent_trading_days(TRADING_DATE, 3)  # 기본 윈도(10) 미만
        for rd in days:
            _seed_contribution_row(
                db, rd, "forum_mention_surge",
                emission_count=1, solo_count=1, solo_tp=0,
                coincident_hit_rate=0.0, unique_catch=0,
            )
        db.commit()

        from app.services.surge_contribution_service import assess_retirement_candidates

        assessments = assess_retirement_candidates(db, TRADING_DATE)
        result = assessments["forum_mention_surge"]
        assert result.retire_candidate is False
        assert result.insufficient_sample is True

    def test_valid_evidence_days_excludes_null_hit_rate_rows(self, db: Session) -> None:
        """EC-3: 발신했으나 그날 scannable 분모가 0(hit_rate=null)인 행은 유효 관측일에서 제외된다."""
        days = _recent_trading_days(TRADING_DATE, 10)
        for i, rd in enumerate(days):
            if i < 5:
                # 절반은 "증거 없음" 행(발신했지만 hit_rate 측정 불가)
                _seed_contribution_row(
                    db, rd, "forum_mention_surge",
                    emission_count=1, solo_count=1, solo_tp=0,
                    coincident_hit_rate=None, unique_catch=0,
                )
            else:
                _seed_contribution_row(
                    db, rd, "forum_mention_surge",
                    emission_count=1, solo_count=1, solo_tp=0,
                    coincident_hit_rate=0.0, unique_catch=0,
                )
        db.commit()

        from app.services.surge_contribution_service import assess_retirement_candidates

        assessments = assess_retirement_candidates(db, TRADING_DATE, window_trading_days=10)
        result = assessments["forum_mention_surge"]
        # 유효 관측일 5 < 10 → 표본 부족으로 보류
        assert result.insufficient_sample is True
        assert result.retire_candidate is False


# ---------------------------------------------------------------------------
# EC-4/AC-070-003: 은퇴 제안 + backtest 검증 + auto-removal 금지
# ---------------------------------------------------------------------------


class TestRetirementProposalAndAutoRemovalGuard:
    def test_ac070_003_retirement_candidate_with_backtest_verdict(self, db: Session) -> None:
        days = _recent_trading_days(TRADING_DATE, 10)
        for rd in days:
            _seed_contribution_row(
                db, rd, "forum_mention_surge",
                emission_count=1, solo_count=1, solo_tp=0,
                coincident_hit_rate=0.0, unique_catch=0,
            )
        db.commit()

        from app.services.surge_contribution_service import assess_retirement_candidates

        assessments = assess_retirement_candidates(db, TRADING_DATE)
        result = assessments["forum_mention_surge"]
        assert result.retire_candidate is True
        assert result.backtest_verdict is not None
        assert result.backtest_verdict.accuracy_did_not_drop is True

    def test_backtest_exclusion_recomputes_accuracy_from_by_combination(
        self, db: Session, make_stock
    ) -> None:
        """verify_retirement_via_backtest: D의 solo 신호를 제외한 잔여 accuracy 재계산 경로."""
        from app.services.surge_contribution_service import verify_retirement_via_backtest

        # forum_mention_surge solo 신호 2건(1승1패) + theme_cluster solo 신호 2건(2승)을
        # compute_surge_backtest가 읽는 FundSignal(price_at_signal/price_after_5d)로 생성한다.
        now = datetime.now(timezone.utc)

        def _backtest_signal(stock, basis, price_at, price_after):
            sig = FundSignal(
                stock_id=stock.id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.7,
                reasoning="backtest 테스트",
                surge_metadata=json.dumps({"surge_basis": basis}, ensure_ascii=False),
                created_at=now,
                price_at_signal=price_at,
                price_after_5d=price_after,
            )
            db.add(sig)
            db.flush()
            return sig

        _backtest_signal(make_stock(stock_code="920001"), ["forum_mention_surge"], 10000, 11000)  # 승
        _backtest_signal(make_stock(stock_code="920002"), ["forum_mention_surge"], 10000, 9000)  # 패
        _backtest_signal(make_stock(stock_code="920003"), ["theme_cluster"], 10000, 11000)  # 승
        _backtest_signal(make_stock(stock_code="920004"), ["theme_cluster"], 10000, 11000)  # 승
        db.commit()

        verdict = verify_retirement_via_backtest(db, "forum_mention_surge", lookback_days=30)

        assert verdict.before_total_signals == 4
        assert verdict.solo_signals_excluded == 2
        assert verdict.after_total_signals == 2
        # forum_mention_surge(1승1패, 0.5) 제외 후 잔여는 theme_cluster 2승 → 100%
        assert verdict.after_accuracy == pytest.approx(1.0)
        assert verdict.accuracy_did_not_drop is True

    def test_ec4_weekend_gap_up_structural_zero_emission_retires_with_renorm_note(
        self, db: Session
    ) -> None:
        days = _recent_trading_days(TRADING_DATE, 10)
        for rd in days:
            _seed_contribution_row(db, rd, "weekend_gap_up", emission_count=0)
        db.commit()

        from app.services.surge_contribution_service import (
            assess_retirement_candidates,
            build_contribution_report,
        )

        assessments = assess_retirement_candidates(db, TRADING_DATE)
        assert assessments["weekend_gap_up"].retire_candidate is True

        report = build_contribution_report(
            db, TRADING_DATE, contribution_rows=[], retirement_assessments=assessments
        )
        assert "weekend_gap_up" in report
        assert "재정규화" in report

    def test_ec5_legacy_consensus_contribution_prevents_retirement(self, db: Session) -> None:
        """EC-5: legacy가 weighted_sum 0이지만 unique_catch>0(consensus 기여)면 은퇴 부적합."""
        days = _recent_trading_days(TRADING_DATE, 10)
        for rd in days:
            _seed_contribution_row(
                db, rd, "legacy",
                emission_count=1, solo_count=1, solo_tp=1,
                coincident_hit_rate=1.0, unique_catch=1,
            )
        db.commit()

        from app.services.surge_contribution_service import assess_retirement_candidates

        assessments = assess_retirement_candidates(db, TRADING_DATE)
        result = assessments["legacy"]
        assert result.is_floor_breach is False
        assert result.retire_candidate is False

    def test_ac070_003_yaml_files_unmodified_after_full_pipeline(
        self, db: Session, make_stock
    ) -> None:
        import hashlib
        from pathlib import Path

        base_yaml = Path(__file__).parent.parent / "app" / "surge_config" / "surge_detection.yaml"
        auto_yaml = (
            Path(__file__).parent.parent / "app" / "surge_config" / "surge_detection.auto.yaml"
        )

        before_hash = hashlib.sha256(base_yaml.read_bytes()).hexdigest()
        before_mtime = base_yaml.stat().st_mtime
        auto_existed_before = auto_yaml.exists()

        days = _recent_trading_days(TRADING_DATE, 10)
        for rd in days:
            _seed_contribution_row(db, rd, "forum_mention_surge", emission_count=0)
        stock = make_stock(stock_code="900040")
        _make_signal(db, stock.id, ["theme_cluster"], _prev_day_dt())
        db.commit()

        from app.services.surge_contribution_service import (
            apply_retirement_candidates,
            assess_retirement_candidates,
            build_contribution_report,
            evaluate_detector_contribution,
        )

        rows = evaluate_detector_contribution(db, TRADING_DATE)
        assessments = assess_retirement_candidates(db, TRADING_DATE)
        apply_retirement_candidates(db, TRADING_DATE, assessments)
        build_contribution_report(
            db, TRADING_DATE, contribution_rows=rows, retirement_assessments=assessments
        )

        after_hash = hashlib.sha256(base_yaml.read_bytes()).hexdigest()
        after_mtime = base_yaml.stat().st_mtime
        assert before_hash == after_hash
        assert before_mtime == after_mtime
        assert auto_yaml.exists() == auto_existed_before

    def test_surge_auto_improver_has_no_detector_add_remove_path(self) -> None:
        """REQ-004 [HARD]: surge_auto_improver에 탐지기 추가/제거 능력이 없음을 소스 검사로 보장."""
        import inspect

        from app.services import surge_auto_improver

        source = inspect.getsource(surge_auto_improver)
        forbidden_patterns = [
            "def add_detector",
            "def remove_detector",
            "def disable_detector",
            "_DETECTORS.append",
            "_DETECTORS.remove",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, f"surge_auto_improver에 금지된 패턴 발견: {pattern}"

    def test_surge_contribution_service_never_writes_yaml(self) -> None:
        """본 서비스 모듈 소스에 yaml 쓰기(open(..., 'w') 등) 코드가 전혀 없음을 보장."""
        import inspect

        from app.services import surge_contribution_service

        source = inspect.getsource(surge_contribution_service)
        assert "_patch_yaml_values" not in source
        assert 'open(' not in source
        assert "yaml.dump" not in source
        assert "yaml.safe_dump" not in source

    def test_apply_retirement_candidates_updates_only_db_rows(self, db: Session) -> None:
        days = _recent_trading_days(TRADING_DATE, 10)
        for rd in days:
            _seed_contribution_row(db, rd, "forum_mention_surge", emission_count=0)
        db.commit()

        from app.services.surge_contribution_service import apply_retirement_candidates

        rows = apply_retirement_candidates(db, TRADING_DATE)
        target = next(r for r in rows if r.detector == "forum_mention_surge")
        assert target.retire_candidate is True


# ---------------------------------------------------------------------------
# AC-070-004: 학습형 앙상블 타당성 평가
# ---------------------------------------------------------------------------


class TestLearnedEnsembleFeasibility:
    def test_ac070_004_insufficient_data_report(self, db: Session) -> None:
        from app.services.surge_contribution_service import assess_learned_ensemble_feasibility

        report = assess_learned_ensemble_feasibility(db)
        assert report.data_sufficiency == "insufficient"
        assert report.recommend_followup_spec is False
        assert "불충분" in report.text

    def test_ac070_004_sufficient_data_report_no_model_deployed(
        self, db: Session, make_stock
    ) -> None:
        from app.services.surge_contribution_service import (
            LEARNED_FEASIBILITY_MIN_TRADING_DAYS,
            assess_learned_ensemble_feasibility,
            evaluate_detector_contribution,
        )

        days = _recent_trading_days(TRADING_DATE, LEARNED_FEASIBILITY_MIN_TRADING_DAYS)
        for i, rd in enumerate(days):
            prev = _get_prev_business_day(rd)
            stock = make_stock(stock_code=f"91{i:04d}")
            _make_signal(
                db, stock.id, ["theme_cluster"],
                datetime(prev.year, prev.month, prev.day, 15, 20, tzinfo=timezone.utc),
            )
            surge_type = "scannable" if i % 2 == 0 else "non_scannable"
            _make_outcome(db, rd, stock.stock_code, surge_type=surge_type)
            db.commit()
            evaluate_detector_contribution(db, rd)

        report = assess_learned_ensemble_feasibility(db)
        assert report.data_sufficiency == "sufficient"
        assert report.learned_accuracy is not None
        assert report.rule_based_accuracy is not None
        assert "in-sample" in report.text
        # REQ-005 [HARD]: 모델이 운영에 연결되지 않는다 — 리포트 텍스트 확인 외 별도 부수효과 없음
        assert "저장/배포" in report.text or "연결" in report.text


# ---------------------------------------------------------------------------
# EC-7: 텔레그램 미설정 시 graceful skip
# ---------------------------------------------------------------------------


class TestSchedulerWrapperTelegramMissing:
    @patch("app.services.scheduler._is_kr_market_open", return_value=True)
    @patch("app.services.scheduler.SessionLocal")
    @patch(
        "app.services.surge_contribution_service.build_contribution_report",
        return_value="테스트 리포트",
    )
    @patch("app.services.surge_contribution_service.apply_retirement_candidates")
    @patch("app.services.surge_contribution_service.assess_retirement_candidates", return_value={})
    @patch("app.services.surge_contribution_service.evaluate_detector_contribution", return_value=[])
    def test_ec7_missing_telegram_token_does_not_crash(
        self,
        mock_eval,
        mock_assess,
        mock_apply,
        mock_report,
        mock_session_cls,
        mock_market_open,
        monkeypatch,
    ) -> None:
        monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        from app.services.scheduler import _run_surge_detector_contribution

        _run_surge_detector_contribution()  # 예외 없이 완료되어야 함(EC-7)

        mock_db.close.assert_called_once()

    @patch("app.services.scheduler._is_kr_market_open", return_value=False)
    @patch("app.services.scheduler.SessionLocal")
    def test_weekend_skips_job(self, mock_session_cls, mock_market_open) -> None:
        from app.services.scheduler import _run_surge_detector_contribution

        _run_surge_detector_contribution()
        mock_session_cls.assert_not_called()
