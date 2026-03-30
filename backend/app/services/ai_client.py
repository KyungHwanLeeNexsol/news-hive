"""Gemini 전용 AI 클라이언트 — 3개 API 키 라운드로빈.

모든 AI 호출은 `ask_ai()`를 통해 수행한다.
Gemini API 키 3개를 순환하여 일일 1000건 제한을 분산한다.
"""

import asyncio
import logging

from app.config import settings
from app.services.circuit_breaker import api_circuit_breaker

logger = logging.getLogger(__name__)

# 라운드로빈 카운터 (모듈 수준 상태)
_call_counter: int = 0


def _get_gemini_keys() -> list[str]:
    """설정된 Gemini API 키 목록을 반환한다."""
    keys = []
    for key in [settings.GEMINI_API_KEY, settings.GEMINI_API_KEY_2, settings.GEMINI_API_KEY_3]:
        if key:
            keys.append(key)
    return keys


async def _call_gemini(prompt: str, api_key: str) -> str | None:
    """Gemini API 호출.

    google.genai의 generate_content()는 동기 호출이므로
    asyncio.to_thread()로 감싸서 이벤트 루프 블로킹을 방지한다.
    """
    from google import genai

    client = genai.Client(api_key=api_key)

    def _sync_call() -> str | None:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()

    return await asyncio.to_thread(_sync_call)


# @MX:ANCHOR: [AUTO] 모든 AI 호출의 진입점 — 키 순환 순서가 일일 사용량 분산에 영향
# @MX:REASON: Gemini 3키 라운드로빈 구조, 변경 시 전체 AI 기능에 영향
async def ask_ai(prompt: str, max_retries: int = 3) -> str | None:
    """AI에 프롬프트를 전송하고 응답 텍스트를 반환한다.

    3개 Gemini API 키를 라운드로빈으로 순환한다.
    rate limit 발생 시 다음 키로 즉시 전환한다.
    """
    global _call_counter

    keys = _get_gemini_keys()
    if not keys:
        logger.warning("Gemini API 키가 설정되지 않음 — AI 호출 건너뜀")
        return None

    # 서킷 브레이커: Gemini 연속 실패 시 스킵
    if not api_circuit_breaker.is_available("gemini"):
        logger.warning("Gemini 서킷 열림, AI 호출 스킵")
        return None

    n_keys = len(keys)
    start_idx = _call_counter % n_keys
    _call_counter += 1

    errors = []

    # 라운드로빈 시작점부터 모든 키를 순회
    for i in range(n_keys):
        key_idx = (start_idx + i) % n_keys
        key_name = f"Gemini-{key_idx + 1}"

        for attempt in range(max_retries):
            try:
                result = await _call_gemini(prompt, keys[key_idx])
                if result:
                    api_circuit_breaker.record_success("gemini")
                    return result
            except Exception as e:
                err_str = str(e)
                is_rate_limit = any(k in err_str for k in ("429", "RESOURCE_EXHAUSTED", "rate_limit"))
                if is_rate_limit:
                    logger.warning(f"{key_name} rate limited, 다음 키로 전환")
                    errors.append(f"{key_name}: rate_limited")
                    break  # 다음 키로
                elif attempt < max_retries - 1:
                    wait = 2 * (2 ** attempt)
                    logger.info(f"{key_name} 오류, {wait}초 후 재시도 (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    logger.warning(f"{key_name} 실패: {e}")
                    errors.append(f"{key_name}: {type(e).__name__}: {e}")
                    break  # 다음 키로

    if errors:
        api_circuit_breaker.record_failure("gemini")
        detail = "; ".join(errors)
        logger.error(f"모든 Gemini 키 실패: {detail}")
        raise RuntimeError(f"모든 Gemini API 키 실패 — {detail}")

    api_circuit_breaker.record_success("gemini")
    return None
