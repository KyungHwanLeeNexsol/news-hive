"""Unified AI client with Groq (primary) + Gemini + OpenRouter fallback.

All AI calls in the project should go through `ask_ai()` instead of
calling individual providers directly.  This gives us:
  - Groq (free, high limit) as primary
  - Gemini as secondary
  - OpenRouter as tertiary fallback
  - Centralized rate-limit retry logic
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# OpenRouter free model — Gemini 2.0 Flash via OpenRouter has its own quota
OPENROUTER_DEFAULT_MODEL = "openrouter/free"


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


async def _call_openrouter(prompt: str) -> str | None:
    """Call OpenRouter API (OpenAI-compatible)."""
    if not settings.OPENROUTER_API_KEY:
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    model = settings.OPENROUTER_MODEL or OPENROUTER_DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            body = response.text[:500]
            raise RuntimeError(f"OpenRouter HTTP {response.status_code} (model={model}): {body}")
        data = response.json()
        choices = data.get("choices")
        if not choices:
            raise RuntimeError(f"OpenRouter empty choices: {data}")
        return choices[0]["message"]["content"].strip()


async def _call_gemini(prompt: str) -> str | None:
    """Call Gemini API directly."""
    if not settings.GEMINI_API_KEY:
        return None

    from google import genai

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
    )
    return response.text.strip()


async def ask_ai(prompt: str, max_retries: int = 3) -> str | None:
    """Send a prompt to AI and return the response text.

    Tries providers in order: Groq → Gemini → OpenRouter.
    Includes retry with exponential backoff for rate-limit errors.
    """
    providers = []
    if settings.GROQ_API_KEY:
        providers.append(("Groq", _call_groq))
    if settings.GEMINI_API_KEY:
        providers.append(("Gemini", _call_gemini))
    if settings.OPENROUTER_API_KEY:
        providers.append(("OpenRouter", _call_openrouter))

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
                if is_rate_limit and attempt < max_retries - 1:
                    wait = 5 * (2 ** attempt)
                    logger.info(f"{provider_name} rate limited, retrying in {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    logger.warning(f"{provider_name} failed: {e}")
                    errors.append(f"{provider_name}: {type(e).__name__}: {e}")
                    break  # Try next provider

    if errors:
        detail = "; ".join(errors)
        logger.error(f"All AI providers failed: {detail}")
        raise RuntimeError(f"모든 AI 프로바이더 실패 — {detail}")
    return None
