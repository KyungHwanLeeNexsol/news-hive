"""SPEC-FOLLOW-001 텔레그램 발송 서비스 단위 테스트.

httpx 및 settings를 Mock으로 대체하여 외부 API 호출 없이 발송 로직을 검증한다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# send_telegram_message 테스트
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_success() -> None:
    """텔레그램 API가 200을 반환하면 True를 반환한다."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch("app.services.telegram_service.settings") as mock_settings,
        patch("app.services.telegram_service.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.TELEGRAM_BOT_TOKEN = "test-bot-token"

        from app.services.telegram_service import send_telegram_message

        result = await send_telegram_message("123456789", "테스트 메시지")

    assert result is True


@pytest.mark.asyncio
async def test_send_message_http_error() -> None:
    """텔레그램 API가 비-200 상태를 반환하면 False를 반환한다."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch("app.services.telegram_service.settings") as mock_settings,
        patch("app.services.telegram_service.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.TELEGRAM_BOT_TOKEN = "test-bot-token"

        from app.services.telegram_service import send_telegram_message

        result = await send_telegram_message("123456789", "테스트 메시지")

    assert result is False


@pytest.mark.asyncio
async def test_send_message_no_token() -> None:
    """TELEGRAM_BOT_TOKEN이 빈 문자열이면 False를 반환하고 API를 호출하지 않는다."""
    with (
        patch("app.services.telegram_service.settings") as mock_settings,
        patch("app.services.telegram_service.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.TELEGRAM_BOT_TOKEN = ""  # 토큰 미설정

        from app.services.telegram_service import send_telegram_message

        result = await send_telegram_message("123456789", "테스트 메시지")

    # 토큰 없으면 httpx 호출 없이 즉시 False 반환
    assert result is False
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_exception() -> None:
    """네트워크 예외 발생 시 False를 반환하고 예외를 전파하지 않는다."""
    mock_client = AsyncMock()
    mock_client.post.side_effect = ConnectionError("네트워크 오류")
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch("app.services.telegram_service.settings") as mock_settings,
        patch("app.services.telegram_service.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.TELEGRAM_BOT_TOKEN = "test-bot-token"

        from app.services.telegram_service import send_telegram_message

        # 예외가 전파되지 않아야 한다
        result = await send_telegram_message("123456789", "테스트 메시지")

    assert result is False


@pytest.mark.asyncio
async def test_send_message_html_parse_mode() -> None:
    """parse_mode가 HTML로 설정되어 API 요청이 전송된다."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch("app.services.telegram_service.settings") as mock_settings,
        patch("app.services.telegram_service.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.TELEGRAM_BOT_TOKEN = "test-bot-token"

        from app.services.telegram_service import send_telegram_message

        result = await send_telegram_message(
            "123456789", "<b>굵은 텍스트</b>", parse_mode="HTML"
        )

    assert result is True
    # 전달된 payload에 parse_mode가 포함되어 있는지 확인
    call_kwargs = mock_client.post.call_args
    assert call_kwargs is not None
    json_payload = call_kwargs.kwargs.get("json", {})
    assert json_payload.get("parse_mode") == "HTML"
    assert json_payload.get("chat_id") == "123456789"
