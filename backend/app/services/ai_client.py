"""AI 클라이언트 — Gemini 3키 라운드로빈 + Z.AI(GLM) fallback.

모든 AI 호출은 `ask_ai()`를 통해 수행한다.
Gemini API 키 3개를 순환하며, 전부 rate limit 소진 시 Z.AI GLM으로 fallback한다.
"""

import asyncio
import logging

import httpx

from app.config import settings
from app.services.circuit_breaker import api_circuit_breaker

logger = logging.getLogger(__name__)

# 라운드로빈 카운터 (모듈 수준 상태)
_call_counter: int = 0

_ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"


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


async def _call_zai(prompt: str) -> str | None:
    """Z.AI(GLM) API 호출 — OpenAI 호환 포맷.

    Gemini 전체 rate limit 소진 시 fallback으로 사용.
    GLM-4.7-Flash는 완전 무료.
    """
    if not settings.ZAI_API_KEY:
        return None

    payload = {
        "model": settings.ZAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {settings.ZAI_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{_ZAI_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


# @MX:ANCHOR: [AUTO] 모든 AI 호출의 진입점 — 키 순환 순서가 일일 사용량 분산에 영향
# @MX:REASON: Gemini 3키 라운드로빈 + Z.AI fallback 구조, 변경 시 전체 AI 기능에 영향
async def ask_ai_with_model(prompt: str, max_retries: int = 3) -> tuple[str | None, str]:
    """AI에 프롬프트를 전송하고 (응답 텍스트, 사용된 모델명) 튜플을 반환한다.

    1. Gemini 3개 키 라운드로빈 시도
    2. 전부 rate limit 소진 시 Z.AI(GLM) fallback
    """
    global _call_counter

    keys = _get_gemini_keys()
    gemini_errors = []

    if keys and api_circuit_breaker.is_available("gemini"):
        n_keys = len(keys)
        start_idx = _call_counter % n_keys
        _call_counter += 1

        for i in range(n_keys):
            key_idx = (start_idx + i) % n_keys
            key_name = f"Gemini-{key_idx + 1}"

            for attempt in range(max_retries):
                try:
                    result = await _call_gemini(prompt, keys[key_idx])
                    if result:
                        api_circuit_breaker.record_success("gemini")
                        return result, settings.GEMINI_MODEL
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = any(k in err_str for k in ("429", "RESOURCE_EXHAUSTED", "rate_limit"))
                    if is_rate_limit:
                        logger.warning(f"{key_name} rate limited, 다음 키로 전환")
                        gemini_errors.append(f"{key_name}: rate_limited")
                        break
                    elif attempt < max_retries - 1:
                        wait = 2 * (2 ** attempt)
                        logger.info(f"{key_name} 오류, {wait}초 후 재시도 (attempt {attempt + 1})")
                        await asyncio.sleep(wait)
                    else:
                        logger.warning(f"{key_name} 실패: {e}")
                        gemini_errors.append(f"{key_name}: {type(e).__name__}: {e}")
                        break

        if gemini_errors:
            api_circuit_breaker.record_failure("gemini")
            logger.warning(f"Gemini 전체 실패, Z.AI fallback 시도: {gemini_errors}")
        else:
            api_circuit_breaker.record_success("gemini")
    else:
        if not keys:
            logger.warning("Gemini API 키가 설정되지 않음 — Z.AI fallback 시도")
        else:
            logger.warning("Gemini 서킷 열림 — Z.AI fallback 시도")

    # Z.AI(GLM) fallback
    if settings.ZAI_API_KEY:
        try:
            result = await _call_zai(prompt)
            if result:
                logger.info(f"Z.AI({settings.ZAI_MODEL}) fallback 성공")
                return result, settings.ZAI_MODEL
        except Exception as e:
            logger.error(f"Z.AI fallback 실패: {e}")

    if gemini_errors:
        raise RuntimeError(f"모든 AI 키 실패 — Gemini: {gemini_errors}; Z.AI: 미설정 또는 실패")

    logger.warning("Gemini 키 없음, Z.AI 키 없음 — AI 호출 불가")
    return None, "unknown"


async def ask_ai(prompt: str, max_retries: int = 3) -> str | None:
    """AI에 프롬프트를 전송하고 응답 텍스트를 반환한다 (모델명 불필요한 호출용)."""
    result, _ = await ask_ai_with_model(prompt, max_retries)
    return result
