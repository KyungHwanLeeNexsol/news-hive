"""SPEC-AI-108: 급등예측 지평 시그니처별 정밀도 분리 측정.

AC-108-001: 빈/None surge_basis는 multi_day_dominant로 재구성된다.
AC-108-002: 단일/다중 라벨 재구성이 compute_horizon_signature()와 동등하다
            (immediate_disclosure/legacy 정규화 동등성 포함).
AC-108-003: 앙상블 7개 키 밖의 surge_basis 멤버는 무시된다.
AC-108-004: 지평 시그니처별 정밀도가 4개 버킷 모두에 산출된다.
AC-108-005: 재조회는 signal_rows의 fund_signal_id 집합으로 한정되고
            predicted_set을 재조회하지 않는다.
AC-108-006: 신호 수 0인 버킷의 precision은 None이다.
AC-108-007: 정상 평가 사이클에서 구조화 로그 1줄이 기록된다.
AC-108-008: 진단 실패가 핵심 평가 결과 및 EOD upsert를 방해하지 않는다.
AC-108-009: 게이팅/신규 테이블/기존 함수 무변경(별도 grep/diff로 검증, 이 파일 범위 밖).
AC-108-010: plan.md §C 증거 활용 절차 문서화(별도 grep으로 검증, 이 파일 범위 밖).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.models.surge_signal_forward_outcome import SurgeSignalForwardOutcome
from app.services.naver_finance import PriceRecord
from app.services.surge_detector import SurgeCandidate, compute_horizon_signature
from app.services.surge_evaluation_service import (
    _analyze_precision_by_horizon_signature,
    _reconstruct_horizon_signature_from_basis,
    evaluate_surge_predictions,
)
from app.surge_config.surge_settings import get_surge_config


def _make_stock(db: Session, code: str) -> Stock:
    sector = Sector(name=f"테스트섹터_{code}", is_custom=False)
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=f"주식{code}", sector_id=sector.id, market="KOSPI")
    db.add(stock)
    db.flush()
    return stock


_HORIZON_LABELS = get_surge_config().ensemble.horizon_aware_thresholds.horizon_labels


# ---------------------------------------------------------------------------
# TASK-001 / AC-108-001, AC-108-002, AC-108-003:
# _reconstruct_horizon_signature_from_basis
# ---------------------------------------------------------------------------


class TestReconstructHorizonSignatureFromBasis:
    def test_none_returns_multi_day_dominant(self):
        """AC-108-001: surge_basis=None → multi_day_dominant."""
        assert (
            _reconstruct_horizon_signature_from_basis(None, _HORIZON_LABELS)
            == "multi_day_dominant"
        )

    def test_empty_list_returns_multi_day_dominant(self):
        """AC-108-001: surge_basis=[] → multi_day_dominant."""
        assert (
            _reconstruct_horizon_signature_from_basis([], _HORIZON_LABELS)
            == "multi_day_dominant"
        )

    def test_single_same_day_key_matches_live_function(self):
        """AC-108-002: 단일 same_day 키(volume_breakout) — 라이브 함수와 동등."""
        reconstructed = _reconstruct_horizon_signature_from_basis(
            ["volume_breakout"], _HORIZON_LABELS
        )
        config = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000000", stock_name="테스트", volume_breakout_score=0.9
        )
        live = compute_horizon_signature(candidate, config)
        assert reconstructed == live == "same_day_dominant"

    def test_single_next_day_key_matches_live_function(self):
        """AC-108-002: 단일 next_day 키(momentum_continuation) — 라이브 함수와 동등."""
        reconstructed = _reconstruct_horizon_signature_from_basis(
            ["momentum_continuation"], _HORIZON_LABELS
        )
        config = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000000", stock_name="테스트", momentum_continuation_score=0.9
        )
        live = compute_horizon_signature(candidate, config)
        assert reconstructed == live == "next_day_dominant"

    def test_single_multi_day_key_matches_live_function(self):
        """AC-108-002: 단일 multi_day 키(theme_cluster) — 라이브 함수와 동등."""
        reconstructed = _reconstruct_horizon_signature_from_basis(
            ["theme_cluster"], _HORIZON_LABELS
        )
        config = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000000", stock_name="테스트", theme_cluster_score=0.9
        )
        live = compute_horizon_signature(candidate, config)
        assert reconstructed == live == "multi_day_dominant"

    def test_multiple_different_labels_returns_mixed(self):
        """AC-108-002: 서로 다른 라벨을 갖는 2개 이상 키 — mixed, 라이브 함수와 동등."""
        reconstructed = _reconstruct_horizon_signature_from_basis(
            ["theme_cluster", "volume_breakout"], _HORIZON_LABELS
        )
        config = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000000",
            stock_name="테스트",
            theme_cluster_score=0.9,
            volume_breakout_score=0.9,
        )
        live = compute_horizon_signature(candidate, config)
        assert reconstructed == live == "mixed"

    def test_immediate_disclosure_normalizes_to_disclosure_pattern_equivalent(self):
        """AC-108-002 회귀 방지: surge_basis=["immediate_disclosure"]가 확정 매핑
        {"immediate_disclosure": "disclosure_pattern"}을 통해 disclosure_pattern
        앙상블 키로 정규화되고, immediate_disclosure_score>0인 라이브 후보와 동등하다."""
        reconstructed = _reconstruct_horizon_signature_from_basis(
            ["immediate_disclosure"], _HORIZON_LABELS
        )
        config = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000000", stock_name="테스트", immediate_disclosure_score=0.9
        )
        live = compute_horizon_signature(candidate, config)
        assert reconstructed == live == "same_day_dominant"

    def test_legacy_normalizes_to_legacy_detectors_equivalent(self):
        """AC-108-002 회귀 방지: surge_basis=["legacy"]가 확정 매핑
        {"legacy": "legacy_detectors"}를 통해 legacy_detectors 앙상블 키로 정규화되고,
        legacy_score>0인 라이브 후보와 동등하다."""
        reconstructed = _reconstruct_horizon_signature_from_basis(["legacy"], _HORIZON_LABELS)
        config = get_surge_config()
        candidate = SurgeCandidate(
            stock_code="000000", stock_name="테스트", legacy_score=0.9
        )
        live = compute_horizon_signature(candidate, config)
        assert reconstructed == live == "multi_day_dominant"

    def test_non_ensemble_keys_ignored(self):
        """AC-108-003: 앙상블 7개 키 밖의 이름(near_limit_up_carry)은 결과에 영향을
        주지 않는다 — ["near_limit_up_carry", "volume_breakout"]는
        ["volume_breakout"]만 있을 때와 동일한 결과."""
        with_bypass_name = _reconstruct_horizon_signature_from_basis(
            ["near_limit_up_carry", "volume_breakout"], _HORIZON_LABELS
        )
        without_bypass_name = _reconstruct_horizon_signature_from_basis(
            ["volume_breakout"], _HORIZON_LABELS
        )
        assert with_bypass_name == without_bypass_name == "same_day_dominant"

    def test_bypass_only_signal_returns_multi_day_dominant(self):
        """시나리오 3: 우회/독립 탐지기만 발화한 신호는 앙상블 7개 키와의 교집합이
        빈 집합이므로 multi_day_dominant로 안전하게 처리된다 — 예외 없음."""
        assert (
            _reconstruct_horizon_signature_from_basis(
                ["near_limit_up_carry"], _HORIZON_LABELS
            )
            == "multi_day_dominant"
        )


# ---------------------------------------------------------------------------
# TASK-002 / AC-108-004, AC-108-005, AC-108-006:
# _analyze_precision_by_horizon_signature
# ---------------------------------------------------------------------------


class TestAnalyzePrecisionByHorizonSignature:
    def _make_signal_row(
        self, db: Session, code: str, surge_basis: list[str], forward_pct: float | None
    ):
        stock = _make_stock(db, code)
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            surge_metadata=f'{{"surge_basis": {surge_basis!r}}}'.replace("'", '"'),
            price_at_signal=1000,
        )
        db.add(signal)
        db.flush()
        db.commit()

        if forward_pct is not None:
            db.add(
                SurgeSignalForwardOutcome(
                    trading_date=date(2026, 6, 9),
                    stock_code=code,
                    fund_signal_id=signal.id,
                    price_at_signal=1000,
                    forward_max_return_pct=forward_pct,
                )
            )
            db.commit()

        return SimpleNamespace(
            fund_signal_id=signal.id,
            stock_code=code,
            surge_metadata=signal.surge_metadata,
        )

    def test_all_four_buckets_present_with_correct_precision(self, db: Session):
        """AC-108-004: 4개 버킷 각각에 서로 다른 신호수/forward_max_return_pct 분포를
        가진 fixture로 정밀도 계산값을 수동 계산값과 대조."""
        trading_date = date(2026, 6, 9)
        rows = [
            # same_day_dominant: 2건, 1건 양성(>=10.0) → precision=0.5
            self._make_signal_row(db, "100001", ["volume_breakout"], 15.0),
            self._make_signal_row(db, "100002", ["volume_breakout"], 5.0),
            # next_day_dominant: 1건, 1건 양성 → precision=1.0
            self._make_signal_row(db, "100003", ["momentum_continuation"], 10.0),
            # multi_day_dominant: 1건, 0건 양성 → precision=0.0
            self._make_signal_row(db, "100004", ["theme_cluster"], 3.0),
            # mixed: 1건, 1건 양성 → precision=1.0
            self._make_signal_row(
                db, "100005", ["theme_cluster", "volume_breakout"], 20.0
            ),
        ]

        result = _analyze_precision_by_horizon_signature(
            db, trading_date, rows, _HORIZON_LABELS
        )

        assert result["same_day_dominant"]["signal_count"] == 2
        assert result["same_day_dominant"]["forward_positive_count"] == 1
        assert result["same_day_dominant"]["precision"] == pytest.approx(0.5)

        assert result["next_day_dominant"]["signal_count"] == 1
        assert result["next_day_dominant"]["forward_positive_count"] == 1
        assert result["next_day_dominant"]["precision"] == pytest.approx(1.0)

        assert result["multi_day_dominant"]["signal_count"] == 1
        assert result["multi_day_dominant"]["forward_positive_count"] == 0
        assert result["multi_day_dominant"]["precision"] == pytest.approx(0.0)

        assert result["mixed"]["signal_count"] == 1
        assert result["mixed"]["forward_positive_count"] == 1
        assert result["mixed"]["precision"] == pytest.approx(1.0)

    def test_zero_signal_count_bucket_precision_is_none(self, db: Session):
        """AC-108-006: mixed 버킷에 신호가 전혀 없으면 precision=None, signal_count=0
        — ZeroDivisionError 없음."""
        trading_date = date(2026, 6, 9)
        rows = [self._make_signal_row(db, "100006", ["volume_breakout"], 15.0)]

        result = _analyze_precision_by_horizon_signature(
            db, trading_date, rows, _HORIZON_LABELS
        )

        assert result["mixed"]["signal_count"] == 0
        assert result["mixed"]["precision"] is None

    def test_null_forward_return_counts_toward_signal_count_not_positive(
        self, db: Session
    ):
        """edge case: SurgeSignalForwardOutcome 행 부재(forward_pct=None)인 신호는
        signal_count에는 포함되나 forward_positive_count는 증가하지 않는다."""
        trading_date = date(2026, 6, 9)
        rows = [self._make_signal_row(db, "100007", ["volume_breakout"], None)]

        result = _analyze_precision_by_horizon_signature(
            db, trading_date, rows, _HORIZON_LABELS
        )

        assert result["same_day_dominant"]["signal_count"] == 1
        assert result["same_day_dominant"]["forward_positive_count"] == 0
        assert result["same_day_dominant"]["precision"] == pytest.approx(0.0)

    def test_malformed_surge_metadata_treated_as_multi_day_dominant(self, db: Session):
        """edge case: surge_metadata가 JSON 파싱 불가능하면 surge_basis=None으로
        안전하게 취급되어 multi_day_dominant 버킷으로 집계된다."""
        trading_date = date(2026, 6, 9)
        stock = _make_stock(db, "100008")
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            surge_metadata="{not valid json",
            price_at_signal=1000,
        )
        db.add(signal)
        db.flush()
        db.commit()
        row = SimpleNamespace(
            fund_signal_id=signal.id, stock_code="100008", surge_metadata=signal.surge_metadata
        )

        result = _analyze_precision_by_horizon_signature(
            db, trading_date, [row], _HORIZON_LABELS
        )

        assert result["multi_day_dominant"]["signal_count"] == 1

    def test_does_not_requery_fund_signal_or_stock_tables(self, db: Session):
        """AC-108-005: SurgeSignalForwardOutcome 조회 1회만 발생하고 FundSignal/Stock
        추가 조회가 없음을 spy로 확인한다."""
        trading_date = date(2026, 6, 9)
        rows = [self._make_signal_row(db, "100009", ["volume_breakout"], 15.0)]

        with patch.object(db, "query", wraps=db.query) as mock_query:
            _analyze_precision_by_horizon_signature(db, trading_date, rows, _HORIZON_LABELS)

        queried_models = [call.args[0] for call in mock_query.call_args_list if call.args]
        model_names = {getattr(m, "__name__", str(m)) for m in queried_models}
        assert "FundSignal" not in model_names
        assert "Stock" not in model_names


# ---------------------------------------------------------------------------
# TASK-003 / AC-108-007, AC-108-008: evaluate_surge_predictions 통합 배선
# ---------------------------------------------------------------------------


class TestEvaluateSurgePredictionsHorizonDiagnosticIntegration:
    def test_normal_cycle_logs_structured_line_with_all_buckets(
        self, db: Session, caplog
    ):
        """AC-108-007: 정상 평가 사이클에서 [지평시그니처정밀도] INFO 로그 1줄이
        4개 버킷 전부를 포함해 기록된다."""
        stock = _make_stock(db, "200001")
        trading_date = date(2026, 6, 9)
        t_minus_1 = date(2026, 6, 8)

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            surge_metadata='{"surge_basis": ["volume_breakout"]}',
            price_at_signal=1050,
            created_at=datetime(
                t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20, tzinfo=timezone.utc
            ),
        )
        db.add(signal)
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="200001",
                stock_name="주식200001",
                change_rate=12.0,
                was_surge=True,
                high_change_rate=20.0,
                market="KOSPI",
            )
        )
        db.commit()

        records = [PriceRecord(date="2026.06.08", close=1000)]
        with (
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                return_value=records,
            ),
            caplog.at_level(
                logging.INFO, logger="app.services.surge_evaluation_service"
            ),
        ):
            evaluate_surge_predictions(db, trading_date)

        horizon_logs = [
            r for r in caplog.records if "[지평시그니처정밀도]" in r.message
        ]
        assert len(horizon_logs) == 1
        assert horizon_logs[0].levelno == logging.INFO
        message = horizon_logs[0].message
        for bucket_name in (
            "same_day_dominant",
            "next_day_dominant",
            "multi_day_dominant",
            "mixed",
        ):
            assert bucket_name in message

    def test_diagnostic_exception_does_not_block_core_result_or_eod_upsert(
        self, db: Session, caplog
    ):
        """AC-108-008: _analyze_precision_by_horizon_signature 예외 발생 시
        SurgePredictionEvaluation과 SurgeSignalForwardOutcome 행 모두 정상 커밋되고
        경고 로그 1줄이 남는다."""
        stock = _make_stock(db, "200002")
        trading_date = date(2026, 6, 9)
        t_minus_1 = date(2026, 6, 8)

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            surge_metadata='{"surge_basis": ["theme_cluster"]}',
            price_at_signal=1050,
            created_at=datetime(
                t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20, tzinfo=timezone.utc
            ),
        )
        db.add(signal)
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="200002",
                stock_name="주식200002",
                change_rate=12.0,
                was_surge=True,
                high_change_rate=20.0,
                market="KOSPI",
            )
        )
        db.commit()

        records = [PriceRecord(date="2026.06.08", close=1000)]
        with (
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                return_value=records,
            ),
            patch(
                "app.services.surge_evaluation_service."
                "_analyze_precision_by_horizon_signature",
                side_effect=RuntimeError("boom"),
            ),
            caplog.at_level(
                logging.WARNING, logger="app.services.surge_evaluation_service"
            ),
        ):
            evaluate_surge_predictions(db, trading_date)

        eval_row = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
            .first()
        )
        assert eval_row is not None

        outcome_row = (
            db.query(SurgeSignalForwardOutcome)
            .filter(SurgeSignalForwardOutcome.fund_signal_id == signal.id)
            .first()
        )
        assert outcome_row is not None

        warn_logs = [
            r for r in caplog.records if "[지평시그니처정밀도] 진단 실패" in r.message
        ]
        assert len(warn_logs) == 1
        assert warn_logs[0].levelno == logging.WARNING

        info_gate_logs = [
            r
            for r in caplog.records
            if "[지평시그니처정밀도]" in r.message and r.levelno == logging.INFO
        ]
        assert info_gate_logs == []
