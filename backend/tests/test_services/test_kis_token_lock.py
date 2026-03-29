"""KIS API 토큰 락(asyncio.Lock) 검증 테스트.

REQ-FIX-011: 동시 토큰 갱신 경쟁 조건 방지를 검증한다.
"""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_token_cache():
    """각 테스트 전 토큰 캐시를 초기화한다."""
    from app.services.kis_api import _token_cache
    _token_cache.access_token = ""
    _token_cache.expires_at = 0.0
    yield
    _token_cache.access_token = ""
    _token_cache.expires_at = 0.0


class TestKISTokenLock:
    """KIS API 토큰 갱신 락 테스트."""

    @pytest.mark.asyncio
    async def test_concurrent_token_refresh_calls_api_once(self):
        """동시에 여러 코루틴이 토큰을 요청해도 API는 1회만 호출된다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "test-token-123",
            "expires_in": 86400,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.kis_api.settings") as mock_settings:
            mock_settings.KIS_APP_KEY = "test-key"
            mock_settings.KIS_APP_SECRET = "test-secret"
            mock_settings.KIS_TOKEN_REFRESH_MARGIN_SECONDS = 60
            mock_settings.KIS_TOKEN_DEFAULT_EXPIRES = 86400

            from app.services.kis_api import _get_access_token

            # 5개 코루틴이 동시에 토큰을 요청
            results = await asyncio.gather(
                _get_access_token(mock_client),
                _get_access_token(mock_client),
                _get_access_token(mock_client),
                _get_access_token(mock_client),
                _get_access_token(mock_client),
            )

            # 모든 코루틴이 동일한 토큰을 받음
            assert all(r == "test-token-123" for r in results)
            # API는 1회만 호출됨 (더블 체크 패턴)
            assert mock_client.post.call_count == 1
