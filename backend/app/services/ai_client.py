"""AI 클라이언트 — Gemini 다키 라운드로빈.

모든 AI 호출은 `ask_ai()`를 통해 수행한다.
Gemini API 키를 순환하며 호출한다. 전부 rate limit 소진 시 None을 반환한다.
"""

import asyncio
import logging
import time

from app.config import settings
from app.services.circuit_breaker import api_circuit_breaker

logger = logging.getLogger(__name__)

# 동시 API 호출 제한: 최대 3개 (Gemini 15 RPM 보호)
_ai_semaphore = asyncio.Semaphore(3)

# 키별 rate limit 쿨다운: {key_idx: monotonic_time_available_after}
_key_rate_limited_until: dict[int, float] = {}


def _get_gemini_keys() -> list[str]:
    """설정된 Gemini API 키 목록을 반환한다."""
    keys = []
    for key in [settings.GEMINI_API_KEY, settings.GEMINI_API_KEY_2, settings.GEMINI_API_KEY_3, settings.GEMINI_API_KEY_4]:
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


# @MX:ANCHOR: [AUTO] 모든 AI 호출의 진입점 — 유료 키(0번) 우선, 나머지는 fallback
# @MX:REASON: Key 0(유료)를 항상 먼저 시도하고 rate limit 시에만 무료 키로 순차 fallback
async def ask_ai_with_model(prompt: str, max_retries: int = 3) -> tuple[str | None, str]:
    """AI에 프롬프트를 전송하고 (응답 텍스트, 사용된 모델명) 튜플을 반환한다.

    GEMINI_API_KEY(유료)를 항상 먼저 시도한다.
    rate limit 등으로 실패 시 Key 2~4를 순차 fallback으로 사용한다.
    전부 소진되거나 서킷이 열린 경우 (None, "unknown")을 반환한다.
    """
    keys = _get_gemini_keys()

    if not keys:
        logger.warning("Gemini API 키가 설정되지 않음")
        return None, "unknown"

    if not api_circuit_breaker.is_available("gemini"):
        logger.warning("Gemini 서킷 열림 — AI 호출 불가")
        return None, "unknown"

    n_keys = len(keys)
    start_idx = 0  # 유료 키(Key 1)를 항상 먼저 시도

    gemini_errors = []

    async with _ai_semaphore:
        for i in range(n_keys):
            key_idx = (start_idx + i) % n_keys
            key_name = f"Gemini-{key_idx + 1}"

            # rate limit 쿨다운 중인 키 skip
            cooldown_until = _key_rate_limited_until.get(key_idx, 0.0)
            if cooldown_until > time.monotonic():
                remaining = cooldown_until - time.monotonic()
                logger.debug(f"{key_name} 쿨다운 중 ({remaining:.0f}초 남음), 다음 키로")
                gemini_errors.append(f"{key_name}: cooldown")
                continue

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
                        # 65초 쿨다운 설정 (1분 RPM 윈도우 + 5초 버퍼)
                        _key_rate_limited_until[key_idx] = time.monotonic() + 65
                        logger.warning(f"{key_name} rate limited (65초 쿨다운), 다음 키로 전환")
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

    # 전체 실패 — rate limit(쿨다운)과 실제 서비스 오류를 구분
    # rate limit만으로 모든 키가 차단된 경우는 서킷 브레이커 실패로 기록하지 않는다.
    # 서킷 브레이커는 실제 서비스 장애(네트워크 오류, 5xx 등)에만 반응해야 한다.
    all_rate_limited = all(
        ("rate_limited" in e or "cooldown" in e) for e in gemini_errors
    ) if gemini_errors else False

    if all_rate_limited:
        logger.warning(f"Gemini 전체 rate limited (서킷 브레이커 미적용): {gemini_errors}")
    else:
        api_circuit_breaker.record_failure("gemini")
        logger.warning(f"Gemini 서비스 오류 — 서킷 브레이커 실패 기록: {gemini_errors}")

    return None, "unknown"


async def _call_openai(prompt: str) -> str | None:
    """OpenAI API 호출 (Gemini 전체 실패 시 fallback).

    gpt-4o-mini를 사용하여 비용을 최소화한다.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    text = response.choices[0].message.content
    return text.strip() if text else None


async def ask_ai_with_openai_fallback(prompt: str, max_retries: int = 3) -> tuple[str | None, str]:
    """Gemini 우선 시도, 전체 실패 시 OpenAI fallback.

    Returns:
        (응답 텍스트, 사용된 모델명) 튜플
    """
    result, model = await ask_ai_with_model(prompt, max_retries)
    if result:
        return result, model

    # Gemini 전체 실패 → OpenAI fallback
    if not settings.OPENAI_API_KEY:
        return None, "unknown"

    try:
        text = await _call_openai(prompt)
        if text:
            logger.warning(f"OpenAI fallback 성공 ({settings.OPENAI_MODEL})")
            return text, settings.OPENAI_MODEL
    except Exception as e:
        logger.warning(f"OpenAI fallback 실패: {e}")

    return None, "unknown"


async def ask_ai(prompt: str, max_retries: int = 3) -> str | None:
    """AI에 프롬프트를 전송하고 응답 텍스트를 반환한다.

    Gemini 우선, 전체 실패 시 OpenAI로 자동 fallback.
    """
    result, _ = await ask_ai_with_openai_fallback(prompt, max_retries)
    return result
