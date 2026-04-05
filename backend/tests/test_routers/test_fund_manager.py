"""AI 펀드매니저 라우터 통합 테스트.

GET /api/fund/briefing, GET /api/fund/signals, GET /api/fund/accuracy,
POST /api/fund/verify 등 엔드포인트를 검증한다.

모든 fund_manager 엔드포인트는 관리자 인증(Bearer 토큰)이 필요하다.
인증 우회 및 거부 시나리오를 함께 테스트한다.
"""

import time
from datetime import date
from unittest.mock import patch

import pytest

from app.routers.auth import _active_tokens, TOKEN_TTL


# ---------------------------------------------------------------------------
# 인증 헬퍼
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_token() -> str:
    """유효한 관리자 토큰을 _active_tokens에 직접 삽입한다."""
    token = "test-admin-token-valid"
    _active_tokens[token] = time.time() + TOKEN_TTL
    yield token
    _active_tokens.pop(token, None)


@pytest.fixture
def admin_headers(admin_token: str) -> dict[str, str]:
    """인증 헤더를 반환한다."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def expired_token() -> str:
    """만료된 관리자 토큰."""
    token = "test-admin-token-expired"
    _active_tokens[token] = time.time() - 1  # 이미 만료됨
    yield token
    _active_tokens.pop(token, None)


# ---------------------------------------------------------------------------
# 인증 거부 테스트
# ---------------------------------------------------------------------------

class TestFundManagerAuth:
    """fund_manager 엔드포인트의 인증 검증 테스트."""

    def test_no_auth_header_returns_401(self, client):
        """인증 헤더가 없으면 401을 반환한다."""
        resp = client.get("/api/fund/signals")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        """잘못된 토큰으로 요청하면 401을 반환한다."""
        resp = client.get(
            "/api/fund/signals",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client, expired_token):
        """만료된 토큰으로 요청하면 401을 반환한다."""
        resp = client.get(
            "/api/fund/signals",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, client):
        """Bearer 접두사 없이 토큰만 보내면 401을 반환한다."""
        resp = client.get(
            "/api/fund/signals",
            headers={"Authorization": "some-token-without-bearer"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/fund/signals -- 투자 시그널 목록 조회
# ---------------------------------------------------------------------------

class TestGetSignals:
    """GET /api/fund/signals 엔드포인트 테스트."""

    def test_signals_empty(self, client, admin_headers):
        """시그널이 없으면 빈 리스트를 반환한다."""
        resp = client.get("/api/fund/signals", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_signals_with_data(self, client, admin_headers, make_fund_signal):
        """시그널이 있으면 최근 시그널을 반환한다."""
        sig = make_fund_signal(signal="buy", confidence=0.85)
        resp = client.get("/api/fund/signals", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["signal"] == "buy"
        assert data[0]["confidence"] == 0.85

    def test_signals_limit_param(self, client, admin_headers, make_fund_signal, make_stock):
        """limit 파라미터로 반환 개수를 제한할 수 있다."""
        # 서로 다른 stock_id로 시그널 생성 (중복 제거 로직 대응)
        for _ in range(5):
            stock = make_stock()
            make_fund_signal(stock_id=stock.id)

        resp = client.get("/api/fund/signals", params={"limit": 2}, headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# GET /api/fund/briefing -- 데일리 브리핑 조회
# ---------------------------------------------------------------------------

class TestGetBriefing:
    """GET /api/fund/briefing 엔드포인트 테스트."""

    def test_briefing_not_found(self, client, admin_headers):
        """오늘 날짜의 브리핑이 없으면 None(null)을 반환한다."""
        resp = client.get("/api/fund/briefing", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() is None

    def test_briefing_with_data(self, client, admin_headers, db):
        """브리핑 데이터가 있으면 해당 브리핑을 반환한다."""
        from app.models.daily_briefing import DailyBriefing

        briefing = DailyBriefing(
            briefing_date=date.today(),
            market_overview="오늘 시장은 상승세입니다.",
            sector_highlights="반도체 섹터 강세",
            stock_picks="삼성전자 주목",
        )
        db.add(briefing)
        db.flush()

        resp = client.get("/api/fund/briefing", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["market_overview"] == "오늘 시장은 상승세입니다."
        assert data["briefing_date"] == str(date.today())

    def test_briefing_with_target_date(self, client, admin_headers, db):
        """target_date 파라미터로 특정 날짜 브리핑을 조회할 수 있다."""
        from app.models.daily_briefing import DailyBriefing

        target = date(2025, 1, 15)
        briefing = DailyBriefing(
            briefing_date=target,
            market_overview="2025-01-15 시장 요약",
        )
        db.add(briefing)
        db.flush()

        resp = client.get(
            "/api/fund/briefing",
            params={"target_date": "2025-01-15"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["briefing_date"] == "2025-01-15"


# ---------------------------------------------------------------------------
# GET /api/fund/accuracy -- 적중률 통계
# ---------------------------------------------------------------------------

class TestGetAccuracy:
    """GET /api/fund/accuracy 엔드포인트 테스트."""

    @patch("app.services.signal_verifier.get_accuracy_stats")
    def test_accuracy_stats(self, mock_stats, client, admin_headers):
        """적중률 통계를 반환한다."""
        mock_stats.return_value = {
            "total": 10,
            "correct": 7,
            "accuracy": 0.7,
            "avg_return": 2.5,
            "buy_accuracy": 0.8,
            "sell_accuracy": 0.6,
            "by_confidence": {},
        }
        resp = client.get("/api/fund/accuracy", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert data["accuracy"] == 0.7

    @patch("app.services.signal_verifier.get_accuracy_stats")
    def test_accuracy_with_days_param(self, mock_stats, client, admin_headers):
        """days 파라미터를 전달할 수 있다."""
        mock_stats.return_value = {
            "total": 0,
            "correct": 0,
            "accuracy": 0.0,
            "avg_return": 0.0,
            "buy_accuracy": 0.0,
            "sell_accuracy": 0.0,
            "by_confidence": {},
        }
        resp = client.get(
            "/api/fund/accuracy",
            params={"days": 60},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        # days=60 인자가 서비스 함수에 전달되었는지 확인
        mock_stats.assert_called_once()
        call_kwargs = mock_stats.call_args
        # get_accuracy_stats(db, days=60) 형태로 호출됨
        assert call_kwargs[1].get("days") == 60 or (len(call_kwargs[0]) >= 2 and call_kwargs[0][1] == 60)
