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
) -> bool:
    """텔레그램 Bot API로 메시지를 발송한다.

    Args:
        chat_id: 텔레그램 채팅 ID
        text: 발송할 메시지 내용 (HTML 마크업 지원)
        parse_mode: 텍스트 파싱 모드 (기본값: HTML)

    Returns:
        True: 발송 성공, False: 발송 실패 또는 토큰 미설정
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN 미설정 — 텔레그램 발송 스킵")
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

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
