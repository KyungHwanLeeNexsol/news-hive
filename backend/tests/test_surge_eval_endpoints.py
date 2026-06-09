"""SPEC-AI-041: 급등 평가 및 개선 이력 API 엔드포인트 테스트."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog
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
