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


# ---------------------------------------------------------------------------
# 영구 차단(403 blocked by the user) 감지 테스트
# 프로덕션 버그: 사용자가 봇을 차단해도 매 알림마다 재시도하며 에러 로그가 반복 발생
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_permanent_block_sets_result_info() -> None:
    """403 'Forbidden: bot was blocked by the user' 응답 시 result_info에
    영구 차단 신호를 남긴다. 반환값(bool) 계약은 기존과 동일하게 유지된다."""
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = (
        '{"ok":false,"error_code":403,'
        '"description":"Forbidden: bot was blocked by the user"}'
    )

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

        result_info: dict = {}
        result = await send_telegram_message(
            "123456789", "테스트 메시지", result_info=result_info
        )

    assert result is False  # 기존 호출자와의 계약(bool) 유지
    assert result_info.get("permanently_blocked") is True


@pytest.mark.asyncio
async def test_send_message_other_error_does_not_set_permanent_block() -> None:
    """403이 아니거나 차단 문구가 없는 실패는 영구 차단으로 표시하지 않는다."""
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

        result_info: dict = {}
        result = await send_telegram_message(
            "123456789", "테스트 메시지", result_info=result_info
        )

    assert result is False
    assert result_info.get("permanently_blocked") is False


@pytest.mark.asyncio
async def test_send_message_result_info_none_by_default() -> None:
    """result_info를 전달하지 않는 기존 호출자는 아무 영향을 받지 않는다."""
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden: bot was blocked by the user"

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

        # result_info 생략 — 기존 호출자(scheduler.py, surge_auto_improver.py 등)와 동일
        result = await send_telegram_message("123456789", "테스트 메시지")

    assert result is False
