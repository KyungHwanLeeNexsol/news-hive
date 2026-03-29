"""
Redis 캐시 유틸리티 모듈.

Redis가 설정되지 않았거나 연결 실패 시 None을 반환하여
호출 측에서 인메모리 캐시로 폴백할 수 있도록 한다.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Redis 연결 풀 (싱글턴)
_redis_client = None
_redis_initialized = False

# 캐시 통계 (인메모리 카운터)
_cache_stats = {"hits": 0, "misses": 0}

# 키 접두사
KEY_PREFIX = "newshive:"


def _json_serializer(obj: Any) -> Any:
    """JSON 직렬화 시 datetime 등 특수 타입 처리."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"직렬화 불가능한 타입: {type(obj)}")


async def get_redis():
    """Redis 클라이언트를 반환. 사용 불가 시 None 반환."""
    global _redis_client, _redis_initialized

    if _redis_initialized:
        return _redis_client

    _redis_initialized = True

    from app.config import settings
    if not settings.REDIS_URL:
        logger.info("REDIS_URL 미설정 - 인메모리 캐시 폴백 사용")
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
        # 연결 확인
        await _redis_client.ping()
        logger.info("Redis 연결 성공")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis 연결 실패 - 인메모리 캐시 폴백 사용: {e}")
        _redis_client = None
        return None


async def cache_get(key: str) -> Optional[Any]:
    """
    Redis에서 캐시 값을 조회.

    Redis 미사용 또는 오류 시 None 반환 (호출 측에서 인메모리 폴백).
    """
    global _cache_stats

    r = await get_redis()
    if r is None:
        return None

    try:
        full_key = KEY_PREFIX + key
        raw = await r.get(full_key)
        if raw is None:
            _cache_stats["misses"] += 1
            return None
        _cache_stats["hits"] += 1
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"Redis cache_get 오류 ({key}): {e}")
        _cache_stats["misses"] += 1
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    """
    Redis에 캐시 값을 저장.

    Args:
        key: 캐시 키 (접두사 자동 추가)
        value: 저장할 값 (JSON 직렬화 가능해야 함)
        ttl: 만료 시간 (초), 기본 300초

    Returns:
        성공 여부. Redis 미사용 시 False.
    """
    r = await get_redis()
    if r is None:
        return False

    try:
        full_key = KEY_PREFIX + key
        raw = json.dumps(value, default=_json_serializer, ensure_ascii=False)
        await r.set(full_key, raw, ex=ttl)
        return True
    except Exception as e:
        logger.debug(f"Redis cache_set 오류 ({key}): {e}")
        return False


async def cache_delete(pattern: str) -> int:
    """
    패턴에 매칭되는 캐시 키 삭제.

    Args:
        pattern: 삭제할 키 패턴 (예: "api:news:*")

    Returns:
        삭제된 키 수. Redis 미사용 시 0.
    """
    r = await get_redis()
    if r is None:
        return 0

    try:
        full_pattern = KEY_PREFIX + pattern
        deleted = 0
        async for key in r.scan_iter(match=full_pattern, count=100):
            await r.delete(key)
            deleted += 1
        return deleted
    except Exception as e:
        logger.debug(f"Redis cache_delete 오류 ({pattern}): {e}")
        return 0


def get_cache_stats() -> dict:
    """캐시 적중/미스 통계 반환."""
    total = _cache_stats["hits"] + _cache_stats["misses"]
    return {
        "hits": _cache_stats["hits"],
        "misses": _cache_stats["misses"],
        "total": total,
        "hit_rate": round(_cache_stats["hits"] / total, 4) if total > 0 else 0.0,
    }


def reset_cache_stats() -> None:
    """캐시 통계 초기화."""
    global _cache_stats
    _cache_stats = {"hits": 0, "misses": 0}


async def close_redis() -> None:
    """Redis 연결 종료. 앱 셧다운 시 호출."""
    global _redis_client, _redis_initialized
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception:
            pass
    _redis_client = None
    _redis_initialized = False
