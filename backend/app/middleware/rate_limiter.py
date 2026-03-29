"""
Redis 기반 슬라이딩 윈도우 Rate Limiter 미들웨어.

Redis 미사용 시 제한 없이 모든 요청을 허용한다 (graceful degradation).
"""

import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 고비용 엔드포인트 목록 (분당 10회 제한)
EXPENSIVE_ENDPOINTS = [
    "POST /api/news/refresh",
    "POST /api/fund-manager/",
    "POST /api/stocks/infer-relations",
]


def _is_expensive(method: str, path: str) -> bool:
    """요청이 고비용 엔드포인트인지 확인."""
    key = f"{method} {path}"
    for ep in EXPENSIVE_ENDPOINTS:
        if key.startswith(ep):
            return True
    return False


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Redis 슬라이딩 윈도우 기반 분당 요청 제한 미들웨어."""

    async def dispatch(self, request: Request, call_next):
        # Redis 연결 확인
        try:
            from app.cache import get_redis
            r = await get_redis()
        except Exception:
            r = None

        # Redis 미사용 시 제한 없이 통과
        if r is None:
            return await call_next(request)

        # 클라이언트 IP 추출
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        # 설정에서 제한값 로드
        from app.config import settings
        is_expensive = _is_expensive(method, path)
        limit = settings.RATE_LIMIT_EXPENSIVE_PER_MINUTE if is_expensive else settings.RATE_LIMIT_PER_MINUTE

        # 슬라이딩 윈도우 키: IP + 분 단위 버킷
        minute_bucket = int(time.time() // 60)
        rate_type = "expensive" if is_expensive else "general"
        redis_key = f"newshive:ratelimit:{client_ip}:{rate_type}:{minute_bucket}"

        try:
            # 현재 카운트 증가 + 확인 (원자적)
            current = await r.incr(redis_key)
            if current == 1:
                # 첫 요청: 2분 TTL (다음 분 버킷 전환 시 자동 삭제)
                await r.expire(redis_key, 120)

            if current > limit:
                retry_after = 60 - int(time.time() % 60)
                logger.warning(
                    f"Rate limit 초과: {client_ip} ({rate_type}) "
                    f"{current}/{limit} req/min"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too Many Requests",
                        "detail": f"분당 {limit}회 요청 제한 초과",
                        "retry_after": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        except Exception as e:
            # Redis 오류 시 제한 없이 통과 (graceful degradation)
            logger.debug(f"Rate limiter Redis 오류 - 통과 허용: {e}")

        return await call_next(request)
