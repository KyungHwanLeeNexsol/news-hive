"""Unified AI client with Groq (primary) + Gemini x3 fallback.

All AI calls in the project should go through `ask_ai()` instead of
calling individual providers directly.  This gives us:
  - Groq (free, high limit) as primary
  - Gemini key 1, 2, 3 as sequential fallbacks (free tier rate limit rotation)
  - Centralized rate-limit retry logic
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def _call_groq(prompt: str) -> str | None:
    """Call Groq API (OpenAI-compatible)."""
    if not settings.GROQ_API_KEY:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            body = response.text[:500]
            raise RuntimeError(f"Groq HTTP {response.status_code}: {body}")
        data = response.json()
        choices = data.get("choices")
        if not choices:
            raise RuntimeError(f"Groq empty choices: {data}")
        return choices[0]["message"]["content"].strip()


async def _call_gemini_key(prompt: str, api_key: str) -> str | None:
    """Call Gemini API with a specific API key."""
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
    )
    return response.text.strip()


async def ask_ai(prompt: str, max_retries: int = 3) -> str | None:
    """Send a prompt to AI and return the response text.

    Tries providers in order: Groq → Gemini key1 → Gemini key2 → Gemini key3.
    On rate limit, immediately falls through to the next provider/key.
    """
    # # @MX:ANCHOR: 모든 AI 호출의 진입점 — 프로바이더 순서가 비용과 가용성에 영향
    # # @MX:REASON: Groq(1차) → Gemini 3키 순환(2~4차) 구조, 변경 시 전체 AI 기능에 영향
    # (name, callable(prompt) -> str | None) 쌍 목록
    providers: list[tuple[str, object]] = []

    if settings.GROQ_API_KEY:
        providers.append(("Groq", _call_groq))

    # Gemini 키 3개를 순서대로 추가 (rate limit 시 다음 키로 fallback)
    for idx, key in enumerate(
        [settings.GEMINI_API_KEY, settings.GEMINI_API_KEY_2, settings.GEMINI_API_KEY_3],
        start=1,
    ):
        if key:
            def _make_gemini_fn(k: str):
                async def _fn(p: str) -> str | None:
                    return await _call_gemini_key(p, k)
                return _fn
            providers.append((f"Gemini-{idx}", _make_gemini_fn(key)))

    if not providers:
        logger.warning("No AI API keys configured — skipping AI call")
        return None

    errors = []

    for provider_name, call_fn in providers:
        for attempt in range(max_retries):
            try:
                result = await call_fn(prompt)
                if result:
                    return result
            except Exception as e:
                err_str = str(e)
                is_rate_limit = any(k in err_str for k in ("429", "RESOURCE_EXHAUSTED", "rate_limit"))
                if is_rate_limit:
                    logger.warning(f"{provider_name} rate limited, trying next key/provider")
                    errors.append(f"{provider_name}: rate_limited")
                    break
                elif attempt < max_retries - 1:
                    wait = 2 * (2 ** attempt)
                    logger.info(f"{provider_name} error, retrying in {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    logger.warning(f"{provider_name} failed: {e}")
                    errors.append(f"{provider_name}: {type(e).__name__}: {e}")
                    break

    if errors:
        detail = "; ".join(errors)
        logger.error(f"All AI providers failed: {detail}")
        raise RuntimeError(f"모든 AI 프로바이더 실패 — {detail}")
    return None
