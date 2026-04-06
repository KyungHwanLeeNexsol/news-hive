"""텔레그램 Bot API 메시지 발송 서비스 (SPEC-FOLLOW-001)."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# @MX:ANCHOR: [AUTO] send_telegram_message — 키워드 매처와 webhook 핸들러가 호출하는 발송 함수
# @MX:REASON: keyword_matcher(스케줄러)와 following 라우터(webhook)에서 호출됨
async def send_telegram_message(
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: dict | None = None,
) -> bool:
    """텔레그램 Bot API로 메시지를 발송한다.

    Args:
        chat_id: 텔레그램 채팅 ID
        text: 발송할 메시지 내용 (HTML 마크업 지원)
        parse_mode: 텍스트 파싱 모드 (기본값: HTML)
        reply_markup: 인라인 키보드 등 reply markup JSON 객체

    Returns:
        True: 발송 성공, False: 발송 실패 또는 토큰 미설정
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN 미설정 — 텔레그램 발송 스킵")
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.error(f"텔레그램 발송 실패: {resp.status_code} {resp.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"텔레그램 발송 예외: {e}")
            return False


async def answer_callback_query(callback_query_id: str, text: str = "") -> bool:
    """텔레그램 Callback Query에 응답한다 (로딩 표시 해제).

    Args:
        callback_query_id: 콜백 쿼리 ID
        text: 팝업으로 표시할 텍스트 (최대 200자)

    Returns:
        True: 성공, False: 실패
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"answerCallbackQuery 예외: {e}")
            return False
