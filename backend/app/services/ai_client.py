"""Unified AI client with OpenRouter (primary) + Gemini (fallback).

All AI calls in the project should go through `ask_ai()` instead of
calling Gemini directly.  This gives us:
  - OpenRouter free models as primary (separate quota)
  - Automatic fallback to Gemini if OpenRouter fails
  - Centralized rate-limit retry logic
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# OpenRouter free model — Gemini 2.0 Flash via OpenRouter has its own quota
OPENROUTER_DEFAULT_MODEL = "google/gemini-2.0-flash-exp:free"


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

    Tries OpenRouter first, then falls back to Gemini.
    Includes retry with exponential backoff for rate-limit errors.
    """
    providers = []
    if settings.OPENROUTER_API_KEY:
        providers.append(("OpenRouter", _call_openrouter))
    if settings.GEMINI_API_KEY:
        providers.append(("Gemini", _call_gemini))

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
                    errors.append(f"{provider_name}: {e}")
                    break  # Try next provider

    if errors:
        logger.error(f"All AI providers failed: {'; '.join(errors)}")
    return None
