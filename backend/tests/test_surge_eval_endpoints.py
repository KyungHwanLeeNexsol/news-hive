"""SPEC-AI-041: 급등 평가 및 개선 이력 API 엔드포인트 테스트."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch


from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog
from app.models.fund_signal import FundSignal
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation


# ---------------------------------------------------------------------------
# GET /api/surge-trading/evaluation
# ---------------------------------------------------------------------------

class TestGetEvaluations:
    def test_returns_list(self, client, db):
        """기본 응답이 리스트여야 한다."""
        response = client.get("/api/surge-trading/evaluation")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_returns_empty_when_no_data(self, client, db):
        """데이터 없으면 빈 리스트 반환."""
        response = client.get("/api/surge-trading/evaluation")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_evaluation_record(self, client, db):
        """평가 레코드가 있으면 정상 반환."""
        ev = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 9),
            predicted_count=10,
            actual_surge_count=8,
            true_positive=5,
            false_positive=5,
            false_negative=3,
            precision=0.5,
            recall=0.625,
            f1_score=0.556,
        )
        db.add(ev)
        db.commit()

        response = client.get("/api/surge-trading/evaluation")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["evaluation_date"] == "2026-06-09"
        assert data[0]["true_positive"] == 5
        assert data[0]["market_recall"] == 5 / 8
        assert data[0]["recall_basis"] == "market"

    def test_days_parameter_limits_results(self, client, db):
        """days=2 → 최대 2개 반환."""
        for i in range(5):
            ev = SurgePredictionEvaluation(
                evaluation_date=date(2026, 6, 9 - i),
                predicted_count=10,
                actual_surge_count=5,
                true_positive=3,
                false_positive=7,
                false_negative=2,
                precision=0.3,
                recall=0.6,
                f1_score=0.4,
            )
            db.add(ev)
        db.commit()

        response = client.get("/api/surge-trading/evaluation?days=2")
        assert response.status_code == 200
        assert len(response.json()) <= 2

    def test_exposes_market_and_scannable_recall_separately(self, client, db):
        """저장 recall과 시장 전체 recall을 별도 필드로 노출한다."""
        ev = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 12),
            predicted_count=4,
            actual_surge_count=8,
            true_positive=2,
            false_positive=2,
            false_negative=6,
            precision=0.5,
            recall=0.75,
            f1_score=0.333,
            scannable_recall=0.75,
            coverage=0.25,
            scannable_actual_count=2,
            total_actual_count=8,
            high_based_recall=0.4,
            high_based_precision=0.6,
            high_based_coverage=0.7,
        )
        db.add(ev)
        db.commit()

        response = client.get("/api/surge-trading/evaluation")
        assert response.status_code == 200
        row = response.json()[0]
        assert row["recall"] == 0.75
        assert row["market_recall"] == 0.25
        assert row["market_f1_score"] == 1 / 3
        assert row["recall_basis"] == "scannable"
        assert row["scannable_recall"] == 0.75
        assert row["coverage"] == 0.25
        assert row["high_based_recall"] == 0.4


# ---------------------------------------------------------------------------
# GET /api/surge-trading/evaluation/{date_str}
# ---------------------------------------------------------------------------

class TestGetEvaluationByDate:
    def test_404_for_missing_date(self, client, db):
        """존재하지 않는 날짜 → 404 반환."""
        response = client.get("/api/surge-trading/evaluation/2020-01-01")
        assert response.status_code == 404

    def test_400_for_invalid_date_format(self, client, db):
        """완전히 잘못된 날짜 형식 → 400 반환."""
        response = client.get("/api/surge-trading/evaluation/not-a-date")
        assert response.status_code == 400

    def test_returns_detail_with_miss_analysis(self, client, db):
        """상세 조회 시 miss_analysis_json 포함."""
        ev = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 9),
            predicted_count=5,
            actual_surge_count=3,
            true_positive=2,
            false_positive=3,
            false_negative=1,
            precision=0.4,
            recall=0.667,
            f1_score=0.5,
            miss_analysis_json="LLM 분석 결과 텍스트",
        )
        db.add(ev)
        db.commit()

        response = client.get("/api/surge-trading/evaluation/2026-06-09")
        assert response.status_code == 200
        data = response.json()
        assert data["evaluation_date"] == "2026-06-09"
        assert data["miss_analysis_json"] == "LLM 분석 결과 텍스트"
        assert "improvements_applied_json" in data
        assert data["market_recall"] == 2 / 3
        assert data["recall_basis"] == "market"


# ---------------------------------------------------------------------------
# GET /api/surge-trading/improvements
# ---------------------------------------------------------------------------

class TestGetImprovements:
    def test_returns_list(self, client, db):
        """기본 응답이 리스트여야 한다."""
        response = client.get("/api/surge-trading/improvements")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_returns_improvement_records(self, client, db):
        """개선 이력 레코드 정상 반환."""
        log = SurgeAutoImprovementLog(
            evaluation_date=date(2026, 6, 9),
            parameter_path="ensemble.weights.theme_cluster",
            old_value=0.25,
            new_value=0.28,
            rationale="테스트 사유",
            rolling_window_days=5,
        )
        db.add(log)
        db.commit()

        response = client.get("/api/surge-trading/improvements")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["parameter_path"] == "ensemble.weights.theme_cluster"
        assert abs(data[0]["old_value"] - 0.25) < 1e-6
        assert abs(data[0]["new_value"] - 0.28) < 1e-6


# ---------------------------------------------------------------------------
# GET /api/surge-trading/prediction-history
# ---------------------------------------------------------------------------

class TestGetPredictionHistory:
    def test_evaluated_row_uses_stored_predicted_count_when_signal_date_drifts(
        self, client, db, make_stock
    ):
        """평가 완료 행의 predicted_count는 현재 FundSignal 재조회 결과로 덮지 않는다."""
        from app.services.surge_trading_service import _get_prev_business_day

        eval_date = date(2026, 6, 10)
        signal_date = _get_prev_business_day(eval_date)
        stock = make_stock(name="히스토리드리프트종목", stock_code="909041")

        db.add(SurgePredictionEvaluation(
            evaluation_date=eval_date,
            predicted_count=7,
            actual_surge_count=3,
            true_positive=1,
            false_positive=6,
            false_negative=2,
            precision=1 / 7,
            recall=1 / 3,
            f1_score=0.2,
        ))
        db.add(FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.8,
            reasoning="테스트 시그널",
            signal_type="surge_candidate",
            surge_metadata='{"surge_basis": ["theme_cluster"]}',
            originally_created_at=datetime.combine(
                signal_date, datetime.min.time()
            ).replace(hour=15, minute=20),
            created_at=datetime(2026, 6, 10, 10, 0),
        ))
        db.commit()

        response = client.get("/api/surge-trading/prediction-history?days=90")
        assert response.status_code == 200

        row = next(
            r for r in response.json()
            if r["target_date"] == eval_date.isoformat()
        )
        assert row["trading_date"] == signal_date.isoformat()
        assert row["predicted_count"] == 7


# ---------------------------------------------------------------------------
# POST /api/surge-trading/evaluation-backfill
# ---------------------------------------------------------------------------

class TestEvaluationBackfill:
    def test_requires_admin(self, client):
        response = client.post(
            "/api/surge-trading/evaluation-backfill?start_date=2026-08-04"
        )
        assert response.status_code == 401

    def test_runs_backfill_for_business_date_range(self, client):
        calls = []

        def fake_repair(db, trading_date, **kwargs):
            calls.append((trading_date, kwargs))
            return {
                "trading_date": str(trading_date),
                "status": "repaired",
                "before": {
                    "trading_date": str(trading_date),
                    "actual_outcome_missing": True,
                    "evaluation_missing": True,
                },
                "after": {
                    "trading_date": str(trading_date),
                    "actual_outcome_missing": False,
                    "evaluation_missing": False,
                },
            }

        with (
            patch("app.routers.auth._verify_admin_token", return_value=True),
            patch(
                "app.services.surge_evaluation_service.repair_missing_surge_evaluation",
                side_effect=fake_repair,
            ),
        ):
            response = client.post(
                "/api/surge-trading/evaluation-backfill"
                "?start_date=2026-08-04&end_date=2026-08-06&force_re_evaluate=true",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert data["failed_count"] == 0
        assert [row["trading_date"] for row in data["results"]] == [
            "2026-08-04",
            "2026-08-05",
            "2026-08-06",
        ]
        assert len(calls) == 3
        assert all(call[1]["force_re_evaluate"] is True for call in calls)
