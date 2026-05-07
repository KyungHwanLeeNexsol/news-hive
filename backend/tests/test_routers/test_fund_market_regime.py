"""SPEC-AI-015: GET /api/fund/market-regime 엔드포인트 테스트."""

import datetime
from unittest.mock import patch

import pytest

from app.models.market_regime import MarketRegime, MarketRegimeEnum


# ---------------------------------------------------------------------------
# GET /api/fund/market-regime 엔드포인트 테스트
# ---------------------------------------------------------------------------

class TestGetMarketRegime:
    """GET /api/fund/market-regime 테스트."""

    def _admin_headers(self):
        """관리자 인증 헤더."""
        return {"Authorization": "Bearer test-admin-token"}

    def test_200_ok_response_structure(self, client, db):
        """정상 응답 구조 검증: today + history 키가 존재한다."""
        today = datetime.date.today()
        db.add(MarketRegime(
            date=today,
            regime=MarketRegimeEnum.SIDEWAYS,
            kospi_5d_return=0.5,
            kospi_20d_ma_position=0.3,
            confidence_score=0.6,
        ))
        db.commit()

        with patch("app.routers.auth._verify_admin_token", return_value=True):
            resp = client.get(
                "/api/fund/market-regime",
                headers=self._admin_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "today" in data
        assert "history" in data

    def test_today_response_has_required_fields(self, client, db):
        """today 응답에 필수 필드가 모두 포함된다."""
        today = datetime.date.today()
        db.add(MarketRegime(
            date=today,
            regime=MarketRegimeEnum.BULL,
            kospi_5d_return=2.5,
            kospi_20d_ma_position=1.8,
            confidence_score=0.75,
        ))
        db.commit()

        with patch("app.routers.auth._verify_admin_token", return_value=True):
            resp = client.get(
                "/api/fund/market-regime",
                headers=self._admin_headers(),
            )

        today_data = resp.json()["today"]
        assert "date" in today_data
        assert "regime" in today_data
        assert "kospi_5d_return" in today_data
        assert "kospi_20d_ma_position" in today_data
        assert "confidence_score" in today_data
        assert "params" in today_data

    def test_today_params_has_required_fields(self, client, db):
        """params 응답에 모든 레짐 파라미터가 포함된다."""
        today = datetime.date.today()
        db.add(MarketRegime(
            date=today,
            regime=MarketRegimeEnum.BEAR,
            kospi_5d_return=-2.0,
            kospi_20d_ma_position=-3.0,
            confidence_score=0.7,
        ))
        db.commit()

        with patch("app.routers.auth._verify_admin_token", return_value=True):
            resp = client.get(
                "/api/fund/market-regime",
                headers=self._admin_headers(),
            )

        params = resp.json()["today"]["params"]
        assert "min_action_confidence" in params
        assert "max_position_pct_high" in params
        assert "target_pct_max" in params
        assert "stop_loss_pct_default" in params
        assert "max_daily_trades" in params

    def test_empty_db_returns_sideways_default(self, client, db):
        """DB에 오늘 레짐이 없으면 SIDEWAYS 기본값을 반환한다."""
        with (
            patch("app.routers.auth._verify_admin_token", return_value=True),
            patch(
                "app.services.market_regime_service._fetch_kospi_indicators",
                side_effect=ValueError("데이터 없음"),
            ),
        ):
            resp = client.get(
                "/api/fund/market-regime",
                headers=self._admin_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["today"]["regime"] == "SIDEWAYS"
        assert data["today"]["confidence_score"] == 0.5

    def test_history_sorted_descending_by_date(self, client, db):
        """히스토리는 날짜 역순으로 반환된다."""
        today = datetime.date.today()
        for i in range(3):
            db.add(MarketRegime(
                date=today - datetime.timedelta(days=i),
                regime=MarketRegimeEnum.SIDEWAYS,
                kospi_5d_return=float(i),
                kospi_20d_ma_position=0.0,
                confidence_score=0.6,
            ))
        db.commit()

        with patch("app.routers.auth._verify_admin_token", return_value=True):
            resp = client.get(
                "/api/fund/market-regime",
                headers=self._admin_headers(),
            )

        history = resp.json()["history"]
        assert len(history) >= 3
        # 날짜 역순 확인
        dates = [h["date"] for h in history]
        assert dates == sorted(dates, reverse=True)

    def test_bull_regime_has_bull_params(self, client, db):
        """BULL 레짐일 때 올바른 파라미터 값이 반환된다."""
        today = datetime.date.today()
        db.add(MarketRegime(
            date=today,
            regime=MarketRegimeEnum.BULL,
            kospi_5d_return=3.0,
            kospi_20d_ma_position=2.0,
            confidence_score=0.8,
        ))
        db.commit()

        with patch("app.routers.auth._verify_admin_token", return_value=True):
            resp = client.get(
                "/api/fund/market-regime",
                headers=self._admin_headers(),
            )

        params = resp.json()["today"]["params"]
        assert params["min_action_confidence"] == 0.48
        assert params["max_position_pct_high"] == 0.20
        assert params["max_daily_trades"] == 7
